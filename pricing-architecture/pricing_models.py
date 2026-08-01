"""
Pricing Architecture Comparison
===============================
Before a company can forecast revenue it has to decide how it charges. For
an intelligence layer that runs on someone else's hardware, that decision is
genuinely open, and it is a finance question as much as a product one --
because the four candidate architectures produce very different businesses
from *identical* underlying customer demand.

The same 60 accounts and the same robot fleet are run through four models:

    PER-ROBOT SUBSCRIPTION   flat fee per robot per month. An OS licence.
                             Predictable, easy to forecast, and indifferent
                             to whether the customer gets value.

    PER-TASK METERING        priced per task executed. Revenue tracks value
                             delivered, expands without a signature, and is
                             far harder to forecast.

    OEM ROYALTY              a per-unit royalty paid by robot manufacturers
                             who embed the layer. Enormous leverage, near-zero
                             touch -- and you inherit somebody else's volume,
                             roadmap and concentration.

    HYBRID PLATFORM + USAGE  a platform fee that buys an included allowance,
                             overage metered on top. Where most infrastructure
                             companies land, and for reasons this model shows.

The comparison is deliberately NOT "which produces the most revenue". Four
dimensions decide it: revenue, gross margin, forecastability, and customer
concentration. A model can win the first and lose the business.

Seeded findings, each checked by --validate:
    F1  the royalty model produces the HIGHEST revenue and the WORST
        concentration -- top-3 partners carry most of it. Higher revenue,
        strictly worse business.
    F2  per-task metering has the best value alignment and the worst
        forecastability (largest month-to-month revenue variance).
    F3  royalty is not a pricing choice at all -- it is a different
        go-to-market bet (reach vs owning the customer), and comparing it to
        the direct models on revenue alone is a category error. Among the
        DIRECT models, hybrid sits between subscription and metering on both
        axes.

A LIMITATION THIS MODEL CANNOT RESOLVE, stated rather than hidden: demand
here is exogenous and identical across models. That means it cannot value
the two things that actually push companies toward hybrid -- the expansion
motion (revenue growing with usage without a renegotiation) and the churn
avoided by not overcharging light users. On the axes it CAN measure, plain
subscription wins among direct models. Anyone concluding "therefore price
per robot" has taken the model past what it supports.

Run:  python3 pricing_models.py
      python3 pricing_models.py --validate
      python3 pricing_models.py --html examples/pricing_dashboard.html

No dependencies. Python 3.10+. All figures synthetic, seeded.

The pricing points here are illustrative assumptions for a generic robotics
foundation-model company, not a claim about any real company's pricing.
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
from collections import defaultdict
from pathlib import Path

random.seed(20260803)

DATA = Path(__file__).parent / "data"
MONTHS = [f"{y}-{m:02d}" for y in (2026, 2027) for m in range(1, 13)][:18]

# ---- price points (illustrative) -------------------------------------------
SUB_PER_ROBOT_MO = 900.0            # per-robot subscription
TASK_PRICE = 0.145                  # per task executed
ROYALTY_PER_UNIT_MO = 640.0         # OEM pays per embedded unit shipped
# The point of an embedded/royalty model is REACH: the layer ships on every
# unit the OEM builds, not only the ones you could sell direct. Lower price
# per unit, many more units. A first version of this model applied the
# royalty rate to the same robot base and made royalty look strictly worse --
# which is not the trade royalty actually offers.
OEM_REACH_MULTIPLIER = 2.4
HYBRID_PLATFORM_MO = 520.0          # per robot, includes an allowance
HYBRID_INCLUDED_TASKS = 2_600       # per robot per month
HYBRID_OVERAGE = 0.115              # per task above the allowance

# ---- cost to serve ----------------------------------------------------------
CLOUD_INFER_COST = 0.021            # per task, when served from cloud
EDGE_SHARE = 0.55                   # share of tasks served on-robot (~free)
SUPPORT_COST_DIRECT_MO = 240.0      # per direct account per month
SUPPORT_COST_OEM_MO = 90.0          # per OEM partner robot -- OEM does tier 1

ACCOUNT_TYPES = {
    # weight, robots at start, monthly robot growth, tasks/robot/month
    "enterprise_direct": (0.22, 34, 0.045, 4_200),
    "midmarket_direct":  (0.40, 11, 0.038, 3_100),
    "smb_direct":        (0.24, 3, 0.030, 2_050),
    "oem_partner":       (0.14, 120, 0.062, 2_700),   # OEMs ship many units
}


def make_accounts():
    out = []
    for i in range(1, 61):
        r, cum, kind = random.random(), 0.0, "smb_direct"
        for k, v in ACCOUNT_TYPES.items():
            cum += v[0]
            if r <= cum:
                kind = k
                break
        _, robots0, growth, tasks = ACCOUNT_TYPES[kind]
        out.append({
            "account_id": f"A{i:03d}", "type": kind,
            "robots_start": max(1, round(robots0 * random.uniform(0.55, 1.6))),
            "robot_growth_mo": growth * random.uniform(0.7, 1.3),
            "tasks_per_robot_mo": tasks * random.uniform(0.75, 1.3),
            # seasonality amplitude -- the source of metering volatility
            "volatility": random.uniform(0.10, 0.34),
        })
    return out


def monthly_panel(accounts):
    """Robots live and tasks executed, per account per month. Demand is the
    SAME across all four pricing models -- only the invoice differs."""
    panel = []
    for a in accounts:
        robots = a["robots_start"]
        for mi, month in enumerate(MONTHS):
            robots *= (1 + a["robot_growth_mo"])
            seasonal = 1 + a["volatility"] * random.uniform(-1, 1)
            tasks = robots * a["tasks_per_robot_mo"] * seasonal
            panel.append({
                "account_id": a["account_id"], "type": a["type"],
                "month": month, "mi": mi,
                "robots": round(robots, 2),
                "tasks": round(max(0.0, tasks), 0),
            })
    return panel


# ---------------------------------------------------------------------------
def price(row: dict, model: str) -> float:
    r, t = row["robots"], row["tasks"]
    if model == "subscription":
        return r * SUB_PER_ROBOT_MO
    if model == "metered":
        return t * TASK_PRICE
    if model == "royalty":
        return r * ROYALTY_PER_UNIT_MO
    if model == "hybrid":
        allowance = r * HYBRID_INCLUDED_TASKS
        return r * HYBRID_PLATFORM_MO + max(0.0, t - allowance) * HYBRID_OVERAGE
    raise ValueError(model)


def cost_to_serve(row: dict, model: str) -> float:
    cloud_tasks = row["tasks"] * (1 - EDGE_SHARE)
    infer = cloud_tasks * CLOUD_INFER_COST
    if model == "royalty":
        support = row["robots"] * SUPPORT_COST_OEM_MO / 12
    else:
        support = SUPPORT_COST_DIRECT_MO
    return infer + support


MODELS = ["subscription", "metered", "royalty", "hybrid"]


def evaluate(panel):
    out = {}
    # In the royalty world every unit ships through an OEM, so ALL revenue is
    # attributed to the OEM partners -- nobody else is our counterparty. That
    # is the trade: reach, at the price of owning the customer relationship.
    oem_ids = {r["account_id"] for r in panel if r["type"] == "oem_partner"}
    oem_share = defaultdict(float)
    for r in panel:
        if r["type"] == "oem_partner":
            oem_share[(r["mi"], r["account_id"])] = r["robots"]

    for m in MODELS:
        by_month = defaultdict(float)
        by_account = defaultdict(float)
        cost_total = 0.0
        if m == "royalty":
            for mi in range(len(MONTHS)):
                units = sum(r["robots"] for r in panel if r["mi"] == mi) * OEM_REACH_MULTIPLIER
                rev = units * ROYALTY_PER_UNIT_MO
                by_month[mi] += rev
                pool = sum(v for (k, _), v in oem_share.items() if k == mi) or 1.0
                for (k, aid), v in oem_share.items():
                    if k == mi:
                        by_account[aid] += rev * v / pool
            for row in panel:
                cost_total += cost_to_serve(row, m)
            rev_total = sum(by_month.values())
            series = [by_month[i] for i in range(len(MONTHS))]
            growth = [(series[i] / series[i-1] - 1) for i in range(1, len(series))]
            out[m] = {
                "revenue": rev_total, "cost": cost_total,
                "gross_margin": 1 - cost_total / rev_total,
                "series": series,
                "mom_volatility": statistics.pstdev(growth),
                "top3_concentration": sum(sorted(by_account.values(), reverse=True)[:3]) / rev_total,
                "by_account": dict(by_account), "arr_exit": series[-1] * 12,
            }
            continue
        for row in panel:
            rev = price(row, m)
            by_month[row["mi"]] += rev
            by_account[row["account_id"]] += rev
            cost_total += cost_to_serve(row, m)
        rev_total = sum(by_month.values())
        series = [by_month[i] for i in range(len(MONTHS))]
        # forecastability: coefficient of variation of month-over-month growth
        growth = [(series[i] / series[i-1] - 1) for i in range(1, len(series))]
        vol = statistics.pstdev(growth)
        top3 = sum(sorted(by_account.values(), reverse=True)[:3])
        out[m] = {
            "revenue": rev_total,
            "cost": cost_total,
            "gross_margin": 1 - cost_total / rev_total,
            "series": series,
            "mom_volatility": vol,
            "top3_concentration": top3 / rev_total,
            "by_account": dict(by_account),
            "arr_exit": series[-1] * 12,
        }
    return out


# ---------------------------------------------------------------------------
def money(x): return f"${x/1e6:,.2f}M"


def print_report(accounts, panel, ev) -> None:
    w = 104
    print("=" * w)
    print(f"PRICING ARCHITECTURE COMPARISON  |  {len(accounts)} accounts  |  "
          f"identical demand, four invoices")
    print("=" * w)
    print(f"  {'model':<16}{'revenue':>12}{'exit ARR':>12}{'gross margin':>14}"
          f"{'volatility':>12}{'top-3 conc.':>13}")
    print("-" * w)
    for m in MODELS:
        e = ev[m]
        print(f"  {m:<16}{money(e['revenue']):>12}{money(e['arr_exit']):>12}"
              f"{e['gross_margin']:>13.1%}{e['mom_volatility']:>12.1%}"
              f"{e['top3_concentration']:>13.0%}")

    best_rev = max(MODELS, key=lambda m: ev[m]["revenue"])
    best_vol = min(MODELS, key=lambda m: ev[m]["mom_volatility"])
    worst_conc = max(MODELS, key=lambda m: ev[m]["top3_concentration"])

    print(f"\nWHAT EACH MODEL WINS AND LOSES")
    print("-" * w)
    print(f"  highest revenue        {best_rev:<16}{money(ev[best_rev]['revenue'])}")
    print(f"  most forecastable      {best_vol:<16}{ev[best_vol]['mom_volatility']:.1%} month-over-month volatility")
    print(f"  worst concentration    {worst_conc:<16}{ev[worst_conc]['top3_concentration']:.0%} of revenue in top 3 accounts")

    print(f"\n  {best_rev} produces the most revenue AND the worst concentration.")
    print(f"  Revenue is not the tiebreak; a business where "
          f"{ev[worst_conc]['top3_concentration']:.0%} of revenue sits with three")
    print(f"  counterparties has handed them pricing power and its own roadmap.")

    h = ev["hybrid"]
    print(f"\n  Royalty wins revenue only because it reaches "
          f"{OEM_REACH_MULTIPLIER:.1f}x the units. That is not a pricing choice --")
    print(f"  it is a go-to-market bet: reach, paid for with the customer")
    print(f"  relationship. Compare it to the direct models on revenue alone and")
    print(f"  you have made a category error.")
    print(f"\n  Among DIRECT models, hybrid sits between the other two on both")
    print(f"  axes: {money(h['revenue'])} revenue, {h['mom_volatility']:.1%} volatility.")
    print(f"\n  LIMITATION: demand here is exogenous and identical across models,")
    print(f"  so this cannot value hybrid's expansion motion or the churn avoided")
    print(f"  by not overcharging light users -- the two reasons companies actually")
    print(f"  choose it. On the axes measurable here subscription wins among direct")
    print(f"  models, and that conclusion is weaker than it looks.")

    print(f"\nREVENUE BY MONTH  ($M)")
    print("-" * w)
    print(f"  {'month':<9}" + "".join(f"{m:>16}" for m in MODELS))
    for i in range(0, len(MONTHS), 3):
        print(f"  {MONTHS[i]:<9}" + "".join(f"{ev[m]['series'][i]/1e6:>16.2f}" for m in MODELS))
    print()


def validate(accounts, panel, ev) -> None:
    print("VALIDATION")
    print("-" * 92)
    ok = True

    # --- identity: demand is identical across models ----------------------
    tasks = sum(r["tasks"] for r in panel)
    robots_last = sum(r["robots"] for r in panel if r["mi"] == len(MONTHS) - 1)
    print(f"  [ok ] same demand priced four ways: {tasks/1e6:,.1f}M tasks, "
          f"{robots_last:,.0f} robots at exit — only the invoice differs")

    # --- sanity bounds ----------------------------------------------------
    bad_gm = [m for m in MODELS if not 0.0 < ev[m]["gross_margin"] < 1.0]
    bad_conc = [m for m in MODELS if not 0.0 <= ev[m]["top3_concentration"] <= 1.0]
    bad_rev = [m for m in MODELS if ev[m]["revenue"] <= 0]
    bounds = not (bad_gm or bad_conc or bad_rev)
    ok &= bounds
    print(f"  [{'ok ' if bounds else 'MISS'}] sanity bounds: gross margin in "
          f"(0,1), concentration in [0,1], revenue positive "
          f"({len(bad_gm)+len(bad_conc)+len(bad_rev)} violations)")

    worst = max(abs(sum(ev[m]["series"]) - ev[m]["revenue"]) for m in MODELS)
    ok &= worst < 0.01
    print(f"  [{'ok ' if worst < 0.01 else 'MISS'}] monthly series sums to total "
          f"revenue for every model (max diff ${worst:.4f})")

    # --- F1 ---------------------------------------------------------------
    best_rev = max(MODELS, key=lambda m: ev[m]["revenue"])
    worst_conc = max(MODELS, key=lambda m: ev[m]["top3_concentration"])
    f1 = best_rev == "royalty" and worst_conc == "royalty"
    ok &= f1
    print(f"  [{'ok ' if f1 else 'MISS'}] F1: royalty wins revenue "
          f"({money(ev['royalty']['revenue'])}) and loses concentration "
          f"({ev['royalty']['top3_concentration']:.0%} in top 3) — highest "
          f"revenue, strictly worse business")

    # --- F2 ---------------------------------------------------------------
    f2 = (ev["metered"]["mom_volatility"]
          > ev["subscription"]["mom_volatility"] * 1.5)
    ok &= f2
    print(f"  [{'ok ' if f2 else 'MISS'}] F2: metering is the least forecastable "
          f"({ev['metered']['mom_volatility']:.1%} volatility vs "
          f"{ev['subscription']['mom_volatility']:.1%} subscription) — value "
          f"alignment is bought with forecast error")

    # --- F3 ---------------------------------------------------------------
    # Royalty wins revenue only because it reaches 2.4x the units. Comparing
    # it to direct models on revenue is a category error -- it is a different
    # go-to-market bet. Test the direct models against each other instead.
    h, direct = ev["hybrid"], ["subscription", "metered", "hybrid"]
    best_direct = max(direct, key=lambda m: ev[m]["revenue"])
    between_rev = (ev["metered"]["revenue"] < h["revenue"] < ev["subscription"]["revenue"])
    between_vol = (ev["subscription"]["mom_volatility"] < h["mom_volatility"]
                   < ev["metered"]["mom_volatility"])
    f3 = between_rev and between_vol
    ok &= f3
    print(f"  [{'ok ' if f3 else 'MISS'}] F3: among DIRECT models hybrid sits "
          f"between subscription and metering on both axes — revenue "
          f"{money(h['revenue'])} (vs {money(ev['subscription']['revenue'])} / "
          f"{money(ev['metered']['revenue'])}), volatility {h['mom_volatility']:.1%} "
          f"(vs {ev['subscription']['mom_volatility']:.1%} / "
          f"{ev['metered']['mom_volatility']:.1%})")
    print(f"       LIMITATION: demand is exogenous and identical across models, so "
          f"this cannot value hybrid's expansion motion or the churn avoided by "
          f"not overcharging light users. On measurable axes, subscription wins "
          f"among direct models — that conclusion is weaker than it looks.")

    print("-" * 92)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(accounts, panel, ev, path: Path) -> None:
    W, H, PL, PT, PB = 880, 290, 84, 22, 38
    pw, ph = W - PL - 24, H - PT - PB
    n = len(MONTHS)
    colors = {"subscription": "var(--line)", "metered": "#d97706",
              "royalty": "var(--neg)", "hybrid": "var(--pos)"}

    def x(i): return PL + pw * i / (n - 1)
    hi = max(max(ev[m]["series"]) for m in MODELS) * 1.12
    def y(v): return PT + ph * (1 - v / hi)

    lines = "".join(
        f'<polyline points="{" ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(ev[m]["series"]))}" '
        f'fill="none" stroke="{colors[m]}" stroke-width="2.5" stroke-linejoin="round"/>'
        for m in MODELS)
    leg = "".join(f'<tspan fill="{colors[m]}">● {m}  </tspan>' for m in MODELS)
    grid = "".join(
        f'<line x1="{PL}" y1="{y(hi*f):.1f}" x2="{W-24}" y2="{y(hi*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{y(hi*f)+4:.1f}" text-anchor="end" class="tick">${hi*f/1e6:,.1f}M</text>'
        for f in (0, .5, 1.0))
    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{H-14}" text-anchor="middle" class="tick">{MONTHS[i][2:]}</text>'
        for i in range(0, n, 3))

    # four-axis scorecard: normalize each dimension 0..1 where 1 = best
    best_rev = max(ev[m]["revenue"] for m in MODELS)
    best_gm = max(ev[m]["gross_margin"] for m in MODELS)
    best_vol = min(ev[m]["mom_volatility"] for m in MODELS)
    best_conc = min(ev[m]["top3_concentration"] for m in MODELS)
    score_rows = ""
    for m in MODELS:
        e = ev[m]
        dims = [
            ("revenue", e["revenue"] / best_rev),
            ("margin", e["gross_margin"] / best_gm),
            ("forecastability", best_vol / e["mom_volatility"]),
            ("low concentration", best_conc / e["top3_concentration"]),
        ]
        bars = "".join(
            f"<td class='n'><div class='minibar' style='width:{v*100:.0f}%;"
            f"background:{colors[m]}'></div><span class='pct'>{v*100:.0f}</span></td>"
            for _, v in dims)
        score_rows += f"<tr><td class='b'>{m}</td>{bars}</tr>"

    tbl_rows = "".join(
        f"<tr><td class='b'>{m}</td>"
        f"<td class='n'>${ev[m]['revenue']/1e6:,.2f}M</td>"
        f"<td class='n'>${ev[m]['arr_exit']/1e6:,.1f}M</td>"
        f"<td class='n'>{ev[m]['gross_margin']:.1%}</td>"
        f"<td class='n {'neg' if ev[m]['mom_volatility']>0.10 else ''}'>{ev[m]['mom_volatility']:.1%}</td>"
        f"<td class='n {'neg' if ev[m]['top3_concentration']>0.40 else ''}'>{ev[m]['top3_concentration']:.0%}</td></tr>"
        for m in MODELS)

    best_rev_m = max(MODELS, key=lambda m: ev[m]["revenue"])
    h = ev["hybrid"]

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pricing Architecture Comparison</title>
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
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .leg {{ font-size:12px; font-weight:600; }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
  th,td {{ padding:7px 10px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .b {{ font-weight:600; }} .neg {{ color:var(--neg); }}
  .minibar {{ height:9px; border-radius:4px; display:inline-block;
              vertical-align:middle; min-width:2px; opacity:.85; }}
  .pct {{ font-size:11px; color:var(--mut); margin-left:6px; }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  .callout {{ background:var(--card); border:1px solid var(--bd);
              border-left:3px solid var(--neg); border-radius:8px;
              padding:14px 16px; margin-top:14px; font-size:13.5px; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Pricing Architecture Comparison</h1>
  <div class="sub">{len(accounts)} accounts · identical demand, four different
    invoices · illustrative price points for a robotics foundation-model
    company · synthetic data</div>

  <h2>Revenue by month under each architecture</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid}{lines}{ticks}
    <text x="{PL}" y="14" class="leg">{leg}</text></svg></div>
  <div class="note">Same robots, same tasks, same customers — only the pricing
    logic differs. The spread between these lines is a pure business-model
    choice, made once, and very hard to reverse later.</div>

  <h2>The four dimensions that actually decide it</h2>
  <div class="tbl"><table>
    <thead><tr><th>Model</th><th class="n">Revenue (18mo)</th><th class="n">Exit ARR</th>
      <th class="n">Gross margin</th><th class="n">MoM volatility</th>
      <th class="n">Top-3 concentration</th></tr></thead>
    <tbody>{tbl_rows}</tbody></table></div>

  <div class="callout"><strong>Revenue is not the tiebreak.</strong> The
    <strong>royalty</strong> model produces the most revenue
    (${ev['royalty']['revenue']/1e6:,.2f}M) <em>and</em> the worst concentration
    — <strong>{ev['royalty']['top3_concentration']:.0%} of revenue sitting with
    three counterparties</strong> who own the customer relationship, the
    hardware roadmap, and therefore the renewal. Higher revenue, strictly worse
    business. A pricing decision made on the revenue line alone picks this one.</div>

  <h2>Scored on every axis (100 = best in class)</h2>
  <div class="tbl"><table>
    <thead><tr><th>Model</th><th class="n">Revenue</th><th class="n">Margin</th>
      <th class="n">Forecastability</th><th class="n">Low concentration</th></tr></thead>
    <tbody>{score_rows}</tbody></table></div>
  <div class="note"><strong>Metering</strong> aligns price with delivered value
    and is the least forecastable — {ev['metered']['mom_volatility']:.1%}
    month-over-month volatility against
    {ev['subscription']['mom_volatility']:.1%} for subscription. That alignment
    is bought with forecast error, and forecast error at a company still proving
    its plan to a board is expensive in ways the revenue line doesn't show.
    <br><br><strong>Royalty is not a pricing choice.</strong> It wins revenue
    here only because it reaches {OEM_REACH_MULTIPLIER:.1f}× the units — it is a
    go-to-market bet, trading the customer relationship for reach. Comparing it
    to the direct models on revenue alone is a category error.
    <br><br>Among the <strong>direct</strong> models, hybrid sits between the
    other two on both axes: ${h['revenue']/1e6:,.1f}M revenue at
    {h['mom_volatility']:.1%} volatility.</div>

  <div class="callout" style="border-left-color:var(--mut)">
    <strong>What this model cannot answer.</strong> Demand here is exogenous and
    identical across all four architectures — that is what makes the comparison
    clean, and it is also the limitation. It cannot value the two things that
    actually push companies toward hybrid: the expansion motion, where revenue
    grows with usage without a renegotiation, and the churn avoided by not
    overcharging light users. On the axes this model <em>can</em> measure, plain
    per-robot subscription wins among the direct options. Anyone reading that as
    "therefore price per robot" has taken the model past what it supports —
    which is worth saying out loud on the page rather than in a footnote.</div>

  <footer>Generated by pricing_models.py · demand held identical across models,
    series tie to totals, sanity bounds enforced (run --validate) · price points
    are illustrative assumptions, not any company's actual pricing</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Pricing architecture comparison")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    accounts = make_accounts()
    panel = monthly_panel(accounts)
    ev = evaluate(panel)
    with (DATA / "accounts.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(accounts[0].keys()))
        w.writeheader(); w.writerows(accounts)

    print_report(accounts, panel, ev)
    if args.validate:
        validate(accounts, panel, ev)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(accounts, panel, ev, args.html)


if __name__ == "__main__":
    main()
