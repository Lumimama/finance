"""
Monte Carlo Scenario Planner
============================
A single-point forecast answers "what do we expect?" This answers the harder
questions a board actually asks: "how bad can it get, with what probability,
and which assumption should we be arguing about?"

Method
------
Take the same driver-based ARR/cash model a deterministic forecast uses, but
draw the drivers from distributions instead of fixing them:

    quarterly ARR growth      normal around plan, clipped
    gross margin              normal, tight
    net revenue retention     normal -- the compounding one
    S&M efficiency drift      normal around planned decline
    collections timing (DSO)  lognormal-ish right tail: DSO stretches, never
                              compresses as much as it slips

Run 10,000 simulations of 12 quarters. Report:

    - P10 / P50 / P90 fan for ARR and cash
    - probability of breaching the board cash floor
    - probability of needing to raise within the window
    - tornado: rank-correlation of each input draw with ending cash --
      which assumption actually drives the outcome spread

The tornado is the deliverable. Everything else says "there is risk"; the
tornado says which lever to work.

Uses only the stdlib (random.gauss + statistics). Seeded, reproducible.

Run:  python3 simulate.py
      python3 simulate.py --sims 20000
      python3 simulate.py --html examples/scenario_dashboard.html
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
from pathlib import Path

SEED = 20260724
N_SIMS = 10_000
QUARTERS = 12
CASH_FLOOR = 20_000_000     # board-committed minimum

# Starting state (same synthetic company as three-statement-model)
START_ARR = 42_000_000
START_CASH = 55_000_000

# Distributions: (mean, sd) unless noted. Means match the deterministic
# base case so the P50 here should roughly reproduce it -- a sanity check.
DIST = {
    "arr_growth_q":  (0.085, 0.022),   # plan 8.5%/q, real-world spread
    "growth_decay":  (0.94, 0.02),
    "gross_margin":  (0.77, 0.015),
    "nrr_q":         (1.027, 0.009),   # quarterly NRR (~111% annualized)
    "sm_pct":        (0.46, 0.04),
    "opex_other_pct": (0.435, 0.02),   # R&D + G&A as % of revenue
    "dso_days":      (58.0, 9.0),      # right tail applied below
}


def _planned_revenue() -> list[float]:
    """Deterministic revenue path at plan (distribution means)."""
    arr, growth = START_ARR, DIST["arr_growth_q"][0]
    out = []
    for _ in range(QUARTERS):
        beginning = arr
        arr = arr * DIST["nrr_q"][0] + beginning * growth
        growth *= DIST["growth_decay"][0]
        out.append((beginning + arr) / 2 / 4)
    return out


PLANNED_REVENUE = _planned_revenue()


def draw(rng: random.Random) -> dict:
    d = {k: rng.gauss(mu, sd) for k, (mu, sd) in DIST.items()}
    # DSO: convert the normal draw into a right-skewed one. Collections slip
    # further than they ever improve; a symmetric DSO is a fantasy.
    base_mu, base_sd = DIST["dso_days"]
    z = (d["dso_days"] - base_mu) / base_sd
    d["dso_days"] = base_mu + base_sd * (math.exp(0.55 * z) - 1) / 0.55
    # clip to sane ranges
    d["arr_growth_q"] = max(-0.02, d["arr_growth_q"])
    d["gross_margin"] = min(0.86, max(0.62, d["gross_margin"]))
    d["nrr_q"] = max(0.96, d["nrr_q"])
    d["sm_pct"] = max(0.25, d["sm_pct"])
    return d


def simulate_path(d: dict, rng: random.Random) -> dict:
    """12 quarters of ARR and cash under one drawn parameter set.

    The cash engine mirrors three-statement-model/model.py deliberately:
    annual prepayments (deferred revenue) lead recognition, SBC inside opex
    is non-cash. Omit either and the model overstates burn so badly that
    growth appears to *destroy* cash -- the first version of this file did
    exactly that (73% floor breach, growth rank-correlated -0.45 with
    ending cash) until the two models were made consistent.
    """
    PREPAY, SBC_SHARE = 0.62, 0.14
    planned_rev = PLANNED_REVENUE
    arr, cash = START_ARR, START_CASH
    growth = d["arr_growth_q"]
    arr_path, cash_path = [], []
    min_cash = cash
    deferred = START_ARR * PREPAY * 0.5   # mid-cycle stock of prepayments
    prev_ar = (START_ARR / 4) * d["dso_days"] / 91.25

    for q in range(QUARTERS):
        beginning_arr = arr
        # growth = new business (drawn, decaying) + retention effect (drawn)
        new_growth = growth * (1 + rng.gauss(0, 0.15))   # execution noise/q
        arr = arr * d["nrr_q"] + beginning_arr * max(0.0, new_growth)
        growth *= d["growth_decay"]
        net_new_arr = arr - beginning_arr

        revenue = (beginning_arr + arr) / 2 / 4
        gross_profit = revenue * d["gross_margin"]
        # Opex is STICKY: teams are hired and committed against the plan, not
        # against realized revenue. Scaling opex to actual revenue silently
        # assumes instant cost discipline in a downside -- which is exactly
        # the scenario planning exists to interrogate. So spend follows the
        # planned revenue path; only the ratios themselves are drawn.
        opex = planned_rev[q] * (d["sm_pct"] + d["opex_other_pct"])
        sbc = opex * SBC_SHARE                       # non-cash
        capex = revenue * 0.035                      # mirrors the 3-stmt model
        ebitda_ish = gross_profit - opex + sbc - capex

        # deferred revenue: annual-prepay share collects up front
        new_deferred = max(0.0, net_new_arr) * PREPAY \
            + beginning_arr * PREPAY / 4
        recognized = deferred / 4 + new_deferred / 4
        end_deferred = max(0.0, deferred + new_deferred - recognized)
        d_deferred = end_deferred - deferred
        deferred = end_deferred

        # collections: AR follows billings (revenue + deferred build)
        billings = revenue + d_deferred
        ar = billings * d["dso_days"] / 91.25
        d_ar = ar - prev_ar
        prev_ar = ar

        cash += ebitda_ish + d_deferred - d_ar
        arr_path.append(arr)
        cash_path.append(cash)
        min_cash = min(min_cash, cash)

    return {"arr_path": arr_path, "cash_path": cash_path,
            "ending_arr": arr, "ending_cash": cash, "min_cash": min_cash,
            "draws": d}


def run(n_sims: int) -> list[dict]:
    rng = random.Random(SEED)
    return [simulate_path(draw(rng), rng) for _ in range(n_sims)]


# ---------------------------------------------------------------------------
def pct(paths: list[list[float]], p: float) -> list[float]:
    out = []
    for q in range(QUARTERS):
        vals = sorted(path[q] for path in paths)
        out.append(vals[int(p * (len(vals) - 1))])
    return out


def spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation, stdlib-only."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for rank, i in enumerate(order):
            r[i] = rank
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (sx * sy) if sx and sy else 0.0


def tornado(sims: list[dict]) -> list[tuple[str, float]]:
    ending = [s["ending_cash"] for s in sims]
    out = []
    for k in DIST:
        xs = [s["draws"][k] for s in sims]
        out.append((k, spearman(xs, ending)))
    return sorted(out, key=lambda kv: -abs(kv[1]))


def analyze(sims: list[dict]) -> dict:
    ending_cash = sorted(s["ending_cash"] for s in sims)
    ending_arr = sorted(s["ending_arr"] for s in sims)
    n = len(sims)

    def q(vals, p):
        return vals[int(p * (n - 1))]

    return {
        "n": n,
        "arr_p10": q(ending_arr, 0.10), "arr_p50": q(ending_arr, 0.50),
        "arr_p90": q(ending_arr, 0.90),
        "cash_p10": q(ending_cash, 0.10), "cash_p50": q(ending_cash, 0.50),
        "cash_p90": q(ending_cash, 0.90),
        "p_floor_breach": sum(1 for s in sims if s["min_cash"] < CASH_FLOOR) / n,
        "p_negative": sum(1 for s in sims if s["min_cash"] < 0) / n,
        "arr_fan": {p: pct([s["arr_path"] for s in sims], p)
                    for p in (0.10, 0.50, 0.90)},
        "cash_fan": {p: pct([s["cash_path"] for s in sims], p)
                     for p in (0.10, 0.50, 0.90)},
        "tornado": tornado(sims),
    }


# ---------------------------------------------------------------------------
LABELS = {
    "arr_growth_q": "New-business growth rate",
    "nrr_q": "Net revenue retention",
    "sm_pct": "S&M spend level",
    "gross_margin": "Gross margin",
    "dso_days": "Collections timing (DSO)",
    "growth_decay": "Growth persistence",
    "opex_other_pct": "R&D + G&A level",
}


def mm(x): return f"${x/1e6:,.1f}M"


def print_report(a: dict) -> None:
    w = 92
    print("=" * w)
    print(f"MONTE CARLO SCENARIO PLANNER  |  {a['n']:,} simulations  |  12 quarters")
    print("=" * w)
    print(f"  {'':<22}{'P10':>12}{'P50':>12}{'P90':>12}")
    print(f"  {'Ending ARR':<22}{mm(a['arr_p10']):>12}{mm(a['arr_p50']):>12}{mm(a['arr_p90']):>12}")
    print(f"  {'Ending cash':<22}{mm(a['cash_p10']):>12}{mm(a['cash_p50']):>12}{mm(a['cash_p90']):>12}")
    print()
    print(f"  P(min cash < {mm(CASH_FLOOR)} board floor)   {a['p_floor_breach']:>7.1%}")
    print(f"  P(cash goes negative)              {a['p_negative']:>7.1%}")

    print(f"\nTORNADO -- what actually drives ending cash")
    print("-" * w)
    print(f"  {'driver':<28}{'rank corr':>10}   " + "" )
    max_r = max(abs(r) for _, r in a["tornado"]) or 1
    for k, r in a["tornado"]:
        bar = "#" * int(abs(r) / max_r * 40)
        sign = "+" if r >= 0 else "-"
        print(f"  {LABELS[k]:<28}{r:>+10.2f}   {sign}{bar}")
    print()
    print("  Read: |corr| ranks how much each assumption moves the outcome.")
    print("  Argue about the top two. The rest is noise management.")
    print()


# ---------------------------------------------------------------------------
def write_html(a: dict, path: Path) -> None:
    W, H, PL, PT, PB = 880, 300, 80, 20, 40
    pw, ph = W - PL - 24, H - PT - PB

    def fan_svg(fan: dict, fmt=lambda v: f"${v/1e6:.0f}M") -> str:
        lo = min(fan[0.10]) * 0.92
        hi = max(fan[0.90]) * 1.05

        def x(i): return PL + pw * i / (QUARTERS - 1)
        def y(v): return PT + ph * (1 - (v - lo) / (hi - lo))

        band = ("M" + " L".join(f"{x(i):.1f},{y(v):.1f}"
                                for i, v in enumerate(fan[0.90]))
                + " L" + " L".join(f"{x(i):.1f},{y(v):.1f}"
                                   for i, v in enumerate(reversed(fan[0.10]))) + " Z")
        p50 = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(fan[0.50]))
        grid = ""
        for fr in (0, .5, 1.0):
            v = lo + (hi - lo) * fr
            grid += (f'<line x1="{PL}" y1="{y(v):.1f}" x2="{W-24}" y2="{y(v):.1f}" class="grid"/>'
                     f'<text x="{PL-10}" y="{y(v)+4:.1f}" text-anchor="end" class="tick">{fmt(v)}</text>')
        ticks = "".join(f'<text x="{x(i):.1f}" y="{H-16}" text-anchor="middle" class="tick">Q{i+1}</text>'
                        for i in range(0, QUARTERS, 2))
        return (f'<svg viewBox="0 0 {W} {H}">{grid}'
                f'<path d="{band}" class="band"/>'
                f'<polyline points="{p50}" class="p50"/>{ticks}</svg>')

    max_r = max(abs(r) for _, r in a["tornado"]) or 1
    torn_rows = ""
    for k, r in a["tornado"]:
        pct_w = abs(r) / max_r * 100
        cls = "tpos" if r >= 0 else "tneg"
        torn_rows += f"""
    <div class="trow"><div class="tlabel">{LABELS[k]}</div>
      <div class="ttrack"><div class="tbar {cls}" style="width:{pct_w:.0f}%"></div></div>
      <div class="tval">{r:+.2f}</div></div>"""

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scenario Planner · Monte Carlo</title>
<style>
  :root {{ color-scheme: light dark; --fg:#12151a; --mut:#5d6673; --bg:#fff;
           --line:#1f6feb; --grid:#e6e9ee; --neg:#b3261e; --pos:#0f7b3f;
           --card:#fbfcfd; --bd:#e6e9ee; --band:#1f6feb22; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg:#e8ebf0; --mut:#98a2b3; --bg:#0d1117; --line:#58a6ff;
             --grid:#232a33; --neg:#ff7b72; --pos:#3fb950; --card:#141a22;
             --bd:#232a33; --band:#58a6ff2b; }} }}
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
  .warn .v {{ color:var(--neg); }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .band {{ fill:var(--band); }}
  .p50 {{ fill:none; stroke:var(--line); stroke-width:2.5; stroke-linejoin:round; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .panel {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:18px 20px; }}
  .trow {{ display:grid; grid-template-columns:220px 1fr 52px; gap:12px;
           align-items:center; margin-bottom:10px; }}
  .tlabel {{ font-size:13px; }}
  .ttrack {{ background:var(--grid); border-radius:4px; height:10px; }}
  .tbar {{ height:10px; border-radius:4px; }}
  .tpos {{ background:var(--pos); }} .tneg {{ background:var(--neg); }}
  .tval {{ font-size:12px; text-align:right; font-variant-numeric:tabular-nums;
           color:var(--mut); }}
  .note {{ font-size:12.5px; color:var(--mut); margin-top:10px; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Monte Carlo Scenario Planner</h1>
  <div class="sub">{a['n']:,} simulations · 12 quarters · drivers drawn from
    distributions · synthetic company</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Ending ARR P50</div><div class="v">{mm(a['arr_p50'])}</div>
      <div class="n2">P10 {mm(a['arr_p10'])} · P90 {mm(a['arr_p90'])}</div></div>
    <div class="kpi"><div class="k">Ending cash P50</div><div class="v">{mm(a['cash_p50'])}</div>
      <div class="n2">P10 {mm(a['cash_p10'])} · P90 {mm(a['cash_p90'])}</div></div>
    <div class="kpi warn"><div class="k">P(breach {mm(CASH_FLOOR)} floor)</div>
      <div class="v">{a['p_floor_breach']:.1%}</div></div>
    <div class="kpi warn"><div class="k">P(cash negative)</div>
      <div class="v">{a['p_negative']:.1%}</div></div>
  </div>

  <h2>Cash — P10 / P50 / P90 fan</h2>
  <div class="chart">{fan_svg(a['cash_fan'])}</div>

  <h2>ARR — P10 / P50 / P90 fan</h2>
  <div class="chart">{fan_svg(a['arr_fan'])}</div>

  <h2>Tornado — what actually drives ending cash</h2>
  <div class="panel">{torn_rows}
    <div class="note">Rank correlation of each input draw with ending cash
      across all {a['n']:,} simulations. Argue about the top two assumptions;
      the rest is noise management.</div>
  </div>

  <footer>Generated by simulate.py · seeded and reproducible · stdlib only</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Monte Carlo scenario planner")
    ap.add_argument("--sims", type=int, default=N_SIMS)
    ap.add_argument("--html", type=Path, default=None)
    args = ap.parse_args()

    sims = run(args.sims)
    a = analyze(sims)
    print_report(a)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(a, args.html)


if __name__ == "__main__":
    main()
