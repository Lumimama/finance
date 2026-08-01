"""
Robot Fleet Unit Economics
==========================
A per-robot P&L for a deployed fleet -- the analysis that separates physical
AI from software AI, because in robotics **a deployed robot is a capital
asset that has to earn back its own cost**.

Software has no equivalent of an idle robot. An unused SaaS seat costs the
vendor nothing; an unused robot has already consumed its hardware capex, is
depreciating on schedule, and is quietly destroying capital every month it
sits below its payback utilization. That single asymmetry drives everything
here:

    UTILIZATION      productive hours / available hours -- the master driver
    UPTIME           1 - downtime; distinct from utilization (a robot can be
                     up and idle, which is the expensive failure mode)
    CONTRIBUTION     revenue - direct opex (field service, connectivity,
                     edge compute) per robot-month
    PAYBACK          months until cumulative contribution repays hardware
                     capex. If payback > depreciation life, the unit never
                     pays for itself and the fleet is destroying capital.

Seeded findings, each proven surfaced by --validate:

    F1  a cohort of units whose payback period exceeds the 60-month
        depreciation life -- capital destruction hiding inside a fleet whose
        blended numbers look fine
    F2  field-service cost is concentrated in a small tail of problem units;
        the median robot is cheap to run and the mean is not
    F3  utilization ramps over roughly the first four months after
        deployment, so judging a unit on month one is judging the install,
        not the asset

Run:  python3 fleet.py
      python3 fleet.py --validate
      python3 fleet.py --html examples/fleet_dashboard.html

No dependencies. Python 3.10+. All data synthetic, seeded.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

random.seed(20260726)

DATA = Path(__file__).parent / "data"
MONTHS = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13)][:18]
MIDX = {m: i for i, m in enumerate(MONTHS)}

# Capex varies by hardware configuration. An earlier version used a single
# constant, which made the "capital at risk" column identical on every row --
# a column that cannot vary cannot inform.
CONFIGS = {
    "standard":        (0.55,  68_000),
    "extended_sensor": (0.28,  84_000),
    "heavy_payload":   (0.17, 112_000),
}
HARDWARE_CAPEX = 68_000          # baseline config, used for display defaults
DEPRECIATION_LIFE_MO = 60        # 5-year straight line
HOURS_AVAILABLE_MO = 22 * 16     # 22 working days x 2 shifts
DEPLOY_RAMP_MO = 4               # F3: utilization ramps over ~4 months

# Deployment archetypes: (weight, steady-state utilization, price per hour,
# service-cost multiplier). "low_util_site" is the seeded capital-destruction
# cohort -- units that were sold into sites that never had the volume.
# Hourly price has to sit BELOW fully-loaded human labor (~$22/hr in these
# settings) or the robot has no business case -- which is what makes fixed
# service cost, not price, the lever that decides whether a unit ever repays.
ARCHETYPES = {
    "high_throughput": (0.30, 0.78, 22.0, 1.0),
    "standard":        (0.44, 0.61, 21.0, 1.0),
    "seasonal":        (0.14, 0.48, 20.0, 1.2),
    "low_util_site":   (0.12, 0.22, 19.0, 1.4),   # F1
}

CUSTOMERS = ["Meridian Logistics", "Cascade Foods", "Halcyon Manufacturing",
             "Northwind Distribution", "Fairhaven Packaging", "Silverline Auto",
             "Orchard Cold Chain", "Kestrel Materials"]


def pick_config() -> tuple[str, int]:
    r, cum = random.random(), 0.0
    for k, (w, capex) in CONFIGS.items():
        cum += w
        if r <= cum:
            return k, capex
    return "standard", 68_000


def pick_archetype() -> str:
    r, cum = random.random(), 0.0
    for k, v in ARCHETYPES.items():
        cum += v[0]
        if r <= cum:
            return k
    return "standard"


# ---------------------------------------------------------------------------
def make_fleet():
    """Robots deployed over the window, plus a month-by-month telemetry panel."""
    robots, panel = [], []
    rid = 0
    for mi, month in enumerate(MONTHS[:-2]):          # deploy through month 15
        for _ in range(random.randint(6, 14)):
            rid += 1
            arch = pick_archetype()
            _, steady_util, price, svc_mult = ARCHETYPES[arch]
            config, capex = pick_config()
            r = {
                "robot_id": f"RB{rid:04d}",
                "customer": random.choice(CUSTOMERS),
                "archetype": arch,
                "config": config,
                "deployed_month": month,
                "deployed_idx": mi,
                "hardware_capex": capex,
                "price_per_hour": price,
            }
            robots.append(r)

            # F2: a small share of units are lemons -- persistent service cost.
            lemon = random.random() < 0.07
            for k, m2 in enumerate(MONTHS[mi:]):
                # F3: ramp to steady state over DEPLOY_RAMP_MO months
                ramp = min(1.0, (k + 1) / DEPLOY_RAMP_MO)
                util = steady_util * ramp * random.uniform(0.90, 1.10)
                util = max(0.0, min(util, 0.95))
                downtime = random.uniform(0.01, 0.05) * (2.6 if lemon else 1.0)
                downtime = min(downtime, 0.30)

                hours_avail = HOURS_AVAILABLE_MO * (1 - downtime)
                hours_used = hours_avail * util
                revenue = hours_used * price

                # direct opex per robot-month
                connectivity = 85.0
                edge_compute = hours_used * 0.42          # on-robot inference
                # Field service is the dominant fixed cost in deployed robotics
                # and the reason low-utilization units cannot be saved by price.
                field_service = (600.0 * svc_mult
                                 * (5.5 if lemon else 1.0)
                                 * random.uniform(0.7, 1.4))
                incidents = 1 if random.random() < (0.22 if lemon else 0.05) else 0

                panel.append({
                    "robot_id": r["robot_id"], "month": m2,
                    "months_since_deploy": k,
                    "hours_available": round(hours_avail, 1),
                    "hours_used": round(hours_used, 1),
                    "utilization": round(util, 4),
                    "uptime": round(1 - downtime, 4),
                    "revenue": round(revenue, 2),
                    "connectivity": connectivity,
                    "edge_compute": round(edge_compute, 2),
                    "field_service": round(field_service, 2),
                    "incidents": incidents,
                })
    return robots, panel


# ---------------------------------------------------------------------------
def contribution(p: dict) -> float:
    """Revenue less direct opex. Excludes depreciation -- payback is measured
    on cash contribution against capex, not on accounting profit."""
    return p["revenue"] - p["connectivity"] - p["edge_compute"] - p["field_service"]


def per_robot(robots, panel):
    """Robot-level P&L, payback period, and whether it clears its capex."""
    by_r = defaultdict(list)
    for p in panel:
        by_r[p["robot_id"]].append(p)

    out = []
    for r in robots:
        rows = sorted(by_r[r["robot_id"]], key=lambda x: x["months_since_deploy"])
        months_live = len(rows)
        rev = sum(x["revenue"] for x in rows)
        svc = sum(x["field_service"] for x in rows)
        contrib_total = sum(contribution(x) for x in rows)
        avg_contrib = contrib_total / months_live

        # observed payback: first month cumulative contribution >= capex
        cum, observed = 0.0, None
        for x in rows:
            cum += contribution(x)
            if observed is None and cum >= r["hardware_capex"]:
                observed = x["months_since_deploy"] + 1
        # projected payback at the steady-state run-rate (last 3 months),
        # used when the observation window is shorter than payback
        recent = rows[-3:] if len(rows) >= 3 else rows
        run_rate = sum(contribution(x) for x in recent) / len(recent)
        projected = (r["hardware_capex"] / run_rate) if run_rate > 0 else float("inf")

        steady = [x for x in rows if x["months_since_deploy"] >= DEPLOY_RAMP_MO]
        out.append({
            **r,
            "months_live": months_live,
            "revenue_total": rev,
            "field_service_total": svc,
            "contribution_total": contrib_total,
            "avg_contribution_mo": avg_contrib,
            "run_rate_contribution_mo": run_rate,
            "payback_observed_mo": observed,
            "payback_projected_mo": projected,
            "clears_capex": projected <= DEPRECIATION_LIFE_MO,
            "utilization_steady": (sum(x["utilization"] for x in steady) / len(steady)
                                   if steady else rows[-1]["utilization"]),
            "uptime_avg": sum(x["uptime"] for x in rows) / months_live,
            "incidents": sum(x["incidents"] for x in rows),
        })
    return out


def fleet_month(robots, panel):
    """Fleet-level monthly roll-up. Depreciation and deployed capital are
    summed from each unit's ACTUAL capex, not a fleet-average constant."""
    capex_of = {r["robot_id"]: r["hardware_capex"] for r in robots}
    capex_by_id = {}
    by_m = defaultdict(list)
    for p in panel:
        by_m[p["month"]].append(p)
    rows = []
    for m in MONTHS:
        rs = by_m.get(m, [])
        if not rs:
            continue
        active = len(rs)
        rows.append({
            "month": m, "active_robots": active,
            "hours_available": sum(x["hours_available"] for x in rs),
            "hours_used": sum(x["hours_used"] for x in rs),
            "utilization": sum(x["hours_used"] for x in rs) / sum(x["hours_available"] for x in rs),
            "uptime": sum(x["uptime"] for x in rs) / active,
            "revenue": sum(x["revenue"] for x in rs),
            "field_service": sum(x["field_service"] for x in rs),
            "contribution": sum(contribution(x) for x in rs),
            "depreciation": sum(capex_of[x["robot_id"]] for x in rs) / DEPRECIATION_LIFE_MO,
            "deployed_capital": sum(capex_of[x["robot_id"]] for x in rs),
        })
    for r in rows:
        r["ebitda_after_depr"] = r["contribution"] - r["depreciation"]
        r["revenue_per_robot"] = r["revenue"] / r["active_robots"]
        r["contribution_per_robot"] = r["contribution"] / r["active_robots"]
    return rows


def ramp_curve(panel):
    """F3: average utilization by months-since-deployment."""
    by_k = defaultdict(list)
    for p in panel:
        by_k[p["months_since_deploy"]].append(p["utilization"])
    return {k: sum(v) / len(v) for k, v in sorted(by_k.items()) if k <= 11}


# ---------------------------------------------------------------------------
def money(x): return f"${x:,.0f}"


def print_report(robots, panel) -> None:
    w = 104
    pr = per_robot(robots, panel)
    fm = fleet_month(robots, panel)
    last = fm[-1]

    print("=" * w)
    print(f"ROBOT FLEET UNIT ECONOMICS  |  {len(robots)} units deployed  |  "
          f"through {last['month']}")
    print("=" * w)
    print(f"  active robots               {last['active_robots']:>12,}")
    print(f"  deployed capital            {money(last['deployed_capital']):>12}")
    print(f"  fleet utilization           {last['utilization']:>11.1%}")
    print(f"  fleet uptime                {last['uptime']:>11.1%}")
    print(f"  revenue / robot / month     {money(last['revenue_per_robot']):>12}")
    print(f"  contribution / robot / mo   {money(last['contribution_per_robot']):>12}")
    print(f"  EBITDA after depreciation   {money(last['ebitda_after_depr']):>12}")

    fails = [r for r in pr if not r["clears_capex"]]
    print(f"\nPAYBACK  (hardware capex {money(HARDWARE_CAPEX)}, "
          f"depreciation life {DEPRECIATION_LIFE_MO}mo)")
    print("-" * w)
    med = sorted(r["payback_projected_mo"] for r in pr
                 if r["payback_projected_mo"] != float("inf"))
    print(f"  median projected payback    {med[len(med)//2]:>10.1f}mo")
    print(f"  units that never clear capex{len(fails):>12,}   "
          f"({len(fails)/len(pr):.0%} of fleet, "
          f"{money(sum(r['hardware_capex'] for r in fails))} of capital)")

    print(f"\n  worst units by projected payback:")
    worst = sorted(pr, key=lambda r: r["run_rate_contribution_mo"])[:6]
    for r in worst:
        print(f"    {r['robot_id']}  {r['customer']:<24}{r['archetype']:<17}"
              f"util {r['utilization_steady']:>5.0%}   "
              f"contrib ${r['run_rate_contribution_mo']:>7,.0f}/mo   "
              f"payback {pb_label(r)}")

    print(f"\nBY ARCHETYPE")
    print("-" * w)
    print(f"  {'archetype':<18}{'units':>7}{'util':>8}{'rev/mo':>11}"
          f"{'contrib/mo':>12}{'payback':>10}{'clears capex':>14}")
    for a in ARCHETYPES:
        g = [r for r in pr if r["archetype"] == a]
        if not g:
            continue
        pbs = [r["payback_projected_mo"] for r in g if r["payback_projected_mo"] != float("inf")]
        med = sorted(pbs)[len(pbs)//2] if pbs else float("inf")
        pb = f"{med:.0f}mo" if med <= DEPRECIATION_LIFE_MO else "never"
        clears = sum(1 for r in g if r["clears_capex"])
        print(f"  {a:<18}{len(g):>7}{sum(r['utilization_steady'] for r in g)/len(g):>8.0%}"
              f"{money(sum(r['revenue_total']/r['months_live'] for r in g)/len(g)):>11}"
              f"{money(sum(r['run_rate_contribution_mo'] for r in g)/len(g)):>12}"
              f"{pb:>10}{f'{clears}/{len(g)}':>14}")

    svc = sorted((r["field_service_total"] / r["months_live"] for r in pr))
    ratio = sorted((r["field_service_total"] / r["months_live"] * 12
                    / r["hardware_capex"]) for r in pr)
    top = sorted(pr, key=lambda r: -r["field_service_total"] / r["months_live"])
    top_share = (sum(r["field_service_total"] for r in top[:len(pr)//10])
                 / sum(r["field_service_total"] for r in pr))
    print(f"\nFIELD SERVICE CONCENTRATION")
    print("-" * w)
    print(f"  median unit  {money(svc[len(svc)//2])}/mo  "
          f"= {ratio[len(ratio)//2]:.1%} of its capex per year")
    print(f"  mean unit    {money(sum(svc)/len(svc))}/mo  "
          f"= {sum(ratio)/len(ratio):.1%} of capex per year")
    print(f"  benchmark: industrial equipment maintenance typically runs 5-15% of")
    print(f"  capital cost per year; high-duty-cycle mobile robots sit at the top")
    print(f"  of that band. The median here is inside it; the mean is above it,")
    print(f"  and the tail is what pushes it there.")
    print(f"  worst 10% of units carry {top_share:.0%} of total field-service cost")

    ramp = ramp_curve(panel)
    print(f"\nDEPLOYMENT RAMP  (utilization by months since install)")
    print("-" * w)
    print("  " + "".join(f"M{k:<6}" for k in list(ramp)[:8]))
    print("  " + "".join(f"{v:<7.0%}" for v in list(ramp.values())[:8]))
    print()


def validate(robots, panel) -> None:
    print("VALIDATION")
    print("-" * 92)
    ok = True
    pr = per_robot(robots, panel)
    fm = fleet_month(robots, panel)

    # --- identities -------------------------------------------------------
    panel_rev = sum(p["revenue"] for p in panel)
    fleet_rev = sum(r["revenue"] for r in fm)
    tie = abs(panel_rev - fleet_rev) < 0.01
    ok &= tie
    print(f"  [{'ok ' if tie else 'MISS'}] robot-level revenue rolls up to the fleet "
          f"monthly total (diff ${abs(panel_rev-fleet_rev):.4f})")

    worst = max(abs(r["contribution"] - (r["revenue"] - sum(
        p["connectivity"] + p["edge_compute"] + p["field_service"]
        for p in panel if p["month"] == r["month"]))) for r in fm)
    ok &= worst < 0.01
    print(f"  [{'ok ' if worst < 0.01 else 'MISS'}] contribution = revenue - direct "
          f"opex, every month (max diff ${worst:.4f})")

    # --- sanity bounds (the guardrail a pure identity check misses) -------
    bad_util = [p for p in panel if not 0.0 <= p["utilization"] <= 1.0]
    bad_up = [p for p in panel if not 0.0 <= p["uptime"] <= 1.0]
    bad_hours = [p for p in panel if p["hours_used"] > p["hours_available"] + 0.01]
    bounds_ok = not (bad_util or bad_up or bad_hours)
    ok &= bounds_ok
    print(f"  [{'ok ' if bounds_ok else 'MISS'}] sanity bounds: utilization and uptime "
          f"in [0,1], hours used <= available ({len(bad_util)+len(bad_up)+len(bad_hours)} violations)")

    # --- seeded findings --------------------------------------------------
    fails = [r for r in pr if not r["clears_capex"]]
    f1 = len(fails) >= 10 and all(r["archetype"] == "low_util_site"
                                  for r in sorted(fails, key=lambda r: r["utilization_steady"])[:5])
    ok &= f1
    print(f"  [{'ok ' if f1 else 'MISS'}] F1: {len(fails)} units never clear capex "
          f"({money(sum(r['hardware_capex'] for r in fails))} of capital), concentrated "
          f"in the low-utilization archetype")

    svc = sorted((r["field_service_total"] / r["months_live"] for r in pr))
    mean_, median_ = sum(svc) / len(svc), svc[len(svc) // 2]
    f2 = mean_ > median_ * 1.25
    ok &= f2
    print(f"  [{'ok ' if f2 else 'MISS'}] F2: field-service cost is tail-concentrated "
          f"(mean {money(mean_)} vs median {money(median_)}/mo, ratio {mean_/median_:.2f}x)")

    ramp = ramp_curve(panel)
    f3 = ramp[0] < ramp[DEPLOY_RAMP_MO] * 0.6
    ok &= f3
    print(f"  [{'ok ' if f3 else 'MISS'}] F3: utilization ramps after install "
          f"(M0 {ramp[0]:.0%} -> M{DEPLOY_RAMP_MO} {ramp[DEPLOY_RAMP_MO]:.0%})")

    print("-" * 92)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def pb_label(r: dict) -> str:
    """Payback display. Beyond the depreciation life the exact month count is
    noise -- payback = capex / contribution is hyperbolic near zero, so 251 mo
    and 683 mo both simply mean "never". Bin, don't rank."""
    v = r["payback_projected_mo"]
    if v == float("inf"):
        return "never — loses money"
    if v > DEPRECIATION_LIFE_MO:
        return f"never (~{v/12:.0f}y at run-rate)"
    return f"{v:.0f} mo"


def write_html(robots, panel, path: Path) -> None:
    pr = per_robot(robots, panel)
    fm = fleet_month(robots, panel)
    last = fm[-1]
    fails = [r for r in pr if not r["clears_capex"]]
    # MUTUALLY EXCLUSIVE buckets. An earlier version reported "25 low-util + 9
    # lemons" against a total of 33, which does not add up: 6 units are both,
    # and 5 are neither (adequate utilization and positive contribution, just
    # not enough of it to clear capex inside the depreciation life).
    lemons = [r for r in fails if r["run_rate_contribution_mo"] <= 0]
    lowutil = [r for r in fails
               if r["archetype"] == "low_util_site"
               and r["run_rate_contribution_mo"] > 0]
    both = [r for r in fails
            if r["archetype"] == "low_util_site"
            and r["run_rate_contribution_mo"] <= 0]
    lemons_only = [r for r in lemons if r not in both]
    marginal = [r for r in fails
                if r not in lowutil and r not in lemons and r not in both]
    ramp = ramp_curve(panel)

    W, H, PL, PT, PB = 880, 270, 84, 22, 38
    pw, ph = W - PL - 24, H - PT - PB
    n = len(fm)

    def x(i): return PL + pw * i / (n - 1)

    # utilization + active robots
    def yu(v): return PT + ph * (1 - v)
    util_line = " ".join(f"{x(i):.1f},{yu(r['utilization']):.1f}" for i, r in enumerate(fm))
    up_line = " ".join(f"{x(i):.1f},{yu(r['uptime']):.1f}" for i, r in enumerate(fm))
    grid_u = "".join(
        f'<line x1="{PL}" y1="{yu(f):.1f}" x2="{W-24}" y2="{yu(f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{yu(f)+4:.1f}" text-anchor="end" class="tick">{f:.0%}</text>'
        for f in (0, .5, 1.0))
    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{H-14}" text-anchor="middle" class="tick">{fm[i]["month"][2:]}</text>'
        for i in range(0, n, 3))

    # contribution vs depreciation per robot
    hi_c = max(max(r["contribution_per_robot"] for r in fm),
               HARDWARE_CAPEX / DEPRECIATION_LIFE_MO) * 1.25
    def yc(v): return PT + ph * (1 - v / hi_c)
    contrib_line = " ".join(f"{x(i):.1f},{yc(r['contribution_per_robot']):.1f}"
                            for i, r in enumerate(fm))
    depr = (sum(r["hardware_capex"] for r in pr) / len(pr)) / DEPRECIATION_LIFE_MO
    depr_line = (f'<line x1="{PL}" y1="{yc(depr):.1f}" x2="{W-24}" y2="{yc(depr):.1f}" '
                 f'class="trig"/><text x="{W-28}" y="{yc(depr)-7:.1f}" text-anchor="end" '
                 f'class="tick" fill="var(--neg)">avg depreciation ${depr:,.0f}/robot/mo</text>')
    grid_c = "".join(
        f'<line x1="{PL}" y1="{yc(hi_c*f):.1f}" x2="{W-24}" y2="{yc(hi_c*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{yc(hi_c*f)+4:.1f}" text-anchor="end" class="tick">${hi_c*f:,.0f}</text>'
        for f in (0, .5, 1.0))

    # ramp bars
    rk = list(ramp)[:9]
    bw = pw / len(rk) * 0.6
    ramp_bars = ""
    for i, k in enumerate(rk):
        bx = PL + pw * i / len(rk) + bw * 0.25
        v = ramp[k]
        ramp_bars += (f'<rect x="{bx:.1f}" y="{yu(v):.1f}" width="{bw:.1f}" '
                      f'height="{yu(0)-yu(v):.1f}" fill="var(--line)" opacity="0.85" rx="2"/>'
                      f'<text x="{bx+bw/2:.1f}" y="{yu(v)-6:.1f}" text-anchor="middle" '
                      f'class="tick">{v:.0%}</text>'
                      f'<text x="{bx+bw/2:.1f}" y="{H-14}" text-anchor="middle" '
                      f'class="tick">M{k}</text>')

    arch_rows = ""
    for a in ARCHETYPES:
        g = [r for r in pr if r["archetype"] == a]
        if not g:
            continue
        pbs = [r["payback_projected_mo"] for r in g if r["payback_projected_mo"] != float("inf")]
        med = sorted(pbs)[len(pbs)//2] if pbs else float("inf")
        pb = f"{med:.0f} mo" if med <= DEPRECIATION_LIFE_MO else "never"
        clears = sum(1 for r in g if r["clears_capex"])
        bad = clears < len(g) * 0.5
        arch_rows += (
            f"<tr><td>{a.replace('_',' ')}</td><td class='n'>{len(g)}</td>"
            f"<td class='n'>{sum(r['utilization_steady'] for r in g)/len(g):.0%}</td>"
            f"<td class='n'>${sum(r['run_rate_contribution_mo'] for r in g)/len(g):,.0f}</td>"
            f"<td class='n {'neg' if bad else ''}'>{pb}</td>"
            f"<td class='n {'neg' if bad else 'pos'}'>{clears}/{len(g)}</td></tr>")

    # Rank by monthly cash impact (most negative first). Sorting by projected
    # payback put every infinite-payback unit at the top, so the table showed
    # eight identical "never" rows and told the reader nothing.
    worst_rows = "".join(
        f"<tr><td class='mono'>{r['robot_id']}</td><td>{r['customer']}</td>"
        f"<td>{r['archetype'].replace('_',' ')}</td>"
        f"<td class='n'>{r['utilization_steady']:.0%}</td>"
        f"<td class='n {'neg' if r['run_rate_contribution_mo'] <= 0 else ''}'>"
        f"${r['run_rate_contribution_mo']:,.0f}</td>"
        f"<td class='n neg'>{pb_label(r)}</td>"
        f"<td>{r['config'].replace('_',' ')}</td>"
        f"<td class='n'>${r['hardware_capex']:,.0f}</td></tr>"
        for r in sorted(fails, key=lambda r: r["run_rate_contribution_mo"])[:10])

    svc = sorted((r["field_service_total"] / r["months_live"] for r in pr))
    mean_, median_ = sum(svc) / len(svc), svc[len(svc) // 2]
    ratios = sorted((r["field_service_total"] / r["months_live"] * 12
                     / r["hardware_capex"]) for r in pr)
    med_ratio = ratios[len(ratios) // 2]
    mean_ratio = sum(ratios) / len(ratios)
    top = sorted(pr, key=lambda r: -r["field_service_total"] / r["months_live"])
    top_share = (sum(r["field_service_total"] for r in top[:max(1, len(pr)//10)])
                 / sum(r["field_service_total"] for r in pr))

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Robot Fleet Unit Economics</title>
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
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
           gap:12px; margin-top:22px; }}
  .kpi {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
          padding:13px 15px; }}
  .kpi .k {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
             color:var(--mut); }}
  .kpi .v {{ font-size:19px; font-weight:600; margin-top:3px;
             font-variant-numeric:tabular-nums; }}
  .kpi .n2 {{ font-size:11px; color:var(--mut); margin-top:1px; }}
  .warn .v {{ color:var(--neg); }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .trig {{ stroke:var(--neg); stroke-width:1.5; stroke-dasharray:5 4; }}
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
  .neg {{ color:var(--neg); }} .pos {{ color:var(--pos); }}
  .mono {{ font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Robot Fleet Unit Economics</h1>
  <div class="sub">{len(robots)} deployed units · {last['month']} ·
    hardware capex ${min(c[1] for c in CONFIGS.values()):,}–${max(c[1] for c in CONFIGS.values()):,}
    by configuration · {DEPRECIATION_LIFE_MO}-month depreciation · synthetic
    data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Active robots</div>
      <div class="v">{last['active_robots']:,}</div>
      <div class="n2">${last['deployed_capital']/1e6:,.1f}M deployed capital</div></div>
    <div class="kpi"><div class="k">Fleet utilization</div>
      <div class="v">{last['utilization']:.0%}</div>
      <div class="n2">uptime {last['uptime']:.0%}</div></div>
    <div class="kpi"><div class="k">Revenue / robot / mo</div>
      <div class="v">${last['revenue_per_robot']:,.0f}</div></div>
    <div class="kpi"><div class="k">Contribution / robot / mo</div>
      <div class="v">${last['contribution_per_robot']:,.0f}</div>
      <div class="n2">vs ${depr:,.0f} avg depreciation</div></div>
    <div class="kpi warn"><div class="k">Units that never repay capex</div>
      <div class="v">{len(fails)}</div>
      <div class="n2">${sum(r['hardware_capex'] for r in fails)/1e6:,.1f}M of capital</div></div>
  </div>

  <h2>Fleet utilization and uptime</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid_u}
    <polyline points="{util_line}" fill="none" stroke="var(--line)" stroke-width="2.5"/>
    <polyline points="{up_line}" fill="none" stroke="var(--pos)" stroke-width="2"
      stroke-dasharray="4 3"/>{ticks}
    <text x="{PL}" y="14" class="leg"><tspan fill="var(--line)">● utilization</tspan>
    <tspan fill="var(--pos)"> ● uptime</tspan></text></svg></div>
  <div class="note">Utilization and uptime are different problems. A robot that
    is <em>up</em> but <em>idle</em> looks healthy on a maintenance dashboard and
    is the most expensive failure mode on this page — the capex is spent, the
    depreciation runs, and nothing is earned against it.</div>

  <h2>Contribution per robot vs the depreciation it has to clear</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid_c}{depr_line}
    <polyline points="{contrib_line}" fill="none" stroke="var(--line)" stroke-width="2.5"/>
    {ticks}</svg></div>
  <div class="note">The dashed line is the monthly depreciation each unit must
    out-earn to be worth owning. This is the chart a software P&amp;L has no
    equivalent for.</div>

  <h2>Payback by deployment archetype</h2>
  <div class="tbl"><table>
    <thead><tr><th>Archetype</th><th class="n">Units</th><th class="n">Steady util</th>
      <th class="n">Contribution / mo</th><th class="n">Median payback</th>
      <th class="n">Clears capex</th></tr></thead>
    <tbody>{arch_rows}</tbody></table></div>
  <div class="note">Blended fleet numbers look acceptable; the archetype split
    shows <strong>{len(fails)} units ({len(fails)/len(pr):.0%} of the fleet,
    ${sum(r['hardware_capex'] for r in fails)/1e6:,.1f}M of capital)</strong> that
    never repay their hardware inside the {DEPRECIATION_LIFE_MO}-month
    depreciation life. They divide into <em>four mutually exclusive</em> groups,
    and the fixes are different for each:
    <br><br>
    <strong>{len(lowutil)}</strong> low-utilization sites still earning positive
    contribution — the volume was never there; redeploy or recover the unit.
    <strong>{len(lemons_only)}</strong> reliability failures whose field-service
    cost exceeds revenue outright — worse than idle, because every month they
    run they lose money. <strong>{len(both)}</strong> are both at once, and are
    the first units to pull out. <strong>{len(marginal)}</strong> are adequately
    utilized and contribution-positive but simply not <em>enough</em> to clear
    capex in {DEPRECIATION_LIFE_MO} months — a pricing or capex-spec question,
    not an operations one.
    <br><br>
    {len(lowutil)} + {len(lemons_only)} + {len(both)} + {len(marginal)} =
    {len(lowutil)+len(lemons_only)+len(both)+len(marginal)}. In a software
    business none of these would be more than low-margin; here all four are
    capital destruction.</div>

  <h2>Worst 10 of {len(fails)} units, ranked by monthly cash contribution</h2>
  <div class="note" style="margin-bottom:8px">Payback beyond the
    {DEPRECIATION_LIFE_MO}-month depreciation life displays as
    <strong>never</strong> — the formula (capex ÷ monthly contribution) goes
    hyperbolic as contribution approaches zero, so "251 months" and "683
    months" differ enormously as numbers and not at all as decisions. The
    run-rate-years figure is kept only as context for how far under water the
    unit is.</div>
  <div class="tbl"><table>
    <thead><tr><th>Robot</th><th>Customer</th><th>Archetype</th>
      <th class="n">Steady util</th><th class="n">Contribution / mo</th>
      <th class="n">Projected payback</th><th>Config</th>
      <th class="n">Capex at risk</th></tr></thead>
    <tbody>{worst_rows}</tbody></table></div>

  <h2>Deployment ramp — utilization by months since install</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid_u}{ramp_bars}</svg></div>
  <div class="note">Utilization takes roughly {DEPLOY_RAMP_MO} months to reach
    steady state. Judging a unit in month one measures the quality of the
    install, not the economics of the asset — which is why payback here is
    projected off the trailing three-month run-rate rather than life-to-date
    average.</div>

  <h2>Field-service concentration</h2>
  <div class="note" style="margin-top:0">Median unit costs
    <strong>${median_:,.0f}/month</strong> to service —
    <strong>{med_ratio:.1%} of its own capex per year</strong>. The mean is
    <strong>${mean_:,.0f}/month ({mean_ratio:.1%} of capex)</strong>. For
    context, industrial-equipment maintenance typically runs 5–15% of capital
    cost annually and high-duty-cycle mobile robots sit at the top of that
    band, so the median here is inside the range and the mean is above it.
    <br><br>The worst 10% of units carry <strong>{top_share:.0%}</strong> of all
    field-service cost. Budgeting from the mean over-provisions the healthy
    fleet and still under-provisions the tail — the actionable unit is the
    problem robot, not the average robot, which is also why a dollar figure
    alone is not enough to judge this line.</div>

  <footer>Generated by fleet.py · roll-ups tie, sanity bounds enforced, seeded
    findings verified (run --validate) · all data synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Robot fleet unit economics")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    robots, panel = make_fleet()
    with (DATA / "robots.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(robots[0].keys()))
        w.writeheader(); w.writerows(robots)
    with (DATA / "telemetry_monthly.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(panel[0].keys()))
        w.writeheader(); w.writerows(panel)

    print_report(robots, panel)
    if args.validate:
        validate(robots, panel)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(robots, panel, args.html)


if __name__ == "__main__":
    main()
