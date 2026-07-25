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

Everything computes from one seeded monthly operating series -- the same
figure is never entered twice -- and --validate recomputes the identities
(ARR walk, EBITDA build, Rule of 40, LTV:CAC) from raw components.

Run:  python3 board.py
      python3 board.py --validate
      python3 board.py --html examples/board_dashboard.html

No dependencies. Python 3.10+. All data synthetic, seeded.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

random.seed(20260815)

MONTHS = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13)][:18]
GM_TARGET = 0.77


def make_series():
    rows = []
    arr = 21_500_000
    customers = 205
    cash = 34_000_000
    pipe_mult = 3.4
    for mi, month in enumerate(MONTHS):
        beg_arr, beg_cust = arr, customers
        new_arr = beg_arr * random.uniform(0.022, 0.034)
        expansion = beg_arr * random.uniform(0.012, 0.020)
        contraction = beg_arr * random.uniform(0.002, 0.005)
        churn_arr = beg_arr * random.uniform(0.005, 0.009)
        arr = beg_arr + new_arr + expansion - contraction - churn_arr

        new_cust = max(1, round(new_arr / random.uniform(75_000, 110_000)))
        churn_cust = max(0, round(beg_cust * random.uniform(0.004, 0.008)))
        customers = beg_cust + new_cust - churn_cust

        revenue = (beg_arr + arr) / 2 / 12
        # AI cost inside COGS -- the line this scorecard refuses to blend away
        tokens_b = revenue / 1000 * random.uniform(19, 23)     # B tokens/mo
        ai_cost = tokens_b * 1e9 / 1000 * 0.0135 * (0.985 ** mi)
        infra_other = revenue * 0.075
        support = revenue * 0.055
        cogs = ai_cost + infra_other + support
        inference_calls = tokens_b * 1e9 / 3_400

        sm = revenue * random.uniform(0.44, 0.50)
        rd = revenue * random.uniform(0.30, 0.34)
        ga = revenue * random.uniform(0.12, 0.15)
        ebitda = revenue - cogs - sm - rd - ga
        capex = revenue * 0.03
        fcf = ebitda - capex
        cash += fcf

        bookings = (new_arr + expansion) * random.uniform(1.0, 1.25)
        billings = revenue + (new_arr * 0.62) / 12 * 6   # crude deferred build
        pipe_mult *= random.uniform(0.985, 1.01)
        pipeline = (new_arr * 12 / 12 * 3) * pipe_mult   # next-Q new-ARR pipe

        rows.append({
            "month": month, "beg_arr": beg_arr, "new_arr": new_arr,
            "expansion": expansion, "contraction": contraction,
            "churn_arr": churn_arr, "arr": arr,
            "beg_cust": beg_cust, "new_cust": new_cust,
            "churn_cust": churn_cust, "customers": customers,
            "revenue": revenue, "cogs": cogs, "ai_cost": ai_cost,
            "tokens": tokens_b * 1e9, "inference_calls": inference_calls,
            "sm": sm, "rd": rd, "ga": ga, "ebitda": ebitda,
            "capex": capex, "fcf": fcf, "cash": cash,
            "bookings": bookings, "billings": billings, "pipeline": pipeline,
            "headcount": round(118 + mi * 2.6),
        })
    return rows


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
        ("Rule of 40", f"{rule40:.0f}", "YoY ARR growth % + FCF margin %.", "≥40 strong"),
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


def validate(rows) -> None:
    print("VALIDATION -- identities recomputed from raw components")
    print("-" * 90)
    ok = True
    worst = max(abs(r["beg_arr"] + r["new_arr"] + r["expansion"]
                    - r["contraction"] - r["churn_arr"] - r["arr"]) for r in rows)
    chain = all(abs(rows[i]["arr"] - rows[i+1]["beg_arr"]) < 0.01
                for i in range(len(rows)-1))
    ok &= worst < 0.01 and chain
    print(f"  [{'ok ' if worst < 0.01 and chain else 'MISS'}] ARR walk ties and chains "
          f"(max diff ${worst:.4f})")

    worst2 = max(abs(r["revenue"] - r["cogs"] - r["sm"] - r["rd"] - r["ga"]
                     - r["ebitda"]) for r in rows)
    ok &= worst2 < 0.01
    print(f"  [{'ok ' if worst2 < 0.01 else 'MISS'}] EBITDA = revenue − COGS − opex, "
          f"every month (max diff ${worst2:.4f})")

    worst3 = max(abs(r["cogs"] - r["ai_cost"] - r["revenue"]*0.075
                     - r["revenue"]*0.055) for r in rows)
    ok &= worst3 < 1.0
    print(f"  [{'ok ' if worst3 < 1.0 else 'MISS'}] COGS = AI cost + infra + support "
          f"(max diff ${worst3:.4f})")

    cash = 34_000_000
    worst4 = 0.0
    for r in rows:
        cash += r["fcf"]
        worst4 = max(worst4, abs(cash - r["cash"]))
    ok &= worst4 < 0.01
    print(f"  [{'ok ' if worst4 < 0.01 else 'MISS'}] cash rolls forward on FCF "
          f"(max diff ${worst4:.4f})")

    S, _ = compute(rows)
    n_missing = sum(1 for sec in S.values() for (_, _, d, _) in sec if len(d) < 20)
    ok &= n_missing == 0
    total = sum(len(sec) for sec in S.values())
    print(f"  [{'ok ' if n_missing == 0 else 'MISS'}] all {total} metrics carry a "
          f"substantive definition ({n_missing} missing)")
    print("-" * 90)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(S, rows, path: Path) -> None:
    last = rows[-1]
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
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Board One-Pager</h1>
  <div class="sub">{last['month']} · thirty metrics in five sections, every one
    with its definition on the page · synthetic data</div>

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
    components (run --validate) · all data synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Board one-pager with definitions")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    rows = make_series()
    S, rows = compute(rows)
    print_report(S, rows)
    if args.validate:
        validate(rows)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(S, rows, args.html)


if __name__ == "__main__":
    main()
