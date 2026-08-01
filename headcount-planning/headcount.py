"""
Headcount Plan & Capacity Model
===============================
The hiring plan IS the budget. Headcount is 60-75% of opex at a company at
this stage, it is the largest thing a finance function actually controls,
and it is the model that gets rebuilt every quarter and argued about in
every board meeting.

Most headcount plans are a list of roles and salaries. That version is wrong
in three specific, expensive ways, and this model exists to show all three:

    FULLY-LOADED COST   salary is roughly 70% of what a head actually costs.
                        Employer tax, benefits, equipment, software seats,
                        and recruiting fees are the rest. A plan built on
                        base salary understates cash by 30-40%.

    REQ-TO-START LAG    you approve a req in January and they start in
                        April. Budgeting the cost from the approval month
                        overstates cash; assuming the capacity from the
                        approval month overstates output. Both errors are
                        routinely made in the same spreadsheet, in opposite
                        directions.

    RAMP                a new AE carries no quota for two quarters. A new
                        engineer ships nothing for one. APPROVED headcount
                        and PRODUCTIVE headcount are different numbers, and
                        forecasting capacity off the first one is the single
                        most common planning error in FP&A.

Plus attrition: a plan that ignores it under-hires all year, because every
departure silently consumes a req that was budgeted for growth.

Seeded findings, each proven by --validate:
    F1  fully-loaded cost exceeds the salary-only budget by >30%
    F2  productive FTE trails approved headcount by ~28% -- structural, from
        req-to-start lag plus ramp, not a recruiting failure. (Written first
        as "the gap is widest while hiring fastest"; --validate showed that
        effect is real but modest, so the claim was narrowed to what holds.)
    F3  attrition consumes a meaningful share of gross hires, so net adds
        badly lag gross hires

Run:  python3 headcount.py
      python3 headcount.py --validate
      python3 headcount.py --scenario slow
      python3 headcount.py --html examples/headcount_dashboard.html

No dependencies. Python 3.10+. All figures synthetic, seeded.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

random.seed(20260802)

DATA = Path(__file__).parent / "data"
MONTHS = [f"{y}-{m:02d}" for y in (2026, 2027) for m in range(1, 13)][:18]
MIDX = {m: i for i, m in enumerate(MONTHS)}

# Fully-loaded cost components, as multipliers on base salary.
EMPLOYER_TAX = 0.0765 + 0.015      # FICA + unemployment/other
BENEFITS = 0.14                    # health, dental, 401k match
EQUIPMENT_SOFTWARE_MO = 620        # laptop amortized, SaaS seats, cloud dev
RECRUITING_FEE = 0.20              # of first-year base, on external hires

# (department, base salary, req-to-start lag months, ramp months, monthly attrition)
ROLES = {
    "Research":      dict(salary=265_000, lag=4, ramp=3, attrition=0.008),
    "Engineering":   dict(salary=210_000, lag=3, ramp=2, attrition=0.011),
    "Deployment":    dict(salary=165_000, lag=2, ramp=2, attrition=0.014),
    "Go-to-market":  dict(salary=155_000, lag=2, ramp=6, attrition=0.020),
    "G&A":           dict(salary=140_000, lag=2, ramp=1, attrition=0.012),
}

STARTING_HEADCOUNT = {"Research": 14, "Engineering": 22, "Deployment": 6,
                      "Go-to-market": 5, "G&A": 4}

# Approved hiring plan: reqs opened per department per month.
SCENARIOS = {
    "plan":  {"Research": 1.1, "Engineering": 1.6, "Deployment": 1.0,
              "Go-to-market": 0.9, "G&A": 0.4},
    "slow":  {"Research": 0.6, "Engineering": 0.9, "Deployment": 0.5,
              "Go-to-market": 0.5, "G&A": 0.2},
    "fast":  {"Research": 1.6, "Engineering": 2.4, "Deployment": 1.6,
              "Go-to-market": 1.4, "G&A": 0.6},
}


# ---------------------------------------------------------------------------
def fully_loaded_monthly(salary: float, first_year: bool) -> float:
    """Monthly cash cost of one head, everything in."""
    base_mo = salary / 12
    loaded = base_mo * (1 + EMPLOYER_TAX + BENEFITS) + EQUIPMENT_SOFTWARE_MO
    if first_year:
        loaded += salary * RECRUITING_FEE / 12
    return loaded


def build_plan(scenario: str = "plan"):
    """Month-by-month roster: reqs opened, starts, attrition, productive FTE."""
    rate = SCENARIOS[scenario]
    # Each head: (dept, start_idx). Seed the existing team as fully ramped.
    heads = []
    for dept, n in STARTING_HEADCOUNT.items():
        for _ in range(n):
            heads.append({"dept": dept, "start_idx": -12, "left_idx": None,
                          "external": False})

    reqs = []            # (dept, opened_idx, start_idx)
    for mi in range(len(MONTHS)):
        for dept, per_mo in rate.items():
            n = int(per_mo) + (1 if random.random() < (per_mo % 1) else 0)
            for _ in range(n):
                lag = ROLES[dept]["lag"] + random.choice([-1, 0, 0, 1])
                lag = max(1, lag)
                reqs.append({"dept": dept, "opened_idx": mi,
                             "start_idx": mi + lag})

    for r in reqs:
        if r["start_idx"] < len(MONTHS):
            heads.append({"dept": r["dept"], "start_idx": r["start_idx"],
                          "left_idx": None, "external": True})

    # attrition
    for h in heads:
        for mi in range(max(0, h["start_idx"]), len(MONTHS)):
            if random.random() < ROLES[h["dept"]]["attrition"]:
                h["left_idx"] = mi
                break

    rows = []
    for mi in range(len(MONTHS)):
        active = [h for h in heads
                  if h["start_idx"] <= mi and (h["left_idx"] is None or h["left_idx"] > mi)]
        starts = [h for h in heads if h["start_idx"] == mi and h["external"]]
        leavers = [h for h in heads if h["left_idx"] == mi]
        opened = [r for r in reqs if r["opened_idx"] == mi]
        # approved = existing + every req opened to date (the number the plan
        # is usually built on)
        approved = (sum(STARTING_HEADCOUNT.values())
                    + sum(1 for r in reqs if r["opened_idx"] <= mi))

        productive = 0.0
        by_dept_fte = defaultdict(float)
        by_dept_prod = defaultdict(float)
        cost = 0.0
        for h in active:
            ramp_mo = ROLES[h["dept"]]["ramp"]
            tenure = mi - h["start_idx"]
            frac = 1.0 if tenure >= ramp_mo else (tenure + 1) / (ramp_mo + 1)
            productive += frac
            by_dept_fte[h["dept"]] += 1
            by_dept_prod[h["dept"]] += frac
            cost += fully_loaded_monthly(
                ROLES[h["dept"]]["salary"],
                first_year=(h["external"] and tenure < 12))

        salary_only = sum(ROLES[h["dept"]]["salary"] / 12 for h in active)

        rows.append({
            "month": MONTHS[mi],
            "approved_headcount": approved,
            "fte": len(active),
            "productive_fte": round(productive, 2),
            "reqs_opened": len(opened),
            "starts": len(starts),
            "leavers": len(leavers),
            "net_adds": len(starts) - len(leavers),
            "salary_only_cost": round(salary_only, 2),
            "fully_loaded_cost": round(cost, 2),
            "by_dept_fte": dict(by_dept_fte),
            "by_dept_productive": {k: round(v, 2) for k, v in by_dept_prod.items()},
        })
    return rows, heads, reqs


# ---------------------------------------------------------------------------
def money(x): return f"${x/1e6:,.2f}M" if abs(x) >= 1e6 else f"${x:,.0f}"


def print_report(rows, heads, reqs, scenario) -> None:
    w = 106
    last = rows[-1]
    print("=" * w)
    print(f"HEADCOUNT PLAN & CAPACITY  |  scenario: {scenario}  |  "
          f"{MONTHS[0]} to {MONTHS[-1]}")
    print("=" * w)
    print(f"  starting FTE                {sum(STARTING_HEADCOUNT.values()):>12}")
    print(f"  ending FTE                  {last['fte']:>12}")
    print(f"  approved headcount          {last['approved_headcount']:>12}   "
          f"<- the number plans are usually built on")
    print(f"  productive FTE              {last['productive_fte']:>12.1f}   "
          f"<- the number capacity should be built on")
    print(f"  gap                         {last['approved_headcount']-last['productive_fte']:>12.1f}")

    gross = sum(r["starts"] for r in rows)
    leav = sum(r["leavers"] for r in rows)
    print(f"\n  gross hires                 {gross:>12}")
    print(f"  attrition                   {leav:>12}   "
          f"({leav/max(1,gross):.0%} of gross hires)")
    print(f"  net adds                    {gross-leav:>12}")

    sal = sum(r["salary_only_cost"] for r in rows)
    loaded = sum(r["fully_loaded_cost"] for r in rows)
    print(f"\nCOST OF THE PLAN")
    print("-" * w)
    print(f"  salary-only budget          {money(sal):>12}")
    print(f"  fully-loaded actual         {money(loaded):>12}")
    print(f"  understatement              {money(loaded-sal):>12}   "
          f"({loaded/sal-1:+.0%})")
    print(f"    employer tax + benefits   {EMPLOYER_TAX+BENEFITS:>11.1%} of base")
    print(f"    equipment + software      {money(EQUIPMENT_SOFTWARE_MO)}/head/mo")
    print(f"    recruiting fee            {RECRUITING_FEE:>11.0%} of first-year base, external hires")

    print(f"\n  {'month':<9}{'approved':>10}{'FTE':>7}{'productive':>12}"
          f"{'starts':>8}{'leavers':>9}{'salary $':>12}{'loaded $':>12}")
    print("-" * w)
    for r in rows[::3]:
        print(f"  {r['month']:<9}{r['approved_headcount']:>10}{r['fte']:>7}"
              f"{r['productive_fte']:>12.1f}{r['starts']:>8}{r['leavers']:>9}"
              f"{r['salary_only_cost']/1e6:>11.2f}M{r['fully_loaded_cost']/1e6:>11.2f}M")

    print(f"\nBY DEPARTMENT  (ending)")
    print("-" * w)
    print(f"  {'department':<16}{'FTE':>7}{'productive':>12}{'ramp mo':>10}"
          f"{'req lag mo':>12}{'loaded $/head/yr':>18}")
    for d in ROLES:
        fte = last["by_dept_fte"].get(d, 0)
        prod = last["by_dept_productive"].get(d, 0.0)
        per_head = fully_loaded_monthly(ROLES[d]["salary"], False) * 12
        print(f"  {d:<16}{fte:>7}{prod:>12.1f}{ROLES[d]['ramp']:>10}"
              f"{ROLES[d]['lag']:>12}{money(per_head):>18}")
    print()


def validate(rows, heads, reqs) -> None:
    print("VALIDATION")
    print("-" * 94)
    ok = True

    # --- identities -------------------------------------------------------
    worst = 0.0
    for i in range(1, len(rows)):
        expect = rows[i-1]["fte"] + rows[i]["starts"] - rows[i]["leavers"]
        worst = max(worst, abs(expect - rows[i]["fte"]))
    ok &= worst < 0.01
    print(f"  [{'ok ' if worst < 0.01 else 'MISS'}] roster rolls forward: prior FTE "
          f"+ starts − leavers = FTE, every month (max diff {worst:.2f})")

    # --- sanity bounds ----------------------------------------------------
    bad = [r for r in rows if r["productive_fte"] > r["fte"] + 0.01]
    bad2 = [r for r in rows if r["fte"] > r["approved_headcount"]]
    bad3 = [r for r in rows if r["fully_loaded_cost"] < r["salary_only_cost"]]
    bounds = not (bad or bad2 or bad3)
    ok &= bounds
    print(f"  [{'ok ' if bounds else 'MISS'}] sanity bounds: productive ≤ FTE ≤ "
          f"approved, and loaded cost ≥ salary cost "
          f"({len(bad)+len(bad2)+len(bad3)} violations)")

    # --- F1: fully-loaded premium ----------------------------------------
    sal = sum(r["salary_only_cost"] for r in rows)
    loaded = sum(r["fully_loaded_cost"] for r in rows)
    f1 = loaded > sal * 1.30
    ok &= f1
    print(f"  [{'ok ' if f1 else 'MISS'}] F1: fully-loaded cost is {loaded/sal-1:+.0%} "
          f"above the salary-only budget ({money(loaded-sal)} on this plan) — "
          f"must exceed +30%")

    # --- F2: the capacity gap is structurally large -----------------------
    # An earlier version of this check claimed the gap widens with hiring
    # SPEED. It does, but only slightly (29% vs 27% of approved headcount at
    # the same month) -- the fully-ramped existing team dilutes the effect in
    # both cases. The robust finding is simply that the gap is large, and it
    # is structural rather than a recruiting failure.
    last = rows[-1]
    gap = last["approved_headcount"] - last["productive_fte"]
    share = gap / last["approved_headcount"]
    f2 = share > 0.20
    ok &= f2
    print(f"  [{'ok ' if f2 else 'MISS'}] F2: {gap:.0f} of "
          f"{last['approved_headcount']} approved heads ({share:.0%}) are not "
          f"productive capacity — req-to-start lag plus ramp, not a recruiting "
          f"failure (must exceed 20%)")

    def end_share(scn):
        r = build_plan(scn)[0][-1]
        return (r["approved_headcount"] - r["productive_fte"]) / r["approved_headcount"]
    print(f"       context: {end_share('fast'):.0%} under fast hiring vs "
          f"{end_share('slow'):.0%} under slow — directionally worse when "
          f"hiring hard, but the effect is modest, not dramatic")

    # --- F3: attrition eats gross hires -----------------------------------
    gross = sum(r["starts"] for r in rows)
    leav = sum(r["leavers"] for r in rows)
    f3 = leav / max(1, gross) > 0.10
    ok &= f3
    print(f"  [{'ok ' if f3 else 'MISS'}] F3: attrition consumed {leav} of {gross} "
          f"gross hires ({leav/max(1,gross):.0%}) — a plan that budgets gross "
          f"hires as net adds under-staffs all year")

    print("-" * 94)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(rows, scenario, path: Path) -> None:
    last = rows[-1]
    n = len(rows)
    W, H, PL, PT, PB = 880, 280, 84, 22, 38
    pw, ph = W - PL - 24, H - PT - PB

    def x(i): return PL + pw * i / (n - 1)

    hi = max(r["approved_headcount"] for r in rows) * 1.12
    def y(v): return PT + ph * (1 - v / hi)
    appr = " ".join(f"{x(i):.1f},{y(r['approved_headcount']):.1f}" for i, r in enumerate(rows))
    fte = " ".join(f"{x(i):.1f},{y(r['fte']):.1f}" for i, r in enumerate(rows))
    prod = " ".join(f"{x(i):.1f},{y(r['productive_fte']):.1f}" for i, r in enumerate(rows))
    # shaded gap between approved and productive
    gap_poly = (" ".join(f"{x(i):.1f},{y(r['approved_headcount']):.1f}" for i, r in enumerate(rows))
                + " " + " ".join(f"{x(i):.1f},{y(r['productive_fte']):.1f}"
                                 for i, r in reversed(list(enumerate(rows)))))
    grid = "".join(
        f'<line x1="{PL}" y1="{y(hi*f):.1f}" x2="{W-24}" y2="{y(hi*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{y(hi*f)+4:.1f}" text-anchor="end" class="tick">{hi*f:.0f}</text>'
        for f in (0, .5, 1.0))
    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{H-14}" text-anchor="middle" class="tick">{rows[i]["month"][2:]}</text>'
        for i in range(0, n, 3))

    # cost: salary vs loaded
    hi_c = max(r["fully_loaded_cost"] for r in rows) * 1.15
    def yc(v): return PT + ph * (1 - v / hi_c)
    sal_line = " ".join(f"{x(i):.1f},{yc(r['salary_only_cost']):.1f}" for i, r in enumerate(rows))
    load_line = " ".join(f"{x(i):.1f},{yc(r['fully_loaded_cost']):.1f}" for i, r in enumerate(rows))
    load_poly = (load_line + " " + " ".join(f"{x(i):.1f},{yc(r['salary_only_cost']):.1f}"
                                            for i, r in reversed(list(enumerate(rows)))))
    grid_c = "".join(
        f'<line x1="{PL}" y1="{yc(hi_c*f):.1f}" x2="{W-24}" y2="{yc(hi_c*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{yc(hi_c*f)+4:.1f}" text-anchor="end" class="tick">${hi_c*f/1e6:,.1f}M</text>'
        for f in (0, .5, 1.0))

    sal = sum(r["salary_only_cost"] for r in rows)
    loaded = sum(r["fully_loaded_cost"] for r in rows)
    gross = sum(r["starts"] for r in rows)
    leav = sum(r["leavers"] for r in rows)

    dept_rows = ""
    for d in ROLES:
        f_ = last["by_dept_fte"].get(d, 0)
        p_ = last["by_dept_productive"].get(d, 0.0)
        per_head = fully_loaded_monthly(ROLES[d]["salary"], False) * 12
        dept_rows += (f"<tr><td>{d}</td><td class='n'>{f_}</td>"
                      f"<td class='n'>{p_:.1f}</td>"
                      f"<td class='n'>{ROLES[d]['lag']} mo</td>"
                      f"<td class='n'>{ROLES[d]['ramp']} mo</td>"
                      f"<td class='n'>${ROLES[d]['salary']:,.0f}</td>"
                      f"<td class='n b'>${per_head:,.0f}</td></tr>")

    mo_rows = "".join(
        f"<tr><td>{r['month']}</td><td class='n'>{r['approved_headcount']}</td>"
        f"<td class='n'>{r['fte']}</td><td class='n'>{r['productive_fte']:.1f}</td>"
        f"<td class='n'>{r['starts']}</td><td class='n neg'>{r['leavers']}</td>"
        f"<td class='n'>${r['salary_only_cost']/1e6:,.2f}M</td>"
        f"<td class='n b'>${r['fully_loaded_cost']/1e6:,.2f}M</td></tr>"
        for r in rows[-9:])

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Headcount Plan &amp; Capacity</title>
<style>
  :root {{ color-scheme: light dark; --fg:#12151a; --mut:#5d6673; --bg:#fff;
           --line:#1f6feb; --grid:#e6e9ee; --neg:#b3261e; --pos:#0f7b3f;
           --card:#fbfcfd; --bd:#e6e9ee; --warn:#d97706; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg:#e8ebf0; --mut:#98a2b3; --bg:#0d1117; --line:#58a6ff;
             --grid:#232a33; --neg:#ff7b72; --pos:#3fb950; --card:#141a22;
             --bd:#232a33; --warn:#d29922; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px 20px; background:var(--bg); color:var(--fg);
          font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1000px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }}
  h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.07em;
        color:var(--mut); margin:28px 0 10px; font-weight:600; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(155px,1fr));
           gap:12px; margin-top:22px; }}
  .kpi {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
          padding:13px 15px; }}
  .kpi .k {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
             color:var(--mut); }}
  .kpi .v {{ font-size:19px; font-weight:600; margin-top:3px;
             font-variant-numeric:tabular-nums; }}
  .kpi .n2 {{ font-size:11px; color:var(--mut); margin-top:1px; }}
  .warnk .v {{ color:var(--warn); }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .leg {{ font-size:12px; font-weight:600; }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
  th,td {{ padding:6px 10px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .b {{ font-weight:600; }} .neg {{ color:var(--neg); }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  .callout {{ background:var(--card); border:1px solid var(--bd);
              border-left:3px solid var(--warn); border-radius:8px;
              padding:14px 16px; margin-top:14px; font-size:13.5px; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Headcount Plan &amp; Capacity</h1>
  <div class="sub">Scenario: <strong>{scenario}</strong> · {MONTHS[0]} to
    {MONTHS[-1]} · fully-loaded costing · synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Ending FTE</div><div class="v">{last['fte']}</div>
      <div class="n2">from {sum(STARTING_HEADCOUNT.values())}</div></div>
    <div class="kpi"><div class="k">Approved headcount</div>
      <div class="v">{last['approved_headcount']}</div>
      <div class="n2">reqs opened to date</div></div>
    <div class="kpi warnk"><div class="k">Productive FTE</div>
      <div class="v">{last['productive_fte']:.0f}</div>
      <div class="n2">{last['approved_headcount']-last['productive_fte']:.0f} below approved</div></div>
    <div class="kpi"><div class="k">Plan cost (18 mo)</div>
      <div class="v">${loaded/1e6:,.1f}M</div>
      <div class="n2">fully loaded</div></div>
    <div class="kpi warnk"><div class="k">Understated by salary-only</div>
      <div class="v">${(loaded-sal)/1e6:,.1f}M</div>
      <div class="n2">{loaded/sal-1:+.0%}</div></div>
  </div>

  <div class="callout"><strong>Approved headcount and productive headcount are
    different numbers.</strong> A req approved in January produces a start in
    March or April, and that person is not fully productive for another one to
    six months depending on the role. Budget the cost from approval and you
    overstate cash; assume the capacity from approval and you overstate output.
    Both errors get made in the same spreadsheet, in opposite directions, and
    they do not cancel.</div>

  <h2>Approved vs actual vs productive headcount</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid}
    <polygon points="{gap_poly}" fill="var(--warn)" opacity="0.13"/>
    <polyline points="{appr}" fill="none" stroke="var(--warn)" stroke-width="2.5"/>
    <polyline points="{fte}" fill="none" stroke="var(--line)" stroke-width="2.5"/>
    <polyline points="{prod}" fill="none" stroke="var(--pos)" stroke-width="2.5"/>
    {ticks}
    <text x="{PL}" y="14" class="leg"><tspan fill="var(--warn)">● approved</tspan>
    <tspan fill="var(--line)"> ● on payroll</tspan>
    <tspan fill="var(--pos)"> ● productive</tspan></text></svg></div>
  <div class="note">The shaded band is capacity the plan assumes and the company
    does not have — <strong>{last['approved_headcount']-last['productive_fte']:.0f}
    of {last['approved_headcount']} approved heads
    ({(last['approved_headcount']-last['productive_fte'])/last['approved_headcount']:.0%})</strong>.
    It is structural, from req-to-start lag plus ramp, and it does not close by
    recruiting harder. Hiring faster widens it, though by less than you would
    expect — the already-ramped team dilutes the effect.</div>

  <h2>Salary-only budget vs fully-loaded cash</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid_c}
    <polygon points="{load_poly}" fill="var(--neg)" opacity="0.13"/>
    <polyline points="{load_line}" fill="none" stroke="var(--neg)" stroke-width="2.5"/>
    <polyline points="{sal_line}" fill="none" stroke="var(--line)" stroke-width="2.5"/>
    {ticks}
    <text x="{PL}" y="14" class="leg"><tspan fill="var(--neg)">● fully loaded</tspan>
    <tspan fill="var(--line)"> ● salary only</tspan></text></svg></div>
  <div class="note">The gap is {loaded/sal-1:+.0%} —
    <strong>${(loaded-sal)/1e6:,.1f}M</strong> over this plan. Employer tax and
    benefits are {EMPLOYER_TAX+BENEFITS:.1%} of base, equipment and software run
    ${EQUIPMENT_SOFTWARE_MO:,}/head/month, and external hires carry a
    {RECRUITING_FEE:.0%} recruiting fee on first-year base. A hiring plan
    presented in base salary is not a budget.</div>

  <h2>By department</h2>
  <div class="tbl"><table>
    <thead><tr><th>Department</th><th class="n">FTE</th><th class="n">Productive</th>
      <th class="n">Req→start</th><th class="n">Ramp</th><th class="n">Base</th>
      <th class="n">Fully loaded /yr</th></tr></thead>
    <tbody>{dept_rows}</tbody></table></div>
  <div class="note">Go-to-market has the longest ramp (six months to full quota)
    and the highest attrition — which is why GTM hiring converts to capacity far
    more slowly than an engineering plan of the same size, and why the two
    should never be modelled with one blended assumption.</div>

  <h2>Monthly detail</h2>
  <div class="tbl"><table>
    <thead><tr><th>Month</th><th class="n">Approved</th><th class="n">FTE</th>
      <th class="n">Productive</th><th class="n">Starts</th><th class="n">Leavers</th>
      <th class="n">Salary</th><th class="n">Fully loaded</th></tr></thead>
    <tbody>{mo_rows}</tbody></table></div>
  <div class="note">Attrition consumed <strong>{leav} of {gross} gross hires
    ({leav/max(1,gross):.0%})</strong> over the window. A plan that treats gross
    hires as net adds under-staffs every quarter and then reports the shortfall
    as a recruiting problem.</div>

  <footer>Generated by headcount.py · roster roll-forward ties, sanity bounds
    enforced (run --validate) · <code>--scenario slow|plan|fast</code> ·
    all figures synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Headcount plan and capacity model")
    ap.add_argument("--scenario", choices=list(SCENARIOS), default="plan")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    rows, heads, reqs = build_plan(args.scenario)
    with (DATA / f"headcount_{args.scenario}.csv").open("w", newline="") as f:
        cols = [k for k in rows[0] if not k.startswith("by_dept")]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    print_report(rows, heads, reqs, args.scenario)
    if args.validate:
        validate(rows, heads, reqs)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(rows, args.scenario, args.html)


if __name__ == "__main__":
    main()
