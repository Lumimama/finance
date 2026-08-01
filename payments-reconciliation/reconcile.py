"""
Payments Reconciliation Engine
==============================
Match a processor ledger against a bank settlement file, classify every break,
age the open items by dollar exposure, and produce the exception report a
settlement-operations team would actually work from.

Why this exists
---------------
At transaction scale, reconciliation is not a spreadsheet task. 50,000
transactions with a 2% break rate is 1,000 exceptions -- and the job is not
finding them (a VLOOKUP finds them), it's *classifying* them, because the
classification decides who works the item:

    timing lag        -> nobody; it self-heals, but must be aged and watched
    amount mismatch   -> merchant ops (tip adjustments, partial captures)
    missing at bank   -> settlement ops, urgently; this is our money in limbo
    missing in ledger -> finance + engineering; we're being paid for unknowns
    duplicate         -> bank relations; recovery of double-settled funds
    fx variance       -> treasury; rate-source disagreement
    fee discrepancy   -> network relations; interchange charged off schedule

A reconciliation that says "1,148 unmatched" is noise. One that says "$41K of
fee overcharges concentrated in card-present credit" is an action item.

Method
------
1. Exact-key match on txn_id (the happy path -- ~98% clears here)
2. Classify the residual by comparing field-by-field within matched keys
   (amount, fees, FX, settlement date) and by presence/absence across files
3. Tolerance: $0.01 on amounts. Everything above tolerance is a break.
4. Age open items from settlement-due date; band by exposure.

Run:  python3 reconcile.py            console report
      python3 reconcile.py --html examples/recon_dashboard.html
      python3 reconcile.py --validate  score against data/seeded_breaks.json

No dependencies. Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).parent / "data"
AS_OF = date(2026, 6, 16)          # two days after the last settlement day
TOL = 0.01                          # amount tolerance, USD
EXPECTED_LAG_DAYS = 1               # contractual T+1 settlement


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def load() -> tuple[list[dict], list[dict]]:
    with (DATA / "processor_ledger.csv").open() as f:
        ledger = list(csv.DictReader(f))
    with (DATA / "bank_settlement.csv").open() as f:
        settle = list(csv.DictReader(f))
    for r in ledger:
        for k in ("local_amount", "fx_rate", "gross_usd", "expected_interchange",
                  "expected_scheme_fee", "expected_net"):
            r[k] = float(r[k])
    for s in settle:
        for k in ("gross_usd", "interchange", "scheme_fee", "net_usd"):
            s[k] = float(s[k])
    return ledger, settle


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------
def reconcile(ledger: list[dict], settle: list[dict]) -> dict:
    led_by_id = {r["txn_id"]: r for r in ledger}

    # Group settlements by reference -- duplicates are >1 row per reference.
    stl_by_ref: dict[str, list[dict]] = defaultdict(list)
    for s in settle:
        stl_by_ref[s["txn_ref"]].append(s)

    exceptions: list[dict] = []
    matched = 0

    def exc(kind: str, txn: dict | None, stl: dict | None, exposure: float,
            detail: str) -> None:
        ref = (txn or {}).get("txn_id") or (stl or {}).get("txn_ref", "?")
        txn_date = (txn or {}).get("txn_date") or (stl or {}).get("settle_date")
        due = date.fromisoformat(txn_date) + timedelta(days=EXPECTED_LAG_DAYS)
        exceptions.append({
            "txn_id": ref,
            "type": kind,
            "rail": (txn or {}).get("rail", "unknown"),
            "exposure_usd": round(exposure, 2),
            "age_days": max(0, (AS_OF - due).days),
            "detail": detail,
        })

    for txn_id, txn in led_by_id.items():
        rows = stl_by_ref.get(txn_id, [])

        if not rows:
            # Sign convention throughout: positive exposure = we hold funds we
            # may not be entitled to; negative = the bank owes us. A missing
            # settlement is money due to us, hence negative.
            exc("missing_at_bank", txn, None, -txn["expected_net"],
                f"no settlement received; {txn['expected_net']:.2f} net due")
            continue

        if len(rows) > 1:
            # First settlement is presumed good; extras are the duplicates.
            rows_sorted = sorted(rows, key=lambda s: s["settle_date"])
            dup_amt = sum(s["net_usd"] for s in rows_sorted[1:])
            exc("duplicate_settlement", txn, rows_sorted[1], dup_amt,
                f"settled {len(rows)}x; {dup_amt:.2f} over-received")
            rows = rows_sorted[:1]

        s = rows[0]

        # Field-by-field, ordered so each break gets its most specific label:
        # fee first (net differs but gross agrees), then FX (cross-border gross
        # drift), then generic amount, then timing.
        fee_delta = (s["interchange"] - txn["expected_interchange"]) + \
                    (s["scheme_fee"] - txn["expected_scheme_fee"])
        gross_delta = s["gross_usd"] - txn["gross_usd"]
        settle_lag = (date.fromisoformat(s["settle_date"])
                      - date.fromisoformat(txn["txn_date"])).days

        if abs(gross_delta) <= TOL and abs(fee_delta) > TOL:
            exc("fee_discrepancy", txn, s, -fee_delta,
                f"fees charged {fee_delta:+.2f} vs published schedule")
        elif abs(gross_delta) > TOL and txn["rail"] == "cross_border":
            implied = s["gross_usd"] / txn["local_amount"]
            exc("fx_variance", txn, s, gross_delta,
                f"settled at {implied:.4f} vs booked {txn['fx_rate']:.4f}")
        elif abs(gross_delta) > TOL:
            exc("amount_mismatch", txn, s, gross_delta,
                f"gross settled {gross_delta:+.2f} vs captured")
        elif settle_lag > EXPECTED_LAG_DAYS:
            exc("timing_lag", txn, s, txn["expected_net"],
                f"settled T+{settle_lag} vs contractual T+{EXPECTED_LAG_DAYS}")
        else:
            matched += 1

    # Settlements referencing transactions we never captured.
    for ref, rows in stl_by_ref.items():
        if ref not in led_by_id:
            for s in rows:
                exc("missing_in_ledger", None, s, s["net_usd"],
                    f"bank settled {s['net_usd']:.2f} for unknown reference")

    return {"matched": matched, "exceptions": exceptions,
            "ledger_count": len(ledger), "settlement_count": len(settle)}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
SEVERITY = {   # who works it, and how loudly
    "missing_in_ledger":    ("critical", "finance + engineering"),
    "duplicate_settlement": ("high",     "bank relations"),
    "missing_at_bank":      ("high",     "settlement ops"),
    "fee_discrepancy":      ("high",     "network relations"),
    "fx_variance":          ("medium",   "treasury"),
    "amount_mismatch":      ("medium",   "merchant ops"),
    "timing_lag":           ("low",      "monitor only"),
}

AGE_BANDS = [(0, 1, "0-1d"), (2, 3, "2-3d"), (4, 7, "4-7d"), (8, 99999, "8d+")]


def analyze(res: dict) -> dict:
    exc = res["exceptions"]
    by_type: dict[str, dict] = {}
    for kind in SEVERITY:
        rows = [e for e in exc if e["type"] == kind]
        gross = sum(abs(e["exposure_usd"]) for e in rows)
        by_type[kind] = {
            "count": len(rows),
            "gross_exposure": round(gross, 2),
            "severity": SEVERITY[kind][0],
            "owner": SEVERITY[kind][1],
            "largest": max((abs(e["exposure_usd"]) for e in rows), default=0.0),
        }

    aging = {label: {"count": 0, "exposure": 0.0} for *_, label in AGE_BANDS}
    for e in exc:
        if e["type"] == "timing_lag":
            continue  # self-healing; aging the watchlist separately would be noise
        for lo, hi, label in AGE_BANDS:
            if lo <= e["age_days"] <= hi:
                aging[label]["count"] += 1
                aging[label]["exposure"] = round(
                    aging[label]["exposure"] + abs(e["exposure_usd"]), 2)
                break

    by_rail: dict[str, dict] = defaultdict(lambda: {"count": 0, "exposure": 0.0})
    for e in exc:
        r = by_rail[e["rail"]]
        r["count"] += 1
        r["exposure"] = round(r["exposure"] + abs(e["exposure_usd"]), 2)

    total_gross = sum(abs(e["exposure_usd"]) for e in exc)
    net_position = sum(e["exposure_usd"] for e in exc
                       if e["type"] != "timing_lag")

    return {
        "as_of": AS_OF.isoformat(),
        "ledger_count": res["ledger_count"],
        "settlement_count": res["settlement_count"],
        "matched": res["matched"],
        "match_rate": res["matched"] / res["ledger_count"],
        "exception_count": len(exc),
        # A reader adding "clean + exceptions" gets 50,099 against a 50,000
        # ledger, because two exception types are NOT ledger transactions:
        # missing_in_ledger (bank rows we have no txn for) and
        # duplicate_settlement (an extra settlement against an already-clean
        # txn). Split the population so the ledger actually reconciles.
        "settlement_only": sum(1 for e in exc if e["type"] in
                               ("missing_in_ledger", "duplicate_settlement")),
        "ledger_exceptions": sum(1 for e in exc if e["type"] not in
                                 ("missing_in_ledger", "duplicate_settlement")),
        "gross_exposure": round(total_gross, 2),
        "net_position": round(net_position, 2),
        "by_type": by_type,
        "aging": aging,
        "by_rail": dict(sorted(by_rail.items(),
                               key=lambda kv: -kv[1]["exposure"])),
        "top_items": sorted(exc, key=lambda e: -abs(e["exposure_usd"]))[:15],
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def usd(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def print_report(a: dict) -> None:
    w = 96
    print("=" * w)
    print(f"SETTLEMENT RECONCILIATION  |  as of {a['as_of']}  |  T+1 contractual")
    print("=" * w)
    print(f"  ledger transactions        {a['ledger_count']:>10,}")
    print(f"  settlement rows            {a['settlement_count']:>10,}")
    print(f"  matched clean              {a['matched']:>10,}   ({a['match_rate']:.2%})")
    print(f"  ledger txns with exceptions{a['ledger_exceptions']:>10,}")
    print(f"    -> ledger reconciles      {a['matched']+a['ledger_exceptions']:>10,}   "
          f"= clean + flagged")
    print(f"  settlement-only events     {a['settlement_only']:>10,}   "
          f"(bank rows with no ledger txn, and duplicate settlements)")
    print(f"  exceptions                 {a['exception_count']:>10,}")
    print(f"  gross exposure             {usd(a['gross_exposure']):>12}")
    print(f"  net position               {usd(a['net_position']):>12}   "
          f"({'bank owes us' if a['net_position'] < 0 else 'we hold excess'})")

    print(f"\nBREAKS BY TYPE")
    print("-" * w)
    print(f"  {'type':<24}{'sev':<10}{'count':>7}{'exposure':>15}{'largest':>12}   owner")
    order = sorted(a["by_type"].items(),
                   key=lambda kv: -kv[1]["gross_exposure"])
    for kind, t in order:
        print(f"  {kind:<24}{t['severity']:<10}{t['count']:>7,}"
              f"{usd(t['gross_exposure']):>15}{usd(t['largest']):>12}   {t['owner']}")

    print(f"\nAGING (excl. timing watchlist)")
    print("-" * w)
    for band, v in a["aging"].items():
        print(f"  {band:<8}{v['count']:>7,}{usd(v['exposure']):>15}")

    print(f"\nEXPOSURE BY RAIL")
    print("-" * w)
    for rail, v in a["by_rail"].items():
        print(f"  {rail:<24}{v['count']:>7,}{usd(v['exposure']):>15}")

    print(f"\nTOP OPEN ITEMS")
    print("-" * w)
    for e in a["top_items"][:10]:
        print(f"  {e['txn_id']:<12}{e['type']:<22}{usd(e['exposure_usd']):>12}"
              f"   {e['age_days']}d   {e['detail']}")
    print()


def validate(res: dict) -> None:
    """Score classifications against the seeded ground truth."""
    truth = json.loads((DATA / "seeded_breaks.json").read_text())
    ours = defaultdict(set)
    for e in res["exceptions"]:
        ours[e["type"]].add(e["txn_id"])

    mapping = {
        "B1_timing": "timing_lag", "B2_amount": "amount_mismatch",
        "B3_missing_at_bank": "missing_at_bank",
        "B4_missing_in_ledger": "missing_in_ledger",
        "B5_duplicate": "duplicate_settlement",
        "B6_fx_variance": "fx_variance", "B7_fee": "fee_discrepancy",
    }
    print("VALIDATION vs seeded ground truth")
    print("-" * 72)
    all_ok = True
    for bkey, ours_key in mapping.items():
        want = truth[bkey]["count"]
        got = len(ours[ours_key])
        ok = "ok " if want == got else "MISS"
        if want != got:
            all_ok = False
        print(f"  [{ok}] {bkey:<24} seeded {want:>5}   classified {got:>5}")
    print(f"\n  {'PASS -- every seeded break found and correctly classified' if all_ok else 'FAIL -- counts differ; investigate'}")


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------
def write_html(a: dict, path: Path) -> None:
    sev_color = {"critical": "var(--neg)", "high": "#d97706",
                 "medium": "var(--line)", "low": "var(--mut)"}

    max_exp = max(t["gross_exposure"] for t in a["by_type"].values()) or 1
    type_rows = ""
    for kind, t in sorted(a["by_type"].items(), key=lambda kv: -kv[1]["gross_exposure"]):
        pct = t["gross_exposure"] / max_exp * 100
        type_rows += f"""
    <div class="brk">
      <div class="brk-head">
        <span class="brk-name">{kind.replace('_', ' ')}</span>
        <span class="sev" style="color:{sev_color[t['severity']]}">{t['severity']}</span>
      </div>
      <div class="bar-track"><div class="bar" style="width:{pct:.1f}%"></div></div>
      <div class="brk-meta">{t['count']:,} items · ${t['gross_exposure']:,.0f} exposure · owner: {t['owner']}</div>
    </div>"""

    aging_rows = "".join(
        f"<tr><td>{band}</td><td class='n'>{v['count']:,}</td>"
        f"<td class='n'>${v['exposure']:,.2f}</td></tr>"
        for band, v in a["aging"].items())

    rail_rows = "".join(
        f"<tr><td>{r.replace('_',' ')}</td><td class='n'>{v['count']:,}</td>"
        f"<td class='n'>${v['exposure']:,.2f}</td></tr>"
        for r, v in a["by_rail"].items())

    top_rows = "".join(
        f"<tr><td class='mono'>{e['txn_id']}</td><td>{e['type'].replace('_',' ')}</td>"
        f"<td class='n'>${abs(e['exposure_usd']):,.2f}</td>"
        f"<td class='n'>{e['age_days']}d</td><td class='mut'>{e['detail']}</td></tr>"
        for e in a["top_items"])

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Settlement Reconciliation · {a['as_of']}</title>
<style>
  :root {{ color-scheme: light dark; --fg:#12151a; --mut:#5d6673; --bg:#fff;
           --line:#1f6feb; --grid:#e6e9ee; --neg:#b3261e; --pos:#0f7b3f;
           --card:#fbfcfd; --bd:#e6e9ee; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg:#e8ebf0; --mut:#98a2b3; --bg:#0d1117; --line:#58a6ff;
             --grid:#232a33; --neg:#ff7b72; --pos:#3fb950; --card:#141a22;
             --bd:#232a33; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px 20px; background:var(--bg); color:var(--fg);
          font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:980px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }}
  h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.07em;
        color:var(--mut); margin:30px 0 12px; font-weight:600; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
           gap:12px; margin-top:22px; }}
  .kpi {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
          padding:13px 15px; }}
  .kpi .k {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
             color:var(--mut); }}
  .kpi .v {{ font-size:20px; font-weight:600; margin-top:3px;
             font-variant-numeric:tabular-nums; }}
  .kpi .n2 {{ font-size:11px; color:var(--mut); margin-top:1px; }}
  .panel {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:18px 20px; }}
  .brk {{ margin-bottom:14px; }}
  .brk:last-child {{ margin-bottom:2px; }}
  .brk-head {{ display:flex; justify-content:space-between; font-size:14px;
               font-weight:600; text-transform:capitalize; }}
  .sev {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em; }}
  .bar-track {{ background:var(--grid); border-radius:4px; height:8px; margin:5px 0 4px; }}
  .bar {{ background:var(--line); height:8px; border-radius:4px; }}
  .brk-meta {{ font-size:12px; color:var(--mut); }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  @media (max-width:700px) {{ .cols {{ grid-template-columns:1fr; }} }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th,td {{ padding:7px 12px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .mono {{ font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
  .mut {{ color:var(--mut); font-size:12px; white-space:normal; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Settlement Reconciliation</h1>
  <div class="sub">As of {a['as_of']} · contractual T+1 · synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Transactions</div><div class="v">{a['ledger_count']:,}</div></div>
    <div class="kpi"><div class="k">Match rate</div><div class="v">{a['match_rate']:.2%}</div>
      <div class="n2">{a['matched']:,} clean</div></div>
    <div class="kpi"><div class="k">Exception events</div>
      <div class="v">{a['exception_count']:,}</div>
      <div class="n2">{a['ledger_exceptions']:,} ledger + {a['settlement_only']:,} settlement-only</div></div>
    <div class="kpi"><div class="k">Gross exposure</div><div class="v">${a['gross_exposure']:,.0f}</div></div>
    <div class="kpi"><div class="k">Net position</div><div class="v">${abs(a['net_position']):,.0f}</div>
      <div class="n2">{'bank owes us' if a['net_position'] < 0 else 'we hold excess'}</div></div>
  </div>

  <div class="note" style="margin-top:14px"><strong>Population
    reconciliation.</strong> {a['matched']:,} clean + {a['ledger_exceptions']:,}
    flagged = {a['matched']+a['ledger_exceptions']:,} ledger transactions. The
    remaining {a['settlement_only']:,} exception events are <em>not</em> ledger
    transactions — bank rows with no matching txn, and duplicate settlements
    against transactions that themselves matched cleanly. Adding clean +
    exception events gives {a['matched']+a['exception_count']:,}, which is why
    the two populations are reported separately.</div>

  <h2>Breaks by type — exposure-ranked</h2>
  <div class="panel">{type_rows}
  </div>

  <div class="cols">
    <div>
      <h2>Aging — open exceptions</h2>
      <div class="tbl"><table>
        <thead><tr><th>Age</th><th class="n">Items</th><th class="n">Exposure</th></tr></thead>
        <tbody>{aging_rows}</tbody>
      </table></div>
    </div>
    <div>
      <h2>Exposure by rail</h2>
      <div class="tbl"><table>
        <thead><tr><th>Rail</th><th class="n">Items</th><th class="n">Exposure</th></tr></thead>
        <tbody>{rail_rows}</tbody>
      </table></div>
    </div>
  </div>

  <h2>Top open items</h2>
  <div class="tbl"><table>
    <thead><tr><th>Txn</th><th>Type</th><th class="n">Exposure</th>
      <th class="n">Age</th><th>Detail</th></tr></thead>
    <tbody>{top_rows}</tbody>
  </table></div>

  <footer>Generated by reconcile.py · all data synthetic · classification
    validated against seeded ground truth (run with --validate)</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Two-sided settlement reconciliation")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true",
                    help="score classifications against seeded ground truth")
    args = ap.parse_args()

    ledger, settle = load()
    res = reconcile(ledger, settle)
    a = analyze(res)
    print_report(a)
    if args.validate:
        validate(res)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(a, args.html)


if __name__ == "__main__":
    main()
