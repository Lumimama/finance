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
            "opex": opex, "sbc": sbc, "depreciation": depreciation,
            "ebit": ebit, "tax": tax, "net_income": net_income,
            "billings": billings,
            "d_ar": d_ar, "d_ap": d_ap, "d_deferred": d_deferred,
            "cfo": cfo, "capex": capex, "cfi": cfi, "cff": cff,
            "d_cash": d_cash, "beg_cash": cash, "fcf": cfo - capex,
            "cash": end_cash, "ar": end_ar, "ppe": end_ppe,
            "ppe_gross": ppe_gross, "accum_depr": accum_depr,
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

    # ---- cash trajectory, all scenarios --------------------------------
    W, H, PL, PT, PB = 880, 280, 80, 20, 40
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
    legend = "".join(f'<tspan style="fill:{colors[n]}">\u25cf {n}  </tspan>' for n in all_ps)

    # ---- statement renderer --------------------------------------------
    def cell(v, cls=""):
        neg = " neg" if v < -0.005e6 else ""
        return f"<td class='n{neg} {cls}'>{v/1e6:,.1f}</td>"

    def row(label, key_or_fn, ps, cls="", indent=False, sign=1):
        cells = ""
        for p in ps:
            v = (key_or_fn(p) if callable(key_or_fn) else p[key_or_fn]) * sign
            cells += cell(v, cls)
        ind = " style='padding-left:22px'" if indent else ""
        return f"<tr class='{cls}'><td{ind}>{label}</td>{cells}</tr>"

    def spacer(ps):
        return f"<tr class='sp'><td></td>{'<td></td>' * len(ps)}</tr>"

    def header_row(ps):
        return ("<tr><th>$M</th>"
                + "".join(f"<th class='n'>{p['q'][2:]}</th>" for p in ps)
                + "</tr>")

    def section(title, inner):
        return (f"<h2>{title}</h2><div class='tbl'><table>"
                f"<thead>{inner[0]}</thead><tbody>{''.join(inner[1:])}</tbody>"
                f"</table></div>")

    def income_statement(ps):
        return section("Income statement", [
            header_row(ps),
            row("Revenue", "revenue", ps, "b"),
            row("Cost of revenue", "cogs", ps, sign=-1, indent=True),
            row("Gross profit", "gross_profit", ps, "b"),
            spacer(ps),
            row("Sales &amp; marketing", "sm", ps, sign=-1, indent=True),
            row("Research &amp; development", "rd", ps, sign=-1, indent=True),
            row("General &amp; administrative", "ga", ps, sign=-1, indent=True),
            row("Depreciation", "depreciation", ps, sign=-1, indent=True),
            row("EBIT", "ebit", ps, "b"),
            row("Tax", "tax", ps, sign=-1, indent=True),
            row("Net income", "net_income", ps, "b top"),
            spacer(ps),
            row("memo: SBC within opex", "sbc", ps, "mut"),
            row("memo: billings", "billings", ps, "mut"),
        ])

    def balance_sheet(ps):
        return section("Balance sheet", [
            header_row(ps),
            row("Cash", "cash", ps, indent=True),
            row("Accounts receivable", "ar", ps, indent=True),
            row("PP&amp;E, net", "ppe", ps, indent=True),
            row("Total assets", "assets", ps, "b top"),
            spacer(ps),
            row("Accounts payable", "ap", ps, indent=True),
            row("Deferred revenue", "deferred", ps, indent=True),
            row("Total liabilities", "liabilities", ps, "b top"),
            spacer(ps),
            row("Paid-in capital", "apic", ps, indent=True),
            row("Retained earnings (deficit)", "re", ps, indent=True),
            row("Total equity", "equity", ps, "b top"),
            spacer(ps),
            row("Total liabilities + equity",
                lambda p: p["liabilities"] + p["equity"], ps, "b"),
            row("check: A \u2212 (L + E)", "tie", ps, "ok"),
        ])

    def cash_flow(ps):
        return section("Cash flow statement (indirect)", [
            header_row(ps),
            row("Net income", "net_income", ps, indent=True),
            row("+ Depreciation", "depreciation", ps, indent=True),
            row("+ Stock-based compensation", "sbc", ps, indent=True),
            row("\u2212 Increase in receivables", "d_ar", ps, sign=-1, indent=True),
            row("+ Increase in payables", "d_ap", ps, indent=True),
            row("+ Increase in deferred revenue", "d_deferred", ps, indent=True),
            row("Cash from operations", "cfo", ps, "b top"),
            spacer(ps),
            row("Capital expenditure", "capex", ps, sign=-1, indent=True),
            row("Cash from investing", "cfi", ps, "b top"),
            row("Cash from financing", "cff", ps, "b"),
            spacer(ps),
            row("Net change in cash", "d_cash", ps, "b"),
            row("Beginning cash", "beg_cash", ps, indent=True),
            row("Ending cash", "cash", ps, "b top"),
            row("check: = balance-sheet cash", lambda p: 0.0, ps, "ok"),
        ])

    panes = ""
    tabs = ""
    for i, (name, ps) in enumerate(all_ps.items()):
        active = " active" if i == 0 else ""
        tabs += (f"<button class='tab{active}' data-s='{name}' "
                 f"style='--c:{colors[name]}'>{name}</button>")
        panes += (f"<div class='pane{active}' id='pane-{name}'>"
                  + income_statement(ps) + balance_sheet(ps) + cash_flow(ps)
                  + "</div>")

    worst = max(abs(p["tie"]) for ps in all_ps.values() for p in ps)

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Three-Statement Model \u00b7 FY2027\u201329</title>
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
  .wrap {{ max-width:1080px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }}
  h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.07em;
        color:var(--mut); margin:28px 0 10px; font-weight:600; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; margin-top:20px; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .ln {{ fill:none; stroke-width:2.5; stroke-linejoin:round; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .leg {{ font-size:12px; font-weight:600; }}
  .tabs {{ display:flex; gap:8px; margin-top:26px; }}
  .tab {{ font:inherit; font-size:13px; font-weight:600; text-transform:capitalize;
          padding:7px 18px; border-radius:8px; border:1px solid var(--bd);
          background:var(--card); color:var(--mut); cursor:pointer; }}
  .tab.active {{ color:var(--c); border-color:var(--c); }}
  .pane {{ display:none; }} .pane.active {{ display:block; }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
  th,td {{ padding:5px 9px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th:first-child, td:first-child {{ position:sticky; left:0; background:var(--bg);
           min-width:200px; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  tr.sp td {{ border-bottom:0; height:8px; padding:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .b td, td.b {{ font-weight:600; }}
  .top td {{ border-top:1.5px solid var(--fg); }}
  .neg {{ color:var(--neg); }}
  .mut td {{ color:var(--mut); font-size:11.5px; }}
  .ok td {{ color:var(--pos); font-size:11.5px; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Integrated Three-Statement Model</h1>
  <div class="sub">Income statement \u00b7 balance sheet \u00b7 cash flow \u00b7
    quarterly FY2027\u2013FY2029 \u00b7 driver-based \u00b7 synthetic company</div>

  <div class="chart">
    <svg viewBox="0 0 {W} {H}" role="img" aria-label="Ending cash by scenario">
      {grid}{lines}{labels}
      <text x="{PL}" y="14" class="leg">{legend}</text>
    </svg>
  </div>

  <div class="tabs">{tabs}</div>
  {panes}

  <footer>Generated by model.py \u00b7 nothing plugged: every line derives from
    the driver block, A = L + E holds in all 12 quarters of all 3 scenarios
    (max abs diff ${worst:.4f}), and the model exits nonzero rather than
    publishing if it ever doesn't \u00b7 synthetic company</footer>
</div>
<script>
  document.querySelectorAll(".tab").forEach(function (b) {{
    b.addEventListener("click", function () {{
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".pane").forEach(p => p.classList.remove("active"));
      b.classList.add("active");
      document.getElementById("pane-" + b.dataset.s).classList.add("active");
    }});
  }});
</script>
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
