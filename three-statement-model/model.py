"""
Integrated Three-Statement Model
================================
Driver-based P&L -> balance sheet -> cash flow for a B2B software company,
projected quarterly over three years, with scenario toggles -- and the two
checks that make a three-statement model a model rather than three tables:

    ARTICULATION   net income flows to retained earnings; D&A, working
                   capital, SBC, and deferred revenue flow through the
                   indirect-method cash flow; ending cash closes the loop
    THE TIE-OUT    assets = liabilities + equity, every period, to the cent,
                   and cash-flow ending cash = balance-sheet cash

Every value derives from the driver block at the top. Nothing is plugged. If
the balance sheet doesn't balance, the model prints exactly which period and
by how much, and exits nonzero -- a model that "mostly balances" is a model
with a hidden plug somewhere.

Why deferred revenue is the spine here: for a SaaS company billing annually
up front, cash collection *leads* revenue recognition. Model that wrong and
the whole cash forecast is wrong in the most expensive direction.

Run:  python3 model.py                    base case
      python3 model.py --scenario downside | upside
      python3 model.py --html examples/three_statement.html   (all scenarios)
      python3 model.py --check              tie-out only, CI-style

No dependencies. Python 3.10+.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path

QUARTERS = [f"FY{y}Q{q}" for y in (2027, 2028, 2029) for q in (1, 2, 3, 4)]


# ---------------------------------------------------------------------------
# Drivers -- the entire model is a function of this block.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Drivers:
    name: str = "base"
    starting_arr: float = 42_000_000
    arr_growth_q: float = 0.085          # quarterly net new ARR growth rate
    growth_decay: float = 0.94           # growth compresses each quarter
    annual_prepay_share: float = 0.62    # share of bookings billed annually up front
    gross_margin: float = 0.77
    sm_pct_rev: float = 0.46             # S&M as % of revenue, declining
    sm_decline_q: float = 0.99
    rd_pct_rev: float = 0.30
    ga_pct_rev: float = 0.135
    sbc_pct_opex: float = 0.14           # stock comp share of total opex
    capex_pct_rev: float = 0.035
    depr_years: float = 4.0
    dso_days: float = 58.0               # receivables
    dpo_days: float = 34.0               # payables (on cogs + opex ex-SBC)
    tax_rate: float = 0.21               # applied only when pre-tax income > 0
    starting_cash: float = 55_000_000
    starting_ppe: float = 6_500_000
    starting_ar: float = 9_800_000
    starting_ap: float = 4_100_000
    starting_deferred: float = 26_000_000
    starting_re: float = -48_000_000     # accumulated deficit
    # Paid-in capital such that the OPENING balance sheet balances:
    # APIC = assets - liabilities - RE = 71.3M - 30.1M - (-48.0M) = 89.2M.
    # The first version had 145.2M here and every period tied out at exactly
    # -56.0M -- a CONSTANT offset, which is the fingerprint of a bad opening
    # BS rather than broken articulation. The check caught it before publish.
    starting_apic: float = 89_200_000


SCENARIOS = {
    "base": Drivers(),
    "upside": Drivers(name="upside", arr_growth_q=0.105, growth_decay=0.96,
                      gross_margin=0.79, sm_decline_q=0.985),
    "downside": Drivers(name="downside", arr_growth_q=0.055, growth_decay=0.90,
                        gross_margin=0.75, sm_pct_rev=0.50, dso_days=71.0),
}


# ---------------------------------------------------------------------------
def build(d: Drivers) -> list[dict]:
    """Project all three statements quarter by quarter."""
    periods = []
    arr = d.starting_arr
    growth = d.arr_growth_q
    cash, ppe, ar, ap_bal = (d.starting_cash, d.starting_ppe,
                             d.starting_ar, d.starting_ap)
    deferred, re_bal, apic = d.starting_deferred, d.starting_re, d.starting_apic
    accum_depr = 0.0
    sm_pct = d.sm_pct_rev

    for i, q in enumerate(QUARTERS):
        # ---- P&L ----------------------------------------------------------
        beginning_arr = arr
        net_new_arr = arr * growth
        arr = arr + net_new_arr
        growth *= d.growth_decay

        revenue = (beginning_arr + arr) / 2 / 4      # avg ARR, quarterly
        cogs = revenue * (1 - d.gross_margin)
        gross_profit = revenue - cogs

        sm = revenue * sm_pct
        sm_pct *= d.sm_decline_q
        rd = revenue * d.rd_pct_rev
        ga = revenue * d.ga_pct_rev
        opex = sm + rd + ga
        sbc = opex * d.sbc_pct_opex                  # non-cash, inside opex

        depreciation = (ppe + accum_depr) / (d.depr_years * 4)
        ebit = gross_profit - opex - depreciation
        pretax = ebit                                 # no debt: no interest
        tax = max(0.0, pretax) * d.tax_rate if pretax > 0 else 0.0
        net_income = pretax - tax

        # ---- working capital / deferred revenue --------------------------
        # Billings: revenue plus the change in deferred. Annual-prepay share
        # of net new ARR is collected up front; the rest bills quarterly.
        new_deferred = net_new_arr * d.annual_prepay_share \
            + (beginning_arr * d.annual_prepay_share) / 4
        recognized_from_deferred = deferred / 4 + new_deferred / 4
        end_deferred = max(0.0, deferred + new_deferred - recognized_from_deferred)
        d_deferred = end_deferred - deferred

        billings = revenue + d_deferred
        end_ar = billings * d.dso_days / 91.25
        d_ar = end_ar - ar

        cash_costs = cogs + opex - sbc
        end_ap = cash_costs * d.dpo_days / 91.25
        d_ap = end_ap - ap_bal

        # ---- cash flow (indirect) -----------------------------------------
        cfo = net_income + depreciation + sbc - d_ar + d_ap + d_deferred
        capex = revenue * d.capex_pct_rev
        cfi = -capex
        cff = 0.0
        d_cash = cfo + cfi + cff
        end_cash = cash + d_cash

        # ---- balance sheet -------------------------------------------------
        ppe_gross = ppe + accum_depr + capex
        accum_depr += depreciation
        end_ppe = ppe_gross - accum_depr

        re_end = re_bal + net_income
        apic_end = apic + sbc                        # SBC credits equity

        assets = end_cash + end_ar + end_ppe
        liabilities = end_ap + end_deferred
        equity = apic_end + re_end
        tie = assets - (liabilities + equity)

        periods.append({
            "q": q, "arr": arr, "revenue": revenue, "cogs": cogs,
            "gross_profit": gross_profit, "sm": sm, "rd": rd, "ga": ga,
            "sbc": sbc, "depreciation": depreciation, "ebit": ebit,
            "tax": tax, "net_income": net_income,
            "billings": billings, "cfo": cfo, "capex": capex, "fcf": cfo - capex,
            "cash": end_cash, "ar": end_ar, "ppe": end_ppe,
            "ap": end_ap, "deferred": end_deferred,
            "apic": apic_end, "re": re_end,
            "assets": assets, "liabilities": liabilities, "equity": equity,
            "tie": tie,
        })

        cash, ar, ap_bal = end_cash, end_ar, end_ap
        ppe, deferred, re_bal, apic = end_ppe, end_deferred, re_end, apic_end

    return periods


def check_ties(periods: list[dict], tol: float = 0.01) -> list[str]:
    """The non-negotiable: A = L + E every period, to the cent."""
    return [f"{p['q']}: off by {p['tie']:+,.2f}"
            for p in periods if abs(p["tie"]) > tol]


# ---------------------------------------------------------------------------
def m(x: float) -> str:
    return f"{x / 1e6:,.1f}"


def print_model(d: Drivers, periods: list[dict]) -> None:
    w = 118
    print("=" * w)
    print(f"THREE-STATEMENT MODEL  |  scenario: {d.name}  |  $M, quarterly, FY2027-FY2029")
    print("=" * w)

    yr = [p for p in periods if p["q"].endswith("Q4")]
    print(f"{'':<22}" + "".join(f"{p['q'][:6]:>12}" for p in yr))
    print("-" * w)

    def yearly(label: str, key: str, flow: bool = True) -> None:
        vals = []
        for j, p in enumerate(yr):
            if flow:
                year_ps = periods[j * 4:(j + 1) * 4]
                vals.append(sum(x[key] for x in year_ps))
            else:
                vals.append(p[key])
        print(f"  {label:<20}" + "".join(f"{m(v):>12}" for v in vals))

    print("P&L (annual)")
    yearly("Revenue", "revenue")
    yearly("Gross profit", "gross_profit")
    yearly("EBIT", "ebit")
    yearly("Net income", "net_income")
    print("\nCASH FLOW (annual)")
    yearly("Billings", "billings")
    yearly("CFO", "cfo")
    yearly("Capex", "capex")
    yearly("Free cash flow", "fcf")
    print("\nBALANCE SHEET (year-end)")
    yearly("Cash", "cash", flow=False)
    yearly("Receivables", "ar", flow=False)
    yearly("Deferred revenue", "deferred", flow=False)
    yearly("Total assets", "assets", flow=False)
    yearly("Total liabilities", "liabilities", flow=False)
    yearly("  of which equity", "equity", flow=False)

    errs = check_ties(periods)
    print("-" * w)
    if errs:
        print("  TIE-OUT: FAIL")
        for e in errs:
            print(f"    {e}")
    else:
        worst = max(abs(p["tie"]) for p in periods)
        print(f"  TIE-OUT: assets = liabilities + equity in all {len(periods)} "
              f"quarters (max abs diff ${worst:.4f})")
    print()


def print_scenario_compare() -> None:
    w = 90
    print("SCENARIO COMPARISON  ($M)")
    print("-" * w)
    print(f"  {'':<26}{'base':>14}{'upside':>14}{'downside':>14}")
    rows = {}
    for name, drv in SCENARIOS.items():
        ps = build(drv)
        fy29 = ps[-4:]
        rows[name] = {
            "arr": ps[-1]["arr"],
            "rev": sum(p["revenue"] for p in fy29),
            "fcf": sum(p["fcf"] for p in fy29),
            "cash": ps[-1]["cash"],
            "ni": sum(p["net_income"] for p in fy29),
        }
    for label, key in [("FY29 ending ARR", "arr"), ("FY29 revenue", "rev"),
                       ("FY29 net income", "ni"), ("FY29 free cash flow", "fcf"),
                       ("FY29 ending cash", "cash")]:
        print(f"  {label:<26}" + "".join(
            f"{m(rows[n][key]):>14}" for n in ("base", "upside", "downside")))
    print()


# ---------------------------------------------------------------------------
def write_html(path: Path) -> None:
    all_ps = {name: build(drv) for name, drv in SCENARIOS.items()}
    for name, ps in all_ps.items():
        errs = check_ties(ps)
        if errs:
            sys.exit(f"refusing to publish: {name} does not tie: {errs[:2]}")

    colors = {"base": "var(--line)", "upside": "var(--pos)", "downside": "var(--neg)"}

    # cash trajectory chart, all scenarios
    W, H, PL, PT, PB = 880, 300, 80, 20, 40
    pw, ph = W - PL - 24, H - PT - PB
    all_cash = [p["cash"] for ps in all_ps.values() for p in ps]
    lo, hi = min(all_cash) * 0.9, max(all_cash) * 1.05

    def x(i): return PL + pw * i / (len(QUARTERS) - 1)
    def y(v): return PT + ph * (1 - (v - lo) / (hi - lo))

    lines = "".join(
        f'<polyline class="ln" style="stroke:{colors[n]}" points="'
        + " ".join(f"{x(i):.1f},{y(p['cash']):.1f}" for i, p in enumerate(ps))
        + '"/>' for n, ps in all_ps.items())
    labels = "".join(
        f'<text x="{x(i):.1f}" y="{H-16}" text-anchor="middle" class="tick">{q[2:]}</text>'
        for i, q in enumerate(QUARTERS) if i % 2 == 0)
    grid = ""
    for fr in (0, .5, 1.0):
        v = lo + (hi - lo) * fr
        grid += (f'<line x1="{PL}" y1="{y(v):.1f}" x2="{W-24}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{PL-10}" y="{y(v)+4:.1f}" text-anchor="end" class="tick">${v/1e6:.0f}M</text>')
    legend = "".join(
        f'<tspan style="fill:{colors[n]}">● {n}  </tspan>' for n in all_ps)

    base = all_ps["base"]
    yr_idx = [3, 7, 11]

    def yearly_row(label, key, flow=True, cls=""):
        cells = ""
        for name in ("base", "upside", "downside"):
            ps = all_ps[name]
            for j in yr_idx:
                if flow:
                    v = sum(p[key] for p in ps[j - 3:j + 1])
                else:
                    v = ps[j][key]
                cells += f"<td class='n {cls}'>{v/1e6:,.1f}</td>"
        return f"<tr><td>{label}</td>{cells}</tr>"

    head2 = "".join(f"<th class='n'>{fy}</th>" for _ in range(3)
                    for fy in ("FY27", "FY28", "FY29"))

    rows_html = (
        yearly_row("Revenue", "revenue")
        + yearly_row("Gross profit", "gross_profit")
        + yearly_row("EBIT", "ebit")
        + yearly_row("Net income", "net_income", cls="b")
        + yearly_row("Billings", "billings")
        + yearly_row("CFO", "cfo")
        + yearly_row("Free cash flow", "fcf", cls="b")
        + yearly_row("Ending cash", "cash", flow=False)
        + yearly_row("Deferred revenue", "deferred", flow=False)
        + yearly_row("Total assets", "assets", flow=False)
        + yearly_row("Equity", "equity", flow=False, cls="b")
    )

    tie_note = " · ".join(
        f"{n}: ties in {len(ps)}/12 quarters (max diff "
        f"${max(abs(p['tie']) for p in ps):.4f})" for n, ps in all_ps.items())

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Three-Statement Model · FY2027–29</title>
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
  .wrap {{ max-width:1000px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }}
  h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.07em;
        color:var(--mut); margin:30px 0 12px; font-weight:600; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; margin-top:20px; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .ln {{ fill:none; stroke-width:2.5; stroke-linejoin:round; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .leg {{ font-size:12px; font-weight:600; }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
  th,td {{ padding:6px 10px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
        color:var(--mut); font-weight:600; }}
  .grp th {{ text-align:center; border-bottom:2px solid var(--bd); }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .b {{ font-weight:600; }}
  .ok {{ color:var(--pos); font-weight:600; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Integrated Three-Statement Model</h1>
  <div class="sub">Driver-based · quarterly FY2027–FY2029 · three scenarios ·
    synthetic company</div>

  <h2>Ending cash by scenario</h2>
  <div class="chart">
    <svg viewBox="0 0 {W} {H}" role="img" aria-label="Cash by scenario">
      {grid}{lines}{labels}
      <text x="{PL}" y="14" class="leg">{legend}</text>
    </svg>
  </div>

  <h2>Annual summary — $M</h2>
  <div class="tbl"><table>
    <thead>
      <tr class="grp"><th></th><th colspan="3">Base</th>
        <th colspan="3">Upside</th><th colspan="3">Downside</th></tr>
      <tr><th></th>{head2}</tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table></div>

  <h2>Articulation &amp; tie-out</h2>
  <div class="tbl"><table><tbody>
    <tr><td>Net income → retained earnings</td><td class="ok">wired</td></tr>
    <tr><td>SBC → added back in CFO, credited to APIC</td><td class="ok">wired</td></tr>
    <tr><td>Deferred revenue → billings → receivables → collections</td><td class="ok">wired</td></tr>
    <tr><td>Capex → PP&amp;E → depreciation → P&amp;L and CFO add-back</td><td class="ok">wired</td></tr>
    <tr><td>CFO + CFI + CFF → ending cash = balance-sheet cash</td><td class="ok">wired</td></tr>
    <tr><td>Assets = Liabilities + Equity, every quarter, to the cent</td>
      <td class="ok">{tie_note}</td></tr>
  </tbody></table></div>

  <footer>Generated by model.py · no plugs — if the balance sheet doesn't
    balance the script exits nonzero rather than publishing · synthetic company</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Integrated three-statement model")
    ap.add_argument("--scenario", choices=list(SCENARIOS), default="base")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--check", action="store_true", help="tie-out only (CI)")
    args = ap.parse_args()

    if args.check:
        bad = False
        for name, drv in SCENARIOS.items():
            errs = check_ties(build(drv))
            print(f"  {name:<10} {'TIES' if not errs else 'FAIL: ' + '; '.join(errs[:3])}")
            bad |= bool(errs)
        sys.exit(1 if bad else 0)

    d = SCENARIOS[args.scenario]
    periods = build(d)
    print_model(d, periods)
    if check_ties(periods):
        sys.exit(1)
    print_scenario_compare()
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(args.html)


if __name__ == "__main__":
    main()
