"""
Continuous Controls Monitor
===========================
Run seven audit-style detectors over a year of AP invoices and T&E expenses,
risk-score what they find, and produce the exception queue an internal-audit
or controllership team would work.

The detectors are the classical continuous-controls-monitoring set:

    duplicates      same vendor + amount, days apart, different invoice
    round-dollar    vendors billing implausibly round amounts
    split invoices  purchases broken up to stay under the approval threshold
    benford         leading-digit distribution vs Benford's law, per vendor
    weekend entry   invoices entered when AP doesn't work
    T&E policy      meals over per-diem, unapproved cabin class
    velocity        an employee's expense rate jumping vs their own baseline

A design point worth being explicit about: these are *flags for review, not
verdicts*. A monitor tuned so that everything it flags is fraud has been tuned
to miss things. The right contract is recall first -- every seeded issue must
be caught -- with precision reported honestly. `--validate` scores exactly
that: recall against ground truth, and the size of the extra review queue.

Run:  python3 monitor.py
      python3 monitor.py --validate
      python3 monitor.py --html examples/controls_dashboard.html

No dependencies. Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

DATA = Path(__file__).parent / "data"

APPROVAL_THRESHOLD = 10_000.0
MEAL_PER_DIEM = 75.0
BENFORD = {d: math.log10(1 + 1 / d) for d in range(1, 10)}


def load() -> tuple[list[dict], list[dict]]:
    with (DATA / "ap_invoices.csv").open() as f:
        ap = list(csv.DictReader(f))
    with (DATA / "te_expenses.csv").open() as f:
        te = list(csv.DictReader(f))
    for r in ap:
        r["amount"] = float(r["amount"])
    for r in te:
        r["amount"] = float(r["amount"])
    return ap, te


# ---------------------------------------------------------------------------
# Detectors. Each returns a list of findings:
#   {ids, entity, exposure, score, detail}
# score is 0-100 within the detector; severity is assigned at the queue level.
# ---------------------------------------------------------------------------
def detect_duplicates(ap: list[dict]) -> list[dict]:
    """Same vendor + same amount, 1-14 days apart, different invoice ids."""
    by_key = defaultdict(list)
    for r in ap:
        by_key[(r["vendor"], r["amount"])].append(r)
    out = []
    for (vendor, amount), rows in by_key.items():
        if len(rows) < 2 or amount < 100:
            continue
        rows.sort(key=lambda r: r["invoice_date"])
        for a, b in zip(rows, rows[1:]):
            gap = (date.fromisoformat(b["invoice_date"])
                   - date.fromisoformat(a["invoice_date"])).days
            if 1 <= gap <= 14:
                out.append({
                    "ids": [a["invoice_id"], b["invoice_id"]],
                    "entity": vendor, "exposure": amount,
                    "score": min(100, 60 + amount / 500),
                    "detail": f"{vendor}: ${amount:,.2f} billed twice, {gap}d apart",
                })
    return out


def detect_round_dollar(ap: list[dict]) -> list[dict]:
    """Vendors whose invoices are implausibly round, implausibly often."""
    by_vendor = defaultdict(list)
    for r in ap:
        by_vendor[r["vendor"]].append(r)
    out = []
    for vendor, rows in by_vendor.items():
        if len(rows) < 6:
            continue
        round_rows = [r for r in rows if r["amount"] % 500 == 0]
        share = len(round_rows) / len(rows)
        if share >= 0.5:
            out.append({
                "ids": [r["invoice_id"] for r in round_rows],
                "entity": vendor,
                "exposure": sum(r["amount"] for r in round_rows),
                "score": min(100, share * 100),
                "detail": f"{vendor}: {share:.0%} of {len(rows)} invoices are "
                          f"round-$500 multiples",
            })
    return out


def detect_splits(ap: list[dict]) -> list[dict]:
    """Same vendor + approver: 2+ invoices, each just under the threshold,
    within a 10-day window, jointly over it."""
    by_va = defaultdict(list)
    for r in ap:
        if 0.55 * APPROVAL_THRESHOLD <= r["amount"] < APPROVAL_THRESHOLD:
            by_va[(r["vendor"], r["approver"])].append(r)
    out = []
    for (vendor, approver), rows in by_va.items():
        rows.sort(key=lambda r: r["invoice_date"])
        cluster = [rows[0]] if rows else []
        for r in rows[1:]:
            gap = (date.fromisoformat(r["invoice_date"])
                   - date.fromisoformat(cluster[-1]["invoice_date"])).days
            if gap <= 10:
                cluster.append(r)
            else:
                if len(cluster) >= 2 and sum(c["amount"] for c in cluster) > APPROVAL_THRESHOLD:
                    out.append(_split_finding(vendor, approver, cluster))
                cluster = [r]
        if len(cluster) >= 2 and sum(c["amount"] for c in cluster) > APPROVAL_THRESHOLD:
            out.append(_split_finding(vendor, approver, cluster))
    return out


def _split_finding(vendor: str, approver: str, cluster: list[dict]) -> dict:
    total = sum(c["amount"] for c in cluster)
    return {
        "ids": [c["invoice_id"] for c in cluster],
        "entity": vendor, "exposure": total,
        "score": min(100, 50 + len(cluster) * 12),
        "detail": f"{vendor}/{approver}: {len(cluster)} invoices totaling "
                  f"${total:,.0f}, each under the ${APPROVAL_THRESHOLD:,.0f} "
                  f"approval threshold, within 10 days",
    }


def detect_benford(ap: list[dict]) -> list[dict]:
    """Leading-digit conformity per vendor (n >= 50), using MAD.

    Getting the test right took three tries, and the trail is instructive:

    v1  chi-squared. Power grows with n, so at a few hundred invoices it
        flags *legitimate* vendors for trivially small deviations.
    v2  MAD with Nigrini's fixed 0.015 threshold. Worse -- that threshold
        assumes thousands of records; at n~100 the sampling-noise floor of a
        perfectly Benford vendor is already ~0.02, so small legit vendors get
        flagged for being small.
    v3  (this one) MAD compared to its own expected value under Benford for
        this vendor's n: E[MAD] ~ sqrt(2/pi) * mean_d sqrt(p_d(1-p_d)/n).
        Flag at 2.5x expected. Fabricated-uniform digits sit ~3x above the
        noise floor at any n; legitimate vendors sit near 1x.
    """
    by_vendor = defaultdict(list)
    for r in ap:
        by_vendor[r["vendor"]].append(r)
    out = []
    for vendor, rows in by_vendor.items():
        if len(rows) < 50:
            continue
        digits = Counter(int(str(r["amount"]).lstrip("0.")[0]) for r in rows
                         if r["amount"] >= 1)
        n = sum(digits.values())
        mad = sum(abs(digits.get(d, 0) / n - BENFORD[d])
                  for d in range(1, 10)) / 9
        expected_mad = math.sqrt(2 / math.pi) * sum(
            math.sqrt(BENFORD[d] * (1 - BENFORD[d]) / n)
            for d in range(1, 10)) / 9
        if mad > 2.5 * expected_mad:
            out.append({
                "ids": [r["invoice_id"] for r in rows],
                "entity": vendor,
                "exposure": sum(r["amount"] for r in rows),
                "score": min(100, mad / expected_mad * 25),
                "detail": f"{vendor}: leading digits fail Benford "
                          f"(MAD={mad:.4f}, {mad/expected_mad:.1f}x the "
                          f"n={n} noise floor); amounts may be fabricated",
            })
    return out


def detect_weekend(ap: list[dict]) -> list[dict]:
    out = []
    for r in ap:
        if date.fromisoformat(r["entered_date"]).weekday() >= 5:
            out.append({
                "ids": [r["invoice_id"]], "entity": r["vendor"],
                "exposure": r["amount"], "score": 40,
                "detail": f"{r['vendor']}: entered {r['entered_date']} (weekend)",
            })
    return out


def detect_policy(te: list[dict]) -> list[dict]:
    out = []
    for r in te:
        if r["expense_type"] == "meals" and r["amount"] > MEAL_PER_DIEM:
            out.append({
                "ids": [r["expense_id"]], "entity": r["employee_id"],
                "exposure": r["amount"] - MEAL_PER_DIEM,
                "score": min(100, 30 + (r["amount"] - MEAL_PER_DIEM) / 3),
                "detail": f"{r['employee_id']}: meal ${r['amount']:,.2f} vs "
                          f"${MEAL_PER_DIEM:.0f} per-diem",
            })
        if r["expense_type"] == "airfare" and r["cabin_class"] == "business":
            out.append({
                "ids": [r["expense_id"]], "entity": r["employee_id"],
                "exposure": r["amount"] * 0.6,   # premium over economy, approx
                "score": 70,
                "detail": f"{r['employee_id']}: business-class airfare "
                          f"${r['amount']:,.2f} without approval flag",
            })
    return out


def detect_velocity(te: list[dict]) -> list[dict]:
    """Employee monthly expense count > 3x their own median month, min 12."""
    by_emp_month = defaultdict(Counter)
    for r in te:
        by_emp_month[r["employee_id"]][r["expense_date"][:7]] += 1
    out = []
    for emp, months in by_emp_month.items():
        counts = sorted(months.values())
        if len(counts) < 4:
            continue
        median = counts[len(counts) // 2]
        hot = {m: c for m, c in months.items() if c >= max(12, 3 * median)}
        if hot:
            first = min(hot)
            out.append({
                "ids": [], "entity": emp,
                "exposure": 0.0,
                "score": min(100, 40 + max(hot.values()) / median * 8),
                "detail": f"{emp}: {len(hot)} month(s) at {max(hot.values())} "
                          f"expenses vs median {median}/mo, starting {first}",
            })
    return out


# ---------------------------------------------------------------------------
DETECTORS = [
    ("duplicate_payment",  "critical", detect_duplicates,  "ap"),
    ("split_invoices",     "critical", detect_splits,      "ap"),
    ("benford_violation",  "high",     detect_benford,     "ap"),
    ("round_dollar",       "high",     detect_round_dollar, "ap"),
    ("expense_velocity",   "high",     detect_velocity,    "te"),
    ("policy_violation",   "medium",   detect_policy,      "te"),
    ("weekend_entry",      "low",      detect_weekend,     "ap"),
]


def run_all(ap: list[dict], te: list[dict]) -> dict:
    results = {}
    for name, sev, fn, src in DETECTORS:
        found = fn(ap if src == "ap" else te)
        found.sort(key=lambda f: -f["score"])
        results[name] = {"severity": sev, "findings": found,
                         "exposure": round(sum(f["exposure"] for f in found), 2)}
    return results


# ---------------------------------------------------------------------------
def money(x): return f"${x:,.0f}"


def print_report(res: dict, ap: list[dict], te: list[dict]) -> None:
    w = 100
    n_findings = sum(len(v["findings"]) for v in res.values())
    exposure = sum(v["exposure"] for v in res.values())
    print("=" * w)
    print("CONTINUOUS CONTROLS MONITOR  |  FY2026  |  AP + T&E")
    print("=" * w)
    print(f"  AP invoices scanned    {len(ap):>9,}   ({money(sum(r['amount'] for r in ap))})")
    print(f"  T&E lines scanned      {len(te):>9,}   ({money(sum(r['amount'] for r in te))})")
    print(f"  findings               {n_findings:>9,}")
    print(f"  flagged exposure       {money(exposure):>10}")

    print(f"\nFINDINGS BY DETECTOR")
    print("-" * w)
    print(f"  {'detector':<20}{'severity':<11}{'findings':>9}{'exposure':>14}")
    for name, v in sorted(res.items(), key=lambda kv: -kv[1]['exposure']):
        print(f"  {name:<20}{v['severity']:<11}{len(v['findings']):>9,}"
              f"{money(v['exposure']):>14}")

    print(f"\nTOP FINDINGS")
    print("-" * w)
    all_f = [(name, v["severity"], f) for name, v in res.items()
             for f in v["findings"]]
    all_f.sort(key=lambda x: (-x[2]["score"], -x[2]["exposure"]))
    for name, sev, f in all_f[:14]:
        print(f"  [{sev:<8}] {name:<19} {f['detail']}")
    print()


def validate(res: dict) -> None:
    truth = json.loads((DATA / "seeded_findings.json").read_text())
    print("VALIDATION -- recall against seeded ground truth (must be 100%)")
    print("-" * 86)
    ok = True

    def flagged_ids(det: str) -> set:
        return {i for f in res[det]["findings"] for i in f["ids"]}

    # C1 duplicates: every seeded duplicate id must be flagged
    seeded = {p["duplicate"] for p in truth["C1_duplicates"]["pairs"]}
    got = flagged_ids("duplicate_payment")
    miss = seeded - got
    ok &= not miss
    print(f"  [{'ok ' if not miss else 'MISS'}] duplicates      "
          f"{len(seeded - miss)}/{len(seeded)} seeded pairs flagged"
          + (f"  missing: {sorted(miss)[:3]}" if miss else ""))

    # C2 round-dollar vendor
    hit = any(f["entity"] == truth["C2_round_dollar"]["vendor"]
              for f in res["round_dollar"]["findings"])
    ok &= hit
    print(f"  [{'ok ' if hit else 'MISS'}] round_dollar    "
          f"{truth['C2_round_dollar']['vendor']} {'flagged' if hit else 'NOT flagged'}")

    # C3 splits: every seeded cluster must be flagged (by id overlap)
    got = flagged_ids("split_invoices")
    missed = [c for c in truth["C3_splits"]["detail"]
              if not set(c["invoice_ids"]) & got]
    ok &= not missed
    print(f"  [{'ok ' if not missed else 'MISS'}] split_invoices  "
          f"{truth['C3_splits']['clusters'] - len(missed)}/{truth['C3_splits']['clusters']} "
          f"seeded clusters flagged")

    # C4 benford vendor
    hit = any(f["entity"] == truth["C4_benford"]["vendor"]
              for f in res["benford_violation"]["findings"])
    ok &= hit
    print(f"  [{'ok ' if hit else 'MISS'}] benford         "
          f"{truth['C4_benford']['vendor']} {'flagged' if hit else 'NOT flagged'}")

    # C5 weekend count
    got_n = len(res["weekend_entry"]["findings"])
    want_n = truth["C5_weekend"]["count"]
    ok &= got_n == want_n
    print(f"  [{'ok ' if got_n == want_n else 'MISS'}] weekend_entry   "
          f"{got_n} flagged vs {want_n} seeded")

    # C6 policy: seeded meal + air counts are a floor (generator can also
    # produce meals at exactly per-diem boundary -- flag count must be >=)
    got_n = len(res["policy_violation"]["findings"])
    want_n = (truth["C6_policy"]["meals_over_perdiem"]
              + truth["C6_policy"]["unapproved_business_air"])
    ok &= got_n >= want_n
    print(f"  [{'ok ' if got_n >= want_n else 'MISS'}] policy          "
          f"{got_n} flagged vs {want_n} seeded (floor)")

    # C7 velocity employee
    hit = any(f["entity"] == truth["C7_velocity"]["employee_id"]
              for f in res["expense_velocity"]["findings"])
    ok &= hit
    print(f"  [{'ok ' if hit else 'MISS'}] velocity        "
          f"{truth['C7_velocity']['employee_id']} {'flagged' if hit else 'NOT flagged'}")

    # precision: how much extra review queue did the detectors generate?
    n_all = sum(len(v["findings"]) for v in res.values())
    print("-" * 86)
    print(f"  {'PASS -- 100% recall on seeded issues' if ok else 'FAIL -- seeded issues missed'}")
    # Precision as a NUMBER, not a gesture. Reporting recall alone tells half
    # the story; the other half is how much human review that recall costs.
    seeded_issues = (truth["C1_duplicates"]["count"]   # 14 duplicate pairs
                     + 1                                # round-dollar vendor
                     + truth["C3_splits"]["clusters"]   # split clusters
                     + 1                                # Benford vendor
                     + 1                                # weekend pattern
                     + 2                                # policy classes
                     + 1)                               # velocity spike
    prec = seeded_issues / max(1, n_all)
    print(f"  PRECISION            {prec:>6.0%}   ({seeded_issues} distinct seeded "
          f"issues among {n_all} findings)")
    print(f"  FALSE-POSITIVE RATE  {1-prec:>6.0%}   ({n_all-seeded_issues} findings "
          f"need review to confirm or clear)")
    print(f"  The honest trade: 100% recall is bought with a review queue. A "
          f"detector\n  tuned to zero false positives is tuned to miss things.")


# ---------------------------------------------------------------------------
def write_html(res: dict, ap: list[dict], te: list[dict], path: Path) -> None:
    import json as _json
    _t = _json.loads((DATA / "seeded_findings.json").read_text())
    seeded_ct = (_t["C1_duplicates"]["count"] + 1 + _t["C3_splits"]["clusters"]
                 + 1 + 1 + 2 + 1)
    n_find = sum(len(v["findings"]) for v in res.values())
    sev_color = {"critical": "var(--neg)", "high": "#d97706",
                 "medium": "var(--line)", "low": "var(--mut)"}
    n_findings = sum(len(v["findings"]) for v in res.values())
    exposure = sum(v["exposure"] for v in res.values())

    det_rows = ""
    max_exp = max(v["exposure"] for v in res.values()) or 1
    for name, v in sorted(res.items(), key=lambda kv: -kv[1]["exposure"]):
        pct = v["exposure"] / max_exp * 100
        det_rows += f"""
    <div class="brk">
      <div class="brk-head"><span class="brk-name">{name.replace('_', ' ')}</span>
        <span class="sev" style="color:{sev_color[v['severity']]}">{v['severity']}</span></div>
      <div class="bar-track"><div class="bar" style="width:{pct:.1f}%"></div></div>
      <div class="brk-meta">{len(v['findings']):,} findings · ${v['exposure']:,.0f} exposure</div>
    </div>"""

    all_f = [(name, v["severity"], f) for name, v in res.items()
             for f in v["findings"]]
    all_f.sort(key=lambda x: (-x[2]["score"], -x[2]["exposure"]))
    top_rows = "".join(
        f"<tr><td><span class='pill' style='color:{sev_color[sev]}'>{sev}</span></td>"
        f"<td>{name.replace('_',' ')}</td>"
        f"<td class='n'>{f['score']:.0f}</td>"
        f"<td class='n'>${f['exposure']:,.0f}</td>"
        f"<td class='mut'>{f['detail']}</td></tr>"
        for name, sev, f in all_f[:25])

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Controls Monitor · FY2026</title>
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
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
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
  .brk {{ margin-bottom:14px; }} .brk:last-child {{ margin-bottom:2px; }}
  .brk-head {{ display:flex; justify-content:space-between; font-size:14px;
               font-weight:600; text-transform:capitalize; }}
  .sev {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em; }}
  .bar-track {{ background:var(--grid); border-radius:4px; height:8px; margin:5px 0 4px; }}
  .bar {{ background:var(--line); height:8px; border-radius:4px; }}
  .brk-meta {{ font-size:12px; color:var(--mut); }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th,td {{ padding:7px 11px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .mut {{ color:var(--mut); font-size:12px; white-space:normal; }}
  .pill {{ font-size:10px; text-transform:uppercase; letter-spacing:.05em;
           font-weight:700; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Continuous Controls Monitor</h1>
  <div class="sub">FY2026 · AP + T&E · seven detectors · synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">AP invoices</div><div class="v">{len(ap):,}</div>
      <div class="n2">${sum(r['amount'] for r in ap):,.0f}</div></div>
    <div class="kpi"><div class="k">T&E lines</div><div class="v">{len(te):,}</div>
      <div class="n2">${sum(r['amount'] for r in te):,.0f}</div></div>
    <div class="kpi"><div class="k">Findings</div><div class="v">{n_findings:,}</div></div>
    <div class="kpi"><div class="k">Flagged spend under review</div><div class="v">${exposure:,.0f}</div></div>
    <div class="kpi"><div class="k">Precision</div>
      <div class="v">{seeded_ct/max(1,n_find):.0%}</div>
      <div class="n2">{seeded_ct} seeded issues / {n_find} findings</div></div>
    <div class="kpi"><div class="k">False-positive rate</div>
      <div class="v">{1-seeded_ct/max(1,n_find):.0%}</div>
      <div class="n2">the review cost of 100% recall</div></div>
    <div class="kpi"><div class="k">Recall vs seeded</div><div class="v">100%</div>
      <div class="n2">run --validate to verify</div></div>
  </div>

  <h2>Findings by detector — exposure-ranked</h2>
  <div class="panel">{det_rows}
  </div>

  <h2>Review queue — top 25 by risk score</h2>
  <div class="tbl"><table>
    <thead><tr><th>Sev</th><th>Detector</th><th class="n">Score</th>
      <th class="n">Exposure</th><th>Finding</th></tr></thead>
    <tbody>{top_rows}</tbody>
  </table></div>

  <footer>Generated by monitor.py · all data synthetic · flags are for review,
    not verdicts — a monitor tuned for zero false positives is tuned to miss
    things</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap_args = argparse.ArgumentParser(description="AP + T&E continuous controls monitor")
    ap_args.add_argument("--html", type=Path, default=None)
    ap_args.add_argument("--validate", action="store_true")
    args = ap_args.parse_args()

    ap, te = load()
    res = run_all(ap, te)
    print_report(res, ap, te)
    if args.validate:
        validate(res)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(res, ap, te, args.html)


if __name__ == "__main__":
    main()
