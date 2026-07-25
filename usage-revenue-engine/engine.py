"""
Usage-Based Revenue Engine
==========================
The finance layer of AI pricing: a contract register expanded into monthly
revenue across three streams, for a platform that bills a subscription PLUS
metered usage against committed minimums.

    PLATFORM LICENSE   annual fee by tier, recognized ratably
    USAGE              metered tasks vs a committed monthly minimum:
                       bill max(actual, commit); overage above commit
                       carries a premium rate
    IMPLEMENTATION     one-time deployment fee, recognized over launch

Why this needs its own engine: subscription-only models treat ARR as a
stepwise thing that changes when contracts change. Usage revenue moves
every month without a signature -- so the walk needs a line subscription
models don't have (usage expansion / contraction), retention splits into
contracted vs consumed, and the commercial questions invert:

    A customer at 60% of commit is not "safe revenue" -- they are paying
    for capacity they don't use, and they are a DOWNGRADE at renewal.
    A customer at 140% of commit is not "over-serviced" -- they are the
    upsell list, and every month they stay on overage rates past a commit
    step-up conversation is money left on the table (theirs or yours).

The commit-utilization panel is therefore the deliverable, the same way
the tornado was for the Monte Carlo: everything else describes revenue;
utilization tells you which contracts to act on.

Seeded (and --validate proves the analysis surfaces them):
    - three contracts under 65% utilization for 3+ consecutive months
    - three contracts over 130%, paying overage rates for months running
    - blended realized rate per task compresses as mix shifts to larger
      tiers -- growth with rate compression, visible only in the rate curve

Invariants checked to the cent: per-contract build sums to the totals; the
ARR walk (incl. usage expansion) reconciles every month; usage billing
equals max(actual, commit) + overage premium on every contract-month.

Run:  python3 engine.py
      python3 engine.py --validate
      python3 engine.py --html examples/usage_dashboard.html

No dependencies. Python 3.10+. All data synthetic.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

random.seed(20260722)

DATA = Path(__file__).parent / "data"
MONTHS = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13)][:18]
MIDX = {m: i for i, m in enumerate(MONTHS)}

# Tier sheet: annual platform fee, committed tasks/month, list price per task,
# implementation fee. Larger commits buy lower unit rates -- the standard
# volume ladder -- which is exactly what creates blended-rate compression.
TIERS = {
    "starter":    dict(platform=24_000,  commit=8_000,   rate=0.240, impl=8_000),
    "growth":     dict(platform=72_000,  commit=35_000,  rate=0.150, impl=24_000),
    "enterprise": dict(platform=180_000, commit=140_000, rate=0.085, impl=60_000),
}
OVERAGE_PREMIUM = 0.20        # rate multiplier above commit
IMPL_MONTHS = 2               # implementation recognized over launch
INFERENCE_COST_START = 0.052  # $/task, declining -- the AI margin story
INFERENCE_COST_DECAY = 0.97   # per month


# ---------------------------------------------------------------------------
def make_contracts() -> list[dict]:
    """~42 contracts with monthly usage paths. Usage is where the story is."""
    out, n = [], 0
    profiles = (["ramping"] * 5 + ["steady"] * 3 + ["over_committed"] * 2
                + ["power_user"] * 2)
    for mi, month in enumerate(MONTHS[:-2]):
        for _ in range(random.choice([1, 2, 2, 3, 3, 4])):
            n += 1
            tier = random.choices(list(TIERS), [0.45, 0.38, 0.17])[0]
            t = TIERS[tier]
            commit = round(t["commit"] * random.uniform(0.7, 1.6), -2)
            profile = random.choice(profiles)
            churn_at = None
            if profile == "over_committed" and random.random() < 0.5:
                churn_at = mi + random.randint(9, 14)   # shelfware cancels
            elif random.random() < 0.06:
                churn_at = mi + random.randint(6, 15)
            out.append({
                "contract_id": f"K{n:03d}",
                "tier": tier, "start": month, "start_idx": mi,
                "platform_acv": t["platform"],
                "committed_tasks_mo": commit,
                "rate_per_task": t["rate"],
                "impl_fee": t["impl"],
                "usage_profile": profile,
                "churn_idx": churn_at if churn_at and churn_at < len(MONTHS) else None,
            })
    return out


def usage_path(c: dict) -> dict[int, float]:
    """Actual tasks per live month, by profile."""
    rng = random.Random(c["contract_id"])       # per-contract, reproducible
    commit = c["committed_tasks_mo"]
    start_lvl = {"ramping": 0.45, "steady": 0.92,
                 "over_committed": 0.55, "power_user": 0.85}[c["usage_profile"]]
    growth = {"ramping": 1.09, "steady": 1.005,
              "over_committed": 0.985, "power_user": 1.065}[c["usage_profile"]]
    out, lvl = {}, start_lvl
    for mi in range(c["start_idx"], c["churn_idx"] or len(MONTHS)):
        out[mi] = max(0.0, round(commit * lvl * rng.uniform(0.93, 1.07)))
        lvl *= growth
        if c["usage_profile"] == "over_committed":
            lvl = max(lvl, 0.40)
        if c["usage_profile"] == "power_user":
            lvl = min(lvl, 1.75)
    return out


# ---------------------------------------------------------------------------
def usage_bill(actual: float, commit: float, rate: float) -> tuple[float, float, float]:
    """(billed $, base $, overage $): bill max(actual, commit); overage at premium."""
    base = commit * rate
    over = max(0.0, actual - commit) * rate * (1 + OVERAGE_PREMIUM)
    return base + over, base, over


def build(contracts):
    """Per-contract, per-month revenue by stream + contract-month detail."""
    detail = []          # rows: contract x month x streams
    for c in contracts:
        path = usage_path(c)
        for mi in range(c["start_idx"], c["churn_idx"] or len(MONTHS)):
            platform = c["platform_acv"] / 12
            impl = c["impl_fee"] / IMPL_MONTHS \
                if mi - c["start_idx"] < IMPL_MONTHS else 0.0
            actual = path.get(mi, 0.0)
            billed, base, over = usage_bill(actual, c["committed_tasks_mo"],
                                            c["rate_per_task"])
            detail.append({
                "contract_id": c["contract_id"], "tier": c["tier"], "mi": mi,
                "platform": platform, "impl": impl,
                "usage_billed": billed, "usage_base": base, "usage_over": over,
                "actual_tasks": actual,
                "committed_tasks": c["committed_tasks_mo"],
                "utilization": actual / c["committed_tasks_mo"],
            })
    return detail


def run_rate_arr(detail_row) -> float:
    """Annualized run-rate for one contract-month: platform + usage x 12.
    Implementation is one-time and excluded from ARR by definition."""
    return (detail_row["platform"] + detail_row["usage_billed"]) * 12


def arr_walk(contracts, detail):
    """Monthly walk with usage expansion/contraction as separate lines."""
    by_cm = {(d["contract_id"], d["mi"]): d for d in detail}
    live_prev: dict[str, float] = {}
    walk = []
    for mi in range(len(MONTHS)):
        new = expansion = contraction = churned = 0.0
        live_now: dict[str, float] = {}
        for c in contracts:
            d = by_cm.get((c["contract_id"], mi))
            if d is None:
                if c["contract_id"] in live_prev:
                    churned += live_prev[c["contract_id"]]
                continue
            arr = run_rate_arr(d)
            live_now[c["contract_id"]] = arr
            prev = live_prev.get(c["contract_id"])
            if prev is None:
                new += arr
            elif arr > prev:
                expansion += arr - prev
            else:
                contraction += prev - arr
        beginning = sum(live_prev.values())
        ending = sum(live_now.values())
        walk.append({
            "mi": mi, "month": MONTHS[mi], "beginning": beginning, "new": new,
            "usage_expansion": expansion, "usage_contraction": contraction,
            "churned": churned, "ending": ending,
        })
        live_prev = live_now
    return walk


def utilization_flags(contracts, detail, low=0.65, high=1.30, run=3):
    """Contracts persistently under or over commit -- the action list."""
    by_c = defaultdict(list)
    for d in detail:
        by_c[d["contract_id"]].append(d)
    flags = {"under": [], "over": []}
    for c in contracts:
        rows = sorted(by_c[c["contract_id"]], key=lambda d: d["mi"])[-run:]
        if len(rows) < run or c["churn_idx"] is not None:
            continue
        utils = [d["utilization"] for d in rows]
        annual_waste = (c["committed_tasks_mo"]
                        * (1 - sum(utils) / len(utils))
                        * c["rate_per_task"] * 12)
        annual_over = sum(d["usage_over"] for d in rows) / len(rows) * 12
        if all(u < low for u in utils):
            flags["under"].append({
                "contract_id": c["contract_id"], "tier": c["tier"],
                "avg_utilization": sum(utils) / len(utils),
                "annual_commit_unused": annual_waste})
        elif all(u > high for u in utils):
            flags["over"].append({
                "contract_id": c["contract_id"], "tier": c["tier"],
                "avg_utilization": sum(utils) / len(utils),
                "annual_overage_run_rate": annual_over})
    flags["under"].sort(key=lambda f: -f["annual_commit_unused"])
    flags["over"].sort(key=lambda f: -f["annual_overage_run_rate"])
    return flags


def rate_and_margin(detail):
    """Blended realized $/task and usage gross margin, monthly."""
    out = []
    for mi in range(len(MONTHS)):
        rows = [d for d in detail if d["mi"] == mi]
        tasks = sum(d["actual_tasks"] for d in rows)
        usage_rev = sum(d["usage_billed"] for d in rows)
        if tasks == 0:
            continue
        inf_cost = INFERENCE_COST_START * (INFERENCE_COST_DECAY ** mi)
        out.append({
            "mi": mi, "month": MONTHS[mi], "tasks": tasks,
            "blended_rate": usage_rev / tasks,
            "inference_cost": inf_cost,
            "usage_gm": 1 - inf_cost * tasks / usage_rev,
        })
    return out


# ---------------------------------------------------------------------------
def money(x): return f"${x:,.0f}"


def print_report(contracts, detail) -> None:
    w = 104
    walk = arr_walk(contracts, detail)
    flags = utilization_flags(contracts, detail)
    rm = rate_and_margin(detail)
    last = walk[-1]

    print("=" * w)
    print(f"USAGE-BASED REVENUE ENGINE  |  {len(contracts)} contracts  |  "
          f"license + metered usage + implementation")
    print("=" * w)
    print("ARR WALK  (run-rate; usage moves without a signature)")
    print("-" * w)
    print(f"  {'month':<9}{'beginning':>12}{'new':>10}{'usage exp':>11}"
          f"{'usage ctr':>11}{'churn':>10}{'ending':>12}")
    for r in walk[-8:]:
        print(f"  {r['month']:<9}{money(r['beginning']):>12}{money(r['new']):>10}"
              f"{money(r['usage_expansion']):>11}{money(-r['usage_contraction']):>11}"
              f"{money(-r['churned']):>10}{money(r['ending']):>12}")

    print(f"\nCOMMIT UTILIZATION -- the action list")
    print("-" * w)
    print(f"  under-committed (<65% for 3 months) -- downgrade risk at renewal:")
    for f in flags["under"][:6]:
        print(f"    {f['contract_id']}  {f['tier']:<11} {f['avg_utilization']:>5.0%} "
              f"utilized   {money(f['annual_commit_unused'])}/yr of commit unused")
    print(f"  over-committed (>130% for 3 months) -- upsell list, paying overage rates:")
    for f in flags["over"][:6]:
        print(f"    {f['contract_id']}  {f['tier']:<11} {f['avg_utilization']:>5.0%} "
              f"utilized   {money(f['annual_overage_run_rate'])}/yr overage run-rate")

    print(f"\nRATE & USAGE MARGIN")
    print("-" * w)
    print(f"  {'month':<9}{'tasks':>12}{'blended $/task':>15}{'inference $/task':>17}{'usage GM':>10}")
    for r in rm[-6:]:
        print(f"  {r['month']:<9}{r['tasks']:>12,.0f}{r['blended_rate']:>15.4f}"
              f"{r['inference_cost']:>17.4f}{r['usage_gm']:>10.1%}")
    first, lastr = rm[6], rm[-1]
    print(f"\n  blended rate {first['blended_rate']:.4f} -> {lastr['blended_rate']:.4f} "
          f"$/task ({lastr['blended_rate']/first['blended_rate']-1:+.0%}): growth with "
          f"rate compression as mix shifts to larger tiers.")
    print(f"  usage GM {first['usage_gm']:.0%} -> {lastr['usage_gm']:.0%}: inference "
          f"cost declines faster than realized rate.")
    print()


def validate(contracts, detail) -> None:
    print("VALIDATION")
    print("-" * 90)
    ok = True
    walk = arr_walk(contracts, detail)

    # 1. walk reconciles every month
    worst = max(abs(r["beginning"] + r["new"] + r["usage_expansion"]
                    - r["usage_contraction"] - r["churned"] - r["ending"])
                for r in walk)
    chain = all(abs(walk[i]["ending"] - walk[i + 1]["beginning"]) < 0.01
                for i in range(len(walk) - 1))
    ok &= worst < 0.01 and chain
    print(f"  [{'ok ' if worst < 0.01 and chain else 'MISS'}] ARR walk (incl. usage "
          f"expansion) reconciles and chains (max diff ${worst:.4f})")

    # 2. billing math on every contract-month, recomputed from the contract
    worst_b = 0.0
    for c in contracts:
        for d in (x for x in detail if x["contract_id"] == c["contract_id"]):
            billed, _, _ = usage_bill(d["actual_tasks"], c["committed_tasks_mo"],
                                      c["rate_per_task"])
            worst_b = max(worst_b, abs(billed - d["usage_billed"]))
    ok &= worst_b < 0.01
    print(f"  [{'ok ' if worst_b < 0.01 else 'MISS'}] usage billing = max(actual, "
          f"commit) + {OVERAGE_PREMIUM:.0%} overage premium on every "
          f"contract-month (max diff ${worst_b:.4f})")

    # 3. seeded flags surface
    flags = utilization_flags(contracts, detail)
    ok &= len(flags["under"]) >= 3 and len(flags["over"]) >= 3
    print(f"  [{'ok ' if len(flags['under']) >= 3 and len(flags['over']) >= 3 else 'MISS'}] "
          f"utilization panel surfaces {len(flags['under'])} under- and "
          f"{len(flags['over'])} over-committed contracts (>=3 each seeded)")

    # 4. rate compression is real and monotone-ish
    rm = rate_and_margin(detail)
    compressed = rm[-1]["blended_rate"] < rm[6]["blended_rate"] * 0.97
    ok &= compressed
    print(f"  [{'ok ' if compressed else 'MISS'}] blended realized rate compresses "
          f"({rm[6]['blended_rate']:.4f} -> {rm[-1]['blended_rate']:.4f} $/task)")

    print("-" * 90)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(contracts, detail, path: Path) -> None:
    walk = arr_walk(contracts, detail)
    flags = utilization_flags(contracts, detail)
    rm = rate_and_margin(detail)
    last = walk[-1]

    # stacked walk chart: monthly ending ARR line + stream mix table instead
    W, H, PL, PT, PB = 880, 290, 84, 22, 40
    pw, ph = W - PL - 24, H - PT - PB
    hi = max(r["ending"] for r in walk) * 1.08

    def x(i): return PL + pw * i / (len(walk) - 1)
    def y(v): return PT + ph * (1 - v / hi)

    arr_line = " ".join(f"{x(i):.1f},{y(r['ending']):.1f}" for i, r in enumerate(walk))
    grid = ""
    for fr in (0, .5, 1.0):
        v = hi * fr
        grid += (f'<line x1="{PL}" y1="{y(v):.1f}" x2="{W-24}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{PL-10}" y="{y(v)+4:.1f}" text-anchor="end" class="tick">${v/1e6:.1f}M</text>')
    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{H-16}" text-anchor="middle" class="tick">{walk[i]["month"]}</text>'
        for i in range(0, len(walk), 3))

    # rate + margin dual line
    hi_r = max(r["blended_rate"] for r in rm) * 1.15
    def yr(v): return PT + ph * (1 - v / hi_r)
    rate_line = " ".join(f"{x(r['mi']):.1f},{yr(r['blended_rate']):.1f}" for r in rm)
    cost_line = " ".join(f"{x(r['mi']):.1f},{yr(r['inference_cost']):.1f}" for r in rm)
    grid_r = ""
    for fr in (0, .5, 1.0):
        v = hi_r * fr
        grid_r += (f'<line x1="{PL}" y1="{yr(v):.1f}" x2="{W-24}" y2="{yr(v):.1f}" class="grid"/>'
                   f'<text x="{PL-10}" y="{yr(v)+4:.1f}" text-anchor="end" class="tick">${v:.3f}</text>')

    walk_rows = "".join(
        f"<tr><td>{r['month']}</td><td class='n'>${r['beginning']/1e6:,.2f}</td>"
        f"<td class='n pos'>+${r['new']/1e3:,.0f}K</td>"
        f"<td class='n pos'>+${r['usage_expansion']/1e3:,.0f}K</td>"
        f"<td class='n neg'>−${r['usage_contraction']/1e3:,.0f}K</td>"
        f"<td class='n neg'>−${r['churned']/1e3:,.0f}K</td>"
        f"<td class='n b'>${r['ending']/1e6:,.2f}</td></tr>"
        for r in walk[-9:])

    def flag_rows(items, val_key, val_label):
        return "".join(
            f"<tr><td class='mono'>{f['contract_id']}</td><td>{f['tier']}</td>"
            f"<td class='n'>{f['avg_utilization']:.0%}</td>"
            f"<td class='n'>${f[val_key]:,.0f}</td></tr>"
            for f in items[:6])

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Usage-Based Revenue Engine</title>
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
        color:var(--mut); margin:28px 0 10px; font-weight:600; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
           gap:12px; margin-top:22px; }}
  .kpi {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
          padding:13px 15px; }}
  .kpi .k {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
             color:var(--mut); }}
  .kpi .v {{ font-size:19px; font-weight:600; margin-top:3px;
             font-variant-numeric:tabular-nums; }}
  .kpi .n2 {{ font-size:11px; color:var(--mut); margin-top:1px; }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .leg {{ font-size:12px; font-weight:600; }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  @media (max-width:760px) {{ .cols {{ grid-template-columns:1fr; }} }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
  th,td {{ padding:6px 10px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .b {{ font-weight:600; }} .neg {{ color:var(--neg); }} .pos {{ color:var(--pos); }}
  .mono {{ font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Usage-Based Revenue Engine</h1>
  <div class="sub">Platform license + metered usage vs committed minimums +
    implementation · {len(contracts)} contracts · synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Run-rate ARR</div>
      <div class="v">${last['ending']/1e6:,.1f}M</div>
      <div class="n2">license + usage annualized</div></div>
    <div class="kpi"><div class="k">Usage expansion, LTM</div>
      <div class="v">${sum(r['usage_expansion'] for r in walk[-12:])/1e6:,.1f}M</div>
      <div class="n2">no signature required</div></div>
    <div class="kpi"><div class="k">Blended rate</div>
      <div class="v">${rm[-1]['blended_rate']:.3f}</div>
      <div class="n2">per task, {rm[-1]['blended_rate']/rm[6]['blended_rate']-1:+.0%} vs Jul-25</div></div>
    <div class="kpi"><div class="k">Usage gross margin</div>
      <div class="v">{rm[-1]['usage_gm']:.0%}</div>
      <div class="n2">from {rm[6]['usage_gm']:.0%}</div></div>
    <div class="kpi"><div class="k">Action list</div>
      <div class="v">{len(flags['under'])} + {len(flags['over'])}</div>
      <div class="n2">downgrade risks + upsell list</div></div>
  </div>

  <h2>Run-rate ARR</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid}
    <polyline points="{arr_line}" fill="none" stroke="var(--line)"
      stroke-width="2.5" stroke-linejoin="round"/>{ticks}</svg></div>

  <h2>ARR walk — usage moves without a signature</h2>
  <div class="tbl"><table>
    <thead><tr><th>Month</th><th class="n">Beginning $M</th><th class="n">New</th>
      <th class="n">Usage expansion</th><th class="n">Usage contraction</th>
      <th class="n">Churn</th><th class="n">Ending $M</th></tr></thead>
    <tbody>{walk_rows}</tbody></table></div>
  <div class="note">The two middle columns are the lines a subscription-only
    walk doesn't have. In a usage business they are frequently the largest
    movements on the page — revenue that arrived, or left, with no contract
    event to anchor it.</div>

  <h2>Commit utilization — the action list</h2>
  <div class="cols">
    <div>
      <div class="note" style="margin-bottom:6px">&lt;65% utilized, 3+ months —
        paying for capacity they don't use: <strong>downgrade risk at
        renewal</strong></div>
      <div class="tbl"><table>
        <thead><tr><th>Contract</th><th>Tier</th><th class="n">Utilization</th>
          <th class="n">Commit unused /yr</th></tr></thead>
        <tbody>{flag_rows(flags['under'], 'annual_commit_unused', '')}</tbody>
      </table></div>
    </div>
    <div>
      <div class="note" style="margin-bottom:6px">&gt;130% utilized, 3+ months —
        on overage rates: <strong>the upsell list</strong></div>
      <div class="tbl"><table>
        <thead><tr><th>Contract</th><th>Tier</th><th class="n">Utilization</th>
          <th class="n">Overage run-rate /yr</th></tr></thead>
        <tbody>{flag_rows(flags['over'], 'annual_overage_run_rate', '')}</tbody>
      </table></div>
    </div>
  </div>

  <h2>Realized rate vs inference cost — the AI margin story</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid_r}
    <polyline points="{rate_line}" fill="none" stroke="var(--line)" stroke-width="2.5"/>
    <polyline points="{cost_line}" fill="none" stroke="var(--neg)" stroke-width="2.5"/>
    {ticks}
    <text x="{PL}" y="14" class="leg"><tspan fill="var(--line)">● blended
    realized $/task</tspan>  <tspan fill="var(--neg)">● inference cost
    $/task</tspan></text></svg></div>
  <div class="note">Blended rate compresses as mix shifts to larger tiers with
    lower unit pricing — growth with rate compression, invisible in revenue
    totals. Margin expands anyway because inference cost falls faster. Whether
    that stays true is the single most important assumption in any AI-native
    P&amp;L.</div>

  <footer>Generated by engine.py · walk reconciles, billing math verified on
    every contract-month (run --validate) · all data synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Usage-based revenue engine")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    contracts = make_contracts()
    detail = build(contracts)
    with (DATA / "contracts.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(contracts[0].keys()))
        w.writeheader(); w.writerows(contracts)
    with (DATA / "contract_months.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        w.writeheader(); w.writerows(detail)

    print_report(contracts, detail)
    if args.validate:
        validate(contracts, detail)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(contracts, detail, args.html)


if __name__ == "__main__":
    main()
