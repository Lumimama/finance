"""
Board Metrics
=============
Turns a monthly operating file into the metrics page of a board deck.

Every SaaS board asks the same eight questions, and every month someone
rebuilds the same eight formulas in a fresh tab. The formulas are not the
hard part -- agreeing on them once and computing them the same way every
month is. That's what this is: the definitions written down as code, with
the arithmetic visible.

Where a metric has more than one defensible definition (net retention,
burn multiple, CAC payback all do), the one used here is stated in the
docstring for that function. A metrics pack whose definitions are implicit
is a metrics pack that quietly changes meaning when someone new builds it.

Usage
-----
    python board_metrics.py
    python board_metrics.py --html dashboard.html
    python board_metrics.py --months 18
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

DATA = Path(__file__).parent / "data" / "monthly_metrics.csv"

NUMERIC = [
    "beginning_arr", "new_arr", "expansion_arr", "contraction_arr", "churned_arr",
    "ending_arr", "beginning_customers", "new_customers", "churned_customers",
    "ending_customers", "revenue", "cogs", "sm_spend", "rd_spend", "ga_spend",
    "financing_inflow", "ending_cash", "headcount",
]


def load(path: Path = DATA) -> list[dict]:
    with path.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in NUMERIC:
            r[k] = float(r[k])
    return rows


def net_burn(r: dict) -> float:
    """Operating cash burn for one month. Negative means burning.

    Excludes financing inflows deliberately -- a Series C is not operating
    performance, and folding it in makes burn multiple and runway lie.
    """
    return r["revenue"] - (r["cogs"] + r["sm_spend"] + r["rd_spend"] + r["ga_spend"])


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------
def net_revenue_retention(rows: list[dict]) -> float:
    """NRR over the window, chain-linked from monthly rates.

    Definition: for each month, (expansion - contraction - churn) / beginning
    ARR, compounded across the window. New business is excluded -- NRR
    measures what happens to the base you already had, and mixing new logos
    in is the most common way this metric gets inflated.
    """
    factor = 1.0
    for r in rows:
        delta = r["expansion_arr"] - r["contraction_arr"] - r["churned_arr"]
        factor *= 1 + delta / r["beginning_arr"]
    return factor


def gross_revenue_retention(rows: list[dict]) -> float:
    """GRR: same window, but expansion cannot offset losses. Caps at 100%."""
    factor = 1.0
    for r in rows:
        loss = r["contraction_arr"] + r["churned_arr"]
        factor *= 1 - loss / r["beginning_arr"]
    return factor


def logo_retention(rows: list[dict]) -> float:
    factor = 1.0
    for r in rows:
        factor *= 1 - r["churned_customers"] / r["beginning_customers"]
    return factor


# ---------------------------------------------------------------------------
# Efficiency
# ---------------------------------------------------------------------------
def burn_multiple(rows: list[dict]) -> float | None:
    """Net burn divided by net new ARR over the window.

    How many dollars burned per dollar of new recurring revenue. Below 1.0
    is exceptional, 1-1.5 good, above 2 is a problem at this stage. Returns
    None if the company generated cash (the ratio stops being meaningful).
    """
    burn = -sum(net_burn(r) for r in rows)
    net_new = rows[-1]["ending_arr"] - rows[0]["beginning_arr"]
    if burn <= 0 or net_new <= 0:
        return None
    return burn / net_new


def cac_payback_months(rows: list[dict], gross_margin: float) -> float | None:
    """Months of gross profit from new ARR needed to repay the S&M that won it.

    Blended and gross-margin-adjusted: total S&M in the window over the
    monthly gross profit implied by the new ARR won in the same window. It
    charges all of S&M -- including the spend supporting expansion -- against
    new logos only, so it runs conservative. That is the point.
    """
    sm = sum(r["sm_spend"] for r in rows)
    new_arr = sum(r["new_arr"] for r in rows)
    if new_arr <= 0:
        return None
    monthly_gross_profit = new_arr * gross_margin / 12
    return sm / monthly_gross_profit


def magic_number(rows: list[dict], prior: list[dict]) -> float | None:
    """Net new ARR added in the period over the prior period's S&M spend.

    Above 0.75 generally means sales spend is working hard enough to lean in.

    Note the missing x4. The textbook form of this metric takes the change in
    *quarterly recognized revenue* and annualizes it. Net new ARR is already
    an annual figure, so annualizing it again inflates the result roughly
    fourfold -- which is how this metric ends up reported at 3.0 by companies
    whose CAC payback says otherwise.
    """
    net_new = rows[-1]["ending_arr"] - rows[0]["beginning_arr"]
    prior_sm = sum(r["sm_spend"] for r in prior)
    if prior_sm <= 0:
        return None
    return net_new / prior_sm


def runway_months(rows: list[dict], lookback: int = 3) -> float:
    """Ending cash over average operating burn of the last `lookback` months."""
    recent = rows[-lookback:]
    avg_burn = -sum(net_burn(r) for r in recent) / len(recent)
    if avg_burn <= 0:
        return float("inf")
    return rows[-1]["ending_cash"] / avg_burn


# ---------------------------------------------------------------------------
def compute(rows: list[dict], window: int = 12) -> dict:
    w = rows[-window:]
    prior = rows[-2 * window : -window] if len(rows) >= 2 * window else []
    latest = rows[-1]

    revenue = sum(r["revenue"] for r in w)
    cogs = sum(r["cogs"] for r in w)
    gross_margin = (revenue - cogs) / revenue
    burn = -sum(net_burn(r) for r in w)

    beginning_arr = w[0]["beginning_arr"]
    ending_arr = latest["ending_arr"]
    yoy_growth = ending_arr / beginning_arr - 1

    fcf_margin = -burn / revenue
    rule_of_40 = (yoy_growth + fcf_margin) * 100

    # Trailing-quarter view for the sales-efficiency metrics -- a 12-month
    # CAC payback smooths over exactly the shift a board wants to see.
    q, prior_q = rows[-3:], rows[-6:-3]

    return {
        "window": window,
        "as_of": latest["month"],
        "arr": ending_arr,
        "arr_prior": beginning_arr,
        "yoy_growth": yoy_growth,
        "net_new_arr": ending_arr - beginning_arr,
        "customers": int(latest["ending_customers"]),
        "headcount": int(latest["headcount"]),
        "arr_per_employee": ending_arr / latest["headcount"],
        "cash": latest["ending_cash"],
        "revenue": revenue,
        "gross_margin": gross_margin,
        "burn": burn,
        "avg_monthly_burn": burn / window,
        "fcf_margin": fcf_margin,
        "rule_of_40": rule_of_40,
        "nrr": net_revenue_retention(w),
        "grr": gross_revenue_retention(w),
        "logo_retention": logo_retention(w),
        "burn_multiple": burn_multiple(w),
        "cac_payback": cac_payback_months(q, gross_margin),
        "magic_number": magic_number(q, prior_q),
        "runway": runway_months(rows),
        "walk": {
            "beginning": beginning_arr,
            "new": sum(r["new_arr"] for r in w),
            "expansion": sum(r["expansion_arr"] for r in w),
            "contraction": sum(r["contraction_arr"] for r in w),
            "churn": sum(r["churned_arr"] for r in w),
            "ending": ending_arr,
        },
        "prior_window": prior,
        "months": w,
    }


# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------
def m(x: float) -> str:
    return f"${x / 1e6:,.1f}M"


def pctf(x: float) -> str:
    return f"{x * 100:.1f}%"


def bench(value: float | None, good: float, ok: float, higher_is_better: bool = True) -> str:
    if value is None:
        return ""
    if higher_is_better:
        return "strong" if value >= good else ("ok" if value >= ok else "watch")
    return "strong" if value <= good else ("ok" if value <= ok else "watch")


def print_metrics(s: dict) -> None:
    width = 74
    print("=" * width)
    print(f"BOARD METRICS  |  trailing {s['window']} months through {s['as_of']}")
    print("=" * width)

    print("\nGROWTH")
    print("-" * width)
    print(f"  ARR                        {m(s['arr']):>12}   from {m(s['arr_prior'])}")
    print(f"  YoY growth                 {pctf(s['yoy_growth']):>12}   [{bench(s['yoy_growth'], .40, .25)}]")
    print(f"  Net new ARR                {m(s['net_new_arr']):>12}")
    print(f"  Customers                  {s['customers']:>12,}")
    print(f"  ARR per employee           {s['arr_per_employee']/1000:>10,.0f}K   [{bench(s['arr_per_employee'], 200_000, 150_000)}]")

    print("\nRETENTION")
    print("-" * width)
    print(f"  Net revenue retention      {pctf(s['nrr']):>12}   [{bench(s['nrr'], 1.10, 1.00)}]")
    print(f"  Gross revenue retention    {pctf(s['grr']):>12}   [{bench(s['grr'], .90, .85)}]")
    print(f"  Logo retention             {pctf(s['logo_retention']):>12}")

    print("\nEFFICIENCY")
    print("-" * width)
    bm = s["burn_multiple"]
    print(f"  Burn multiple              {bm:>12.2f}   [{bench(bm, 1.0, 1.5, higher_is_better=False)}]"
          if bm else "  Burn multiple                cash generative")
    cp = s["cac_payback"]
    print(f"  CAC payback (trailing Q)   {cp:>9.1f} mo   [{bench(cp, 12, 18, higher_is_better=False)}]"
          if cp else "  CAC payback                        n/a")
    mn = s["magic_number"]
    print(f"  Magic number (trailing Q)  {mn:>12.2f}   [{bench(mn, .75, .50)}]"
          if mn else "  Magic number                       n/a")
    print(f"  Gross margin               {pctf(s['gross_margin']):>12}   [{bench(s['gross_margin'], .75, .70)}]")
    print(f"  Rule of 40                 {s['rule_of_40']:>12.0f}   [{bench(s['rule_of_40'], 40, 20)}]")

    print("\nCAPITAL")
    print("-" * width)
    print(f"  Cash                       {m(s['cash']):>12}")
    print(f"  Net burn ({s['window']}mo)             {m(s['burn']):>12}")
    print(f"  Average monthly burn       {m(s['avg_monthly_burn']):>12}")
    rw = s["runway"]
    print(f"  Runway                     {rw:>9.1f} mo   [{bench(rw, 24, 12)}]"
          if rw != float("inf") else "  Runway                       cash generative")

    w = s["walk"]
    print(f"\nARR WALK  (trailing {s['window']} months)")
    print("-" * width)
    print(f"  Beginning ARR              {m(w['beginning']):>12}")
    print(f"  + New                      {m(w['new']):>12}")
    print(f"  + Expansion                {m(w['expansion']):>12}")
    print(f"  - Contraction              {m(w['contraction']):>12}")
    print(f"  - Churn                    {m(w['churn']):>12}")
    print(f"  {'':<26} {'-' * 12:>12}")
    print(f"  Ending ARR                 {m(w['ending']):>12}")
    tie = w["beginning"] + w["new"] + w["expansion"] - w["contraction"] - w["churn"]
    status = "ties" if abs(tie - w["ending"]) < 1 else f"DOES NOT TIE (off by {tie - w['ending']:,.0f})"
    print(f"  {'':<26} {status:>12}")
    print()


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def write_html(s: dict, path: Path) -> None:
    months = s["months"]
    arr = [r["ending_arr"] for r in months]
    labels = [r["month"][2:] for r in months]

    # --- ARR trend line ---
    W, H, PL, PR, PT, PB = 880, 250, 70, 24, 20, 40
    pw, ph = W - PL - PR, H - PT - PB
    lo, hi = min(arr) * 0.92, max(arr) * 1.04

    def x(i): return PL + pw * i / (len(arr) - 1)
    def y(v): return PT + ph * (1 - (v - lo) / (hi - lo))

    line = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(arr))
    area = f"{PL},{y(lo)} {line} {x(len(arr) - 1):.1f},{y(lo)}"
    grid = ""
    for f in (0, 0.5, 1.0):
        v = lo + (hi - lo) * f
        gy = y(v)
        grid += (f'<line x1="{PL}" y1="{gy:.1f}" x2="{W - PR}" y2="{gy:.1f}" class="grid"/>'
                 f'<text x="{PL - 10}" y="{gy + 4:.1f}" text-anchor="end" class="tick">${v/1e6:.0f}M</text>')
    xticks = "".join(
        f'<text x="{x(i):.1f}" y="{H - 14}" text-anchor="middle" class="tick">{lab}</text>'
        for i, lab in enumerate(labels) if i % 2 == 0
    )

    # --- ARR walk waterfall ---
    w = s["walk"]
    bars = [
        ("Beginning", w["beginning"], "total"),
        ("New", w["new"], "pos"),
        ("Expansion", w["expansion"], "pos"),
        ("Contraction", -w["contraction"], "neg"),
        ("Churn", -w["churn"], "neg"),
        ("Ending", w["ending"], "total"),
    ]
    WW, WH, WPL, WPB, WPT = 880, 260, 70, 44, 20
    wpw, wph = WW - WPL - 24, WH - WPT - WPB
    wmax = max(w["beginning"], w["ending"]) * 1.12
    bar_w = wpw / len(bars) * 0.58
    gap = wpw / len(bars)

    def wy(v): return WPT + wph * (1 - v / wmax)

    wsvg, running = "", 0.0
    for i, (label, value, kind) in enumerate(bars):
        cx = WPL + gap * i + gap / 2
        if kind == "total":
            top, bot = wy(value), wy(0)
            running = value
        else:
            start, end = running, running + value
            top, bot = wy(max(start, end)), wy(min(start, end))
            running = end
        sign = {"pos": "+", "neg": "−"}.get(kind, "")
        wsvg += (
            f'<rect x="{cx - bar_w/2:.1f}" y="{top:.1f}" width="{bar_w:.1f}" '
            f'height="{max(bot - top, 1.5):.1f}" class="bar-{kind}" rx="2"/>'
            f'<text x="{cx:.1f}" y="{top - 7:.1f}" text-anchor="middle" class="barval">'
            f'{sign}${abs(value)/1e6:.1f}M</text>'
            f'<text x="{cx:.1f}" y="{WH - 16}" text-anchor="middle" class="tick">{label}</text>'
        )
    wgrid = ""
    for f in (0, 0.5, 1.0):
        v = wmax * f
        gy = wy(v)
        wgrid += (f'<line x1="{WPL}" y1="{gy:.1f}" x2="{WW - 24}" y2="{gy:.1f}" class="grid"/>'
                  f'<text x="{WPL - 10}" y="{gy + 4:.1f}" text-anchor="end" class="tick">${v/1e6:.0f}M</text>')

    def tile(k, v, note="", tone=""):
        return (f'<div class="kpi {tone}"><div class="k">{k}</div>'
                f'<div class="v">{v}</div><div class="n">{note}</div></div>')

    def tone(label): return {"strong": "good", "ok": "", "watch": "warn"}.get(label, "")

    bm, cp, mn, rw = s["burn_multiple"], s["cac_payback"], s["magic_number"], s["runway"]
    tiles = "".join([
        tile("ARR", m(s["arr"]), f"{pctf(s['yoy_growth'])} YoY", tone(bench(s["yoy_growth"], .40, .25))),
        tile("Net new ARR", m(s["net_new_arr"]), f"trailing {s['window']} mo"),
        tile("Net revenue retention", pctf(s["nrr"]), "expansion net of churn", tone(bench(s["nrr"], 1.10, 1.00))),
        tile("Gross revenue retention", pctf(s["grr"]), "no expansion credit", tone(bench(s["grr"], .90, .85))),
        tile("Burn multiple", f"{bm:.2f}" if bm else "n/a", "burn per $1 net new ARR",
             tone(bench(bm, 1.0, 1.5, higher_is_better=False))),
        tile("CAC payback", f"{cp:.1f} mo" if cp else "n/a", "trailing quarter",
             tone(bench(cp, 12, 18, higher_is_better=False))),
        tile("Magic number", f"{mn:.2f}" if mn else "n/a", "trailing quarter", tone(bench(mn, .75, .50))),
        tile("Gross margin", pctf(s["gross_margin"]), "", tone(bench(s["gross_margin"], .75, .70))),
        tile("Rule of 40", f"{s['rule_of_40']:.0f}", f"{pctf(s['yoy_growth'])} growth &middot; {pctf(s['fcf_margin'])} FCF margin",
             tone(bench(s["rule_of_40"], 40, 20))),
        tile("Cash", m(s["cash"]), f"{m(s['avg_monthly_burn'])}/mo burn"),
        tile("Runway", f"{rw:.0f} mo" if rw != float("inf") else "n/a", "at trailing 3-mo burn",
             tone(bench(rw, 24, 12))),
        tile("ARR per employee", f"${s['arr_per_employee']/1000:.0f}K", f"{s['headcount']} people",
             tone(bench(s["arr_per_employee"], 200_000, 150_000))),
    ])

    rows_html = "".join(
        f"<tr><td>{r['month']}</td><td class='n'>{m(r['ending_arr'])}</td>"
        f"<td class='n pos'>+{m(r['new_arr'])}</td>"
        f"<td class='n pos'>+{m(r['expansion_arr'])}</td>"
        f"<td class='n neg'>-{m(r['contraction_arr'])}</td>"
        f"<td class='n neg'>-{m(r['churned_arr'])}</td>"
        f"<td class='n'>{int(r['ending_customers']):,}</td>"
        f"<td class='n {'neg' if net_burn(r) < 0 else 'pos'}'>{m(net_burn(r))}</td></tr>"
        for r in months
    )

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Board Metrics &middot; {s['as_of']}</title>
<style>
  :root {{ color-scheme: light dark; --fg:#12151a; --mut:#5d6673; --bg:#fff;
           --line:#1f6feb; --fill:#1f6feb18; --grid:#e6e9ee; --neg:#b3261e;
           --pos:#0f7b3f; --card:#fbfcfd; --bd:#e6e9ee; --warnbd:#e0a03a; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg:#e8ebf0; --mut:#98a2b3; --bg:#0d1117; --line:#58a6ff;
             --fill:#58a6ff22; --grid:#232a33; --neg:#ff7b72; --pos:#3fb950;
             --card:#141a22; --bd:#232a33; --warnbd:#d29922; }}
  }}
  body {{ margin:0; padding:32px; background:var(--bg); color:var(--fg);
          font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:940px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.07em;
        color:var(--mut); margin:32px 0 12px; font-weight:600; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
           gap:12px; margin-top:24px; }}
  .kpi {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
          padding:14px 16px; }}
  .kpi.good {{ border-left:3px solid var(--pos); }}
  .kpi.warn {{ border-left:3px solid var(--warnbd); }}
  .kpi .k {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em;
             color:var(--mut); }}
  .kpi .v {{ font-size:21px; font-weight:600; margin-top:3px;
             font-variant-numeric:tabular-nums; }}
  .kpi .n {{ font-size:11px; color:var(--mut); margin-top:2px; }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .area {{ fill:var(--fill); }}
  .arr {{ fill:none; stroke:var(--line); stroke-width:2.5;
          stroke-linejoin:round; stroke-linecap:round; }}
  .bar-total {{ fill:var(--line); }} .bar-pos {{ fill:var(--pos); }}
  .bar-neg {{ fill:var(--neg); }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .barval {{ fill:var(--fg); font-size:11px; font-weight:600; }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th,td {{ padding:8px 12px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .neg {{ color:var(--neg); }} .pos {{ color:var(--pos); }}
  footer {{ color:var(--mut); font-size:12px; margin-top:28px; }}
</style>
<div class="wrap">
  <h1>Board Metrics</h1>
  <div class="sub">Trailing {s['window']} months through {s['as_of']} &middot; synthetic data</div>

  <div class="kpis">{tiles}</div>

  <h2>ARR</h2>
  <div class="chart">
    <svg viewBox="0 0 {W} {H}" role="img" aria-label="ARR by month">
      {grid}<polygon class="area" points="{area}"/>
      <polyline class="arr" points="{line}"/>{xticks}
    </svg>
  </div>

  <h2>ARR walk &mdash; trailing {s['window']} months</h2>
  <div class="chart">
    <svg viewBox="0 0 {WW} {WH}" role="img" aria-label="ARR walk waterfall">
      {wgrid}{wsvg}
    </svg>
  </div>

  <h2>Monthly detail</h2>
  <div class="tbl"><table>
    <thead><tr><th>Month</th><th class="n">Ending ARR</th><th class="n">New</th>
      <th class="n">Expansion</th><th class="n">Contraction</th><th class="n">Churn</th>
      <th class="n">Customers</th><th class="n">Net burn</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table></div>

  <footer>Generated by board_metrics.py. All figures synthetic.</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="SaaS board metrics from a monthly operating file")
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--months", type=int, default=12, help="Trailing window (default 12)")
    ap.add_argument("--html", type=Path, default=None)
    args = ap.parse_args()

    rows = load(args.data)
    s = compute(rows, args.months)
    print_metrics(s)
    if args.html:
        write_html(s, args.html)


if __name__ == "__main__":
    main()
