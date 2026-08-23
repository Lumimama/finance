"""
Board One-Pager -- the full metric set, defined
===============================================
Every number a SaaS board asks for, in the five sections a board deck
actually uses, each metric carrying its definition ON the page:

    GROWTH        ARR, net new ARR, YoY, bookings, billings, pipeline coverage
    CUSTOMERS     NRR, GRR, logo churn, count, ACV, ARPA
    EFFICIENCY    burn multiple, Rule of 40, magic number, CAC payback,
                  LTV:CAC, ARR per FTE
    FINANCIAL     cash, runway, gross margin, EBITDA margin, FCF
    AI-SPECIFIC   AI cost as % of revenue, GM after AI costs, cost per
                  inference, cost per 1K tokens

Definitions are printed next to the numbers, deliberately. Half these
metrics have multiple defensible definitions (NRR, magic number, CAC
payback are the notorious ones), and a scorecard that doesn't say which
one it uses will quietly disagree with someone else's deck within two
quarters. The definition column is the deliverable as much as the values.

Everything computes from one monthly operating series -- the same figure is
never entered twice -- and --validate recomputes the identities (ARR walk,
EBITDA build, COGS build, cash roll-forward) from raw components.

The series comes from one of two places:

    --input data/monthly_metrics.csv    the live source: a Google Sheet the
                                        preparer updates once a month and the
                                        workflow exports as CSV
    --demo                              the seeded generator in demo_data.py,
                                        so a reviewer can run this with no
                                        credentials and no network

Validation gates publication. If any check fails the program exits non-zero
and does NOT write the HTML, so a broken refresh leaves the last good
dashboard in place rather than replacing it with a confident wrong number.

Run:  python3 board.py --demo --validate
      python3 board.py --input data/monthly_metrics.csv --context data/board_context.txt \
              --validate --html examples/board_dashboard.html

No dependencies. Python 3.10+. All data synthetic.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import input_loader
from input_loader import InputError

GM_TARGET = 0.77


# ---------------------------------------------------------------------------
def compute(rows):
    """The scorecard: value + definition for every metric."""
    ltm = rows[-12:]
    last = rows[-1]
    q = rows[-3:]
    prior_q = rows[-6:-3]

    rev_ltm = sum(r["revenue"] for r in ltm)
    cogs_ltm = sum(r["cogs"] for r in ltm)
    gm = 1 - cogs_ltm / rev_ltm
    ai_ltm = sum(r["ai_cost"] for r in ltm)
    fcf_ltm = sum(r["fcf"] for r in ltm)
    burn_ltm = -fcf_ltm
    net_new_ltm = last["arr"] - ltm[0]["beg_arr"]
    yoy = last["arr"] / ltm[0]["beg_arr"] - 1

    nrr = grr = logo = 1.0
    for r in ltm:
        nrr *= 1 + (r["expansion"] - r["contraction"] - r["churn_arr"]) / r["beg_arr"]
        grr *= 1 - (r["contraction"] + r["churn_arr"]) / r["beg_arr"]
        logo *= 1 - r["churn_cust"] / r["beg_cust"]

    new_arr_q = sum(r["new_arr"] for r in q)
    sm_q = sum(r["sm"] for r in q)
    cac_payback = sm_q / (new_arr_q * gm / 12)
    magic = (q[-1]["arr"] - q[0]["beg_arr"]) / sum(r["sm"] for r in prior_q)
    # LTV empirical-ish: ARPA x GM / annual churn rate (stated as formulaic!)
    arpa = last["arr"] / last["customers"]
    annual_logo_churn = 1 - logo
    ltv = arpa * gm / max(annual_logo_churn, 1e-9)
    cac_per_logo = sm_q / max(1, sum(r["new_cust"] for r in q)) * 4 / 4
    t3_burn = -sum(r["fcf"] for r in q) / 3
    runway = last["cash"] / t3_burn if t3_burn > 0 else float("inf")
    rule40 = (yoy + fcf_ltm / rev_ltm) * 100

    def M(x): return f"${x/1e6:,.1f}M"
    def K(x): return f"${x/1e3:,.0f}K"
    def pc(x): return f"{x:.1%}"

    S = {}
    S["Growth"] = [
        ("ARR", M(last["arr"]), "Annualized run-rate of contracted recurring revenue at month end. Excludes one-time services.", None),
        ("Net new ARR (LTM)", M(net_new_ltm), "Ending ARR minus ARR twelve months prior: new + expansion − contraction − churn.", None),
        ("ARR growth YoY", pc(yoy), "Ending ARR over ARR one year ago, minus one.", "≥40% strong at this scale"),
        ("Bookings (Q)", M(sum(r["bookings"] for r in q)), "Total contract value signed this quarter (TCV). Leading indicator; not revenue.", None),
        ("Billings (Q)", M(sum(r["billings"] for r in q)), "Amounts invoiced: revenue + change in deferred revenue. The cash-collection precursor.", None),
        ("Pipeline coverage (next Q)", f"{last['pipeline']/(new_arr_q*1.05):.1f}x", "Open pipeline over next quarter's new-ARR target.", "≥3.0x planning floor"),
    ]
    S["Customer Health"] = [
        ("NRR (LTM)", pc(nrr), "Chain-linked monthly: (expansion − contraction − churn) ÷ beginning ARR, installed base only — new logos excluded.", "≥110% strong"),
        ("GRR (LTM)", pc(grr), "Same base, but expansion cannot offset losses. Ceiling 100%.", "≥90% strong"),
        ("Logo churn (LTM)", pc(annual_logo_churn), "Chain-linked customer-count churn, annualized.", "<10% strong"),
        ("Customers", f"{last['customers']:,}", "Active paying customers at month end.", None),
        ("ARPA", K(arpa), "Average revenue per account: ending ARR ÷ customer count.", None),
        ("Avg ACV (new, Q)", K(new_arr_q / max(1, sum(r['new_cust'] for r in q))), "New ARR this quarter ÷ new logos: the annual value of a newly signed contract.", None),
    ]
    S["Efficiency"] = [
        ("Burn multiple (LTM)", f"{burn_ltm/net_new_ltm:.2f}", "Net burn ÷ net new ARR: dollars burned per dollar of new recurring revenue.", "<1.5 good, <1.0 strong"),
        ("Rule of 40", f"{rule40:.0f} pts", "YoY ARR growth % + FCF margin %.", "≥40 strong"),
        ("Magic number (Q)", f"{magic:.2f}", "Net new ARR this quarter ÷ prior quarter's S&M. ARR is already annual — not annualized again.", "≥0.75 lean in"),
        ("CAC payback", f"{cac_payback:.1f} mo", "All S&M ÷ (new ARR × GM ÷ 12): months of gross profit to repay acquisition. Conservative: charges all S&M to new logos.", "<18mo acceptable"),
        ("LTV : CAC", f"{ltv/cac_per_logo:.1f}x", "Formulaic (ARPA × GM ÷ churn) ÷ CAC per logo. Stated as formulaic; treat with the suspicion it deserves — see revenue-cohorts for the empirical version.", ">3x conventional"),
        ("ARR per FTE", K(last["arr"]/last["headcount"]), "Ending ARR ÷ headcount.", "≥$200K strong"),
    ]
    S["Financial Performance"] = [
        ("Cash", M(last["cash"]), "Month-end cash and equivalents.", None),
        ("Runway", f"{runway:,.1f} mo", "Cash ÷ trailing 3-month average net burn.", "≥18mo comfortable"),
        ("Gross margin (LTM)", pc(gm), "(Revenue − COGS) ÷ revenue. COGS includes AI inference, infra, support.", "≥75% strong for AI-native"),
        ("EBITDA margin (LTM)", pc(sum(r["ebitda"] for r in ltm)/rev_ltm), "Revenue − COGS − opex, ÷ revenue. Before capex, SBC treated as cash here.", None),
        ("FCF (LTM)", M(fcf_ltm), "EBITDA − capex. Negative = burning.", None),
        ("Net burn (t3, monthly)", M(t3_burn), "Trailing 3-month average of −FCF. The quotable burn number.", None),
    ]
    S["AI-Specific"] = [
        ("AI cost, % of revenue (LTM)", pc(ai_ltm/rev_ltm), "Inference + model API spend ÷ revenue. The line that decides whether usage growth is good news.", "watch the trend, not the level"),
        ("GM after AI costs", pc(gm), "Gross margin with AI inference fully loaded in COGS — not adjusted out.", "the honest GM"),
        ("Cost per inference", f"${sum(r['ai_cost'] for r in q)/sum(r['inference_calls'] for r in q):.4f}", "Total AI cost ÷ inference calls, trailing quarter.", "must fall as volume grows"),
        ("Cost per 1K tokens", f"${sum(r['ai_cost'] for r in q)/sum(r['tokens'] for r in q)*1000:.4f}", "Total AI cost ÷ tokens processed, trailing quarter.", None),
        ("Tokens processed (mo)", f"{last['tokens']/1e9:,.1f}B", "Total tokens through the platform this month.", None),
        ("AI cost trend (12mo)", pc(sum(r['ai_cost'] for r in ltm[-3:])/sum(r['revenue'] for r in ltm[-3:]) - sum(r['ai_cost'] for r in ltm[:3])/sum(r['revenue'] for r in ltm[:3])), "Change in AI cost as % of revenue, first vs last quarter of the LTM window. Negative = margin expanding.", "negative is the story"),
    ]
    return S, rows


# ---------------------------------------------------------------------------
def print_report(S, rows) -> None:
    w = 110
    print("=" * w)
    print(f"BOARD ONE-PAGER  |  {rows[-1]['month']}  |  every metric with its definition")
    print("=" * w)
    for section, metrics in S.items():
        print(f"\n{section.upper()}")
        print("-" * w)
        for name, val, defn, bench in metrics:
            b = f"   [{bench}]" if bench else ""
            print(f"  {name:<28}{val:>14}{b}")
            print(f"  {'':<28}{defn[:78]}")
    print()


def validate(rows, ctx=None) -> bool:
    """Recompute every identity from raw components. Returns True on PASS.

    TOL is a dollar tolerance, not a percentage: these are accounting
    identities and they either foot or they do not. It is $0.01 rather than
    $0 only because the inputs arrive as CSV text rounded to cents.
    """
    # $0.05, not $0: the Sheet holds dollars-and-cents and its CSV export
    # rounds, so a six-term identity can legitimately miss by a few cents.
    # Any real error -- a mistyped figure, an overtyped formula, a column in
    # thousands -- is off by dollars or more and still fails loudly.
    TOL = 0.05
    print("VALIDATION -- identities recomputed from raw components")
    print("-" * 90)
    ok = True
    fails: list[str] = []

    def check(passed: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        ok &= passed
        if not passed:
            fails.append(label)
        print(f"  [{'ok ' if passed else 'MISS'}] {label}{detail}")

    worst = max(abs(r["beg_arr"] + r["new_arr"] + r["expansion"]
                    - r["contraction"] - r["churn_arr"] - r["arr"]) for r in rows)
    chain = all(abs(rows[i]["arr"] - rows[i+1]["beg_arr"]) < TOL
                for i in range(len(rows)-1))
    bad_chain = [rows[i+1]["month"] for i in range(len(rows)-1)
                 if abs(rows[i]["arr"] - rows[i+1]["beg_arr"]) >= TOL]
    check(worst < TOL and chain, "ARR walk ties and chains",
          f" (max diff ${worst:.4f}"
          + (f"; beginning ARR breaks at {', '.join(bad_chain)}" if bad_chain else "")
          + ")")

    worst2 = max(abs(r["revenue"] - r["cogs"] - r["sm"] - r["rd"] - r["ga"]
                     - r["ebitda"]) for r in rows)
    check(worst2 < TOL, "EBITDA = revenue − COGS − opex, every month",
          f" (max diff ${worst2:.4f})")

    # COGS is checked against its own reported components, not against assumed
    # percentages of revenue -- the earlier version hardcoded 7.5%/5.5% and so
    # could only ever validate the demo generator, never a real input file.
    worst3 = max(abs(r["cogs"] - r["ai_cost"] - r["infra_cost"] - r["support_cost"])
                 for r in rows)
    check(worst3 < TOL, "COGS = AI cost + infra + support",
          f" (max diff ${worst3:.4f})")

    # Checked month-over-month against the REPORTED prior cash rather than by
    # accumulating a running balance from month one. Accumulating compounds the
    # cent-rounding of every prior row into the last one, which made an
    # 18-month sheet fail on rounding alone while hiding which month broke.
    worst4, bad_cash = 0.0, []
    for prev, r in zip(rows, rows[1:]):
        diff = abs(prev["cash"] + r["fcf"] - r["cash"])
        if diff >= TOL:
            bad_cash.append(r["month"])
        worst4 = max(worst4, diff)
    check(worst4 < TOL, "cash rolls forward on FCF",
          f" (max diff ${worst4:.4f}"
          + (f"; breaks at {', '.join(bad_cash[:3])}" if bad_cash else "") + ")")

    fcf_worst = max(abs(r["ebitda"] - r["capex"] - r["fcf"]) for r in rows)
    check(fcf_worst < TOL, "FCF = EBITDA − capex", f" (max diff ${fcf_worst:.4f})")

    cust_worst = max(abs(r["beg_cust"] + r["new_cust"] - r["churn_cust"] - r["customers"])
                     for r in rows)
    check(cust_worst < TOL, "customer count walks", f" (max diff {cust_worst:.2f})")

    S, _ = compute(rows)
    n_missing = sum(1 for sec in S.values() for (_, _, d, _) in sec if len(d) < 20)
    total = sum(len(sec) for sec in S.values())
    check(n_missing == 0,
          f"all {total} metrics carry a substantive definition",
          f" ({n_missing} missing)")

    if ctx is not None and ctx.get("_present"):
        missing_h = [h for h in input_loader.DOC_HEADINGS if not ctx.get(h)]
        check(not missing_h, "board context doc has all five sections",
              f" ({', '.join(missing_h)} missing)" if missing_h else "")

    print("-" * 90)
    print(f"  {'PASS' if ok else 'FAIL'}")
    if not ok:
        print(f"  failed: {'; '.join(fails)}")
    return ok


# ---------------------------------------------------------------------------
def write_html(S, rows, path: Path, meta: dict | None = None,
               ctx: dict | None = None) -> None:
    last = rows[-1]
    meta = meta or {}
    ctx = ctx or {}
    # small ARR sparkline
    W, H, PL, PT, PB = 880, 200, 84, 18, 34
    pw, ph = W - PL - 24, H - PT - PB
    lo = min(r["arr"] for r in rows) * 0.95
    hi = max(r["arr"] for r in rows) * 1.03
    def x(i): return PL + pw * i / (len(rows) - 1)
    def y(v): return PT + ph * (1 - (v - lo) / (hi - lo))
    arr_line = " ".join(f"{x(i):.1f},{y(r['arr']):.1f}" for i, r in enumerate(rows))
    grid = "".join(
        f'<line x1="{PL}" y1="{y(lo+(hi-lo)*f):.1f}" x2="{W-24}" y2="{y(lo+(hi-lo)*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{y(lo+(hi-lo)*f)+4:.1f}" text-anchor="end" class="tick">${(lo+(hi-lo)*f)/1e6:.0f}M</text>'
        for f in (0, .5, 1.0))
    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{H-12}" text-anchor="middle" class="tick">{rows[i]["month"][2:]}</text>'
        for i in range(0, len(rows), 3))

    # Status strip -- every field comes from the run that produced this file.
    # Nothing here is hardcoded: if the refresh failed, this HTML is not
    # rewritten at all, so a stale page keeps its own older timestamp rather
    # than claiming to be current.
    def esc(s: str) -> str:
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    chips = [
        ("Reporting period", meta.get("reporting_period", last["month"])),
        ("Source", meta.get("source_label", "seeded demo data")),
        ("Rows", f"{len(rows)} months"),
        ("Validation", meta.get("validation", "not run")),
        ("Last refresh (UTC)", meta.get("refreshed_utc", "--")),
    ]
    if meta.get("source_hash"):
        chips.append(("Source hash", meta["source_hash"]))
    strip = "".join(
        f'<div class="chip"><span class="k">{esc(k)}</span>'
        f'<span class="v {"good" if k == "Validation" and v == "PASS" else ""}">'
        f'{esc(v)}</span></div>' for k, v in chips)
    status_html = f'<div class="strip">{strip}</div>'

    commentary = (ctx.get("Management Commentary") or "").strip()
    commentary_html = ""
    if commentary:
        # Split on BLANK lines, not every newline: the Doc's text export hard-wraps
        # long sentences, and splitting per line cut paragraphs mid-clause.
        blocks = [" ".join(b.split()) for b in commentary.split("\n\n")]
        paras = "".join(f"<p>{esc(b)}</p>" for b in blocks if b)
        commentary_html = f"""
  <div class="commentary">
    <div class="clabel">Management commentary — supplied by the preparer, not a
      calculated figure</div>
    {paras}
  </div>"""

    disclosure = (ctx.get("Dashboard Disclosure") or
                  "All data synthetic; a demonstration dashboard.").strip()

    sections_html = ""
    for section, metrics in S.items():
        rows_h = "".join(
            f"<tr><td class='mname'>{name}</td><td class='n mval'>{val}</td>"
            f"<td class='mdef'>{defn}{f'<span class=bench> · {bench}</span>' if bench else ''}</td></tr>"
            for name, val, defn, bench in metrics)
        sections_html += f"""
  <h2>{section}</h2>
  <div class="tbl"><table>
    <thead><tr><th>Metric</th><th class="n">Value</th><th>Definition — the one this company uses</th></tr></thead>
    <tbody>{rows_h}</tbody></table></div>"""

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Board One-Pager · {last['month']}</title>
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
        color:var(--mut); margin:26px 0 10px; font-weight:600; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; margin-top:20px; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th,td {{ padding:7px 11px; text-align:left; border-bottom:1px solid var(--bd);
           vertical-align:top; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
        color:var(--mut); font-weight:600; white-space:nowrap; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .mname {{ font-weight:600; white-space:nowrap; }}
  .mval {{ font-weight:600; white-space:nowrap; font-size:14px; }}
  .mdef {{ color:var(--mut); font-size:12.5px; }}
  .bench {{ color:var(--pos); font-weight:600; }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  .strip {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }}
  .chip {{ background:var(--card); border:1px solid var(--bd); border-radius:8px;
           padding:6px 10px; font-size:12px; line-height:1.35; }}
  .chip .k {{ display:block; color:var(--mut); font-size:10.5px;
              text-transform:uppercase; letter-spacing:.05em; }}
  .chip .v {{ font-weight:600; font-variant-numeric:tabular-nums; }}
  .chip .v.good {{ color:var(--pos); }}
  .commentary {{ background:var(--card); border:1px solid var(--bd);
                 border-left:3px solid var(--line); border-radius:8px;
                 padding:12px 14px; margin-top:20px; font-size:13px; }}
  .commentary p {{ margin:6px 0 0; }}
  .clabel {{ color:var(--mut); font-size:10.5px; text-transform:uppercase;
             letter-spacing:.05em; font-weight:600; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Board One-Pager</h1>
  <div class="sub">{last['month']} · thirty metrics in five sections, every one
    with its definition on the page · synthetic data</div>

  {status_html}
  {commentary_html}

  <div class="chart"><svg viewBox="0 0 {W} {H}" role="img" aria-label="ARR trend">
    {grid}<polyline points="{arr_line}" fill="none" stroke="var(--line)"
    stroke-width="2.5"/>{ticks}</svg></div>
  {sections_html}

  <div class="note">Why the definition column exists: NRR, magic number, and
    CAC payback each have several defensible definitions, and a scorecard that
    doesn't state which one it uses will quietly disagree with someone else's
    deck within two quarters. LTV here is flagged as formulaic on the page
    itself — the empirical version lives in the revenue-cohorts project.</div>

  <footer>Generated by board.py · every identity recomputed from raw
    components (run --validate) · {esc(disclosure)}</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=Path(__file__).parent, capture_output=True,
                             text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Board one-pager with definitions")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--input", type=Path, default=None,
                     help="normalized monthly CSV exported from the Google Sheet")
    src.add_argument("--demo", action="store_true",
                     help="seeded demo series; no network, no credentials")
    ap.add_argument("--context", type=Path, default=None,
                    help="text export of the board context Google Doc")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--manifest", type=Path, default=None,
                    help="write a JSON provenance manifest on a passing run")
    ap.add_argument("--export-csv", type=Path, default=None,
                    help="write the loaded series back out (seeds the Sheet)")
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    if not args.input and not args.demo:
        ap.error("choose a source: --input <csv> (live) or --demo (seeded)")

    # ---- load -------------------------------------------------------------
    try:
        if args.demo:
            import demo_data
            rows = demo_data.make_series()
            source_label, source_hash = "seeded demo data (demo_data.py)", ""
        else:
            rows = input_loader.load_csv(args.input)
            source_label = f"Google Sheet export ({args.input.name})"
            source_hash = input_loader.sha256_of(args.input)
        ctx = input_loader.load_context(args.context)
    except InputError as e:
        print(f"INPUT ERROR: {e}", file=sys.stderr)
        print("Refusing to publish. The previous dashboard is unchanged.",
              file=sys.stderr)
        return 2

    if args.export_csv:
        input_loader.write_csv(rows, args.export_csv)
        print(f"Wrote {args.export_csv}")

    S, rows = compute(rows)
    print_report(S, rows)

    # ---- validate ---------------------------------------------------------
    passed = True
    if args.validate:
        passed = validate(rows, ctx)
        if not passed:
            print("\nValidation FAILED -- refusing to write the dashboard. "
                  "The previous version is left in place.", file=sys.stderr)
            return 1

    # ---- publish ----------------------------------------------------------
    meta = {
        "reporting_period": (ctx.get("Reporting Period") or rows[-1]["month"]).strip()
                            or rows[-1]["month"],
        "source_label": source_label,
        "source_hash": source_hash,
        "validation": "PASS" if args.validate else "not run",
        "refreshed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "rows": len(rows),
        "script_sha": _git_sha(),
    }
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(S, rows, args.html, meta, ctx)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(meta, indent=2) + "\n")
        print(f"Wrote {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
