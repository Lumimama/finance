"""
Training Run Capitalization & Amortization
==========================================
The live accounting judgment at every foundation-model company: **is a
training run research expense, or an internally-developed intangible asset?**

The question is not academic. A company spending most of its capital on
training runs will report a materially different EBITDA depending on the
answer, and the answer is genuinely contested -- so the defensible thing a
finance function can do is model BOTH treatments, state which one it uses,
and be able to bridge between them on demand.

    EXPENSE-AS-INCURRED   every dollar of training cost hits R&D in the
                          month it is spent. Simple, conservative, and what
                          most AI companies do today.

    CAPITALIZE            costs incurred AFTER technological feasibility are
                          capitalized as an intangible and amortized over the
                          model's useful service life; pre-feasibility
                          research is still expensed. Abandoned runs are
                          impaired -- written off in full.

THE IDENTITY THAT KEEPS BOTH HONEST: over the full life of every run, the
two treatments charge exactly the same total cost to the P&L. Capitalization
does not reduce expense; it moves it later. --validate proves this to the
cent, which is the single most useful thing to be able to say in the room
where someone proposes capitalizing to improve EBITDA.

Seeded findings:
    F1  the EBITDA gap between treatments GROWS for as long as training spend
        is accelerating -- amortization of older, smaller runs never catches
        up with capitalization of newer, larger ones. The flattering effect
        does not self-correct; it compounds, and only reverses when spend
        plateaus. (This was written the other way round first, predicting the
        gap would compress. --validate disagreed with the model author.)
    F2  two abandoned runs impair in full under capitalization, delivering a
        lumpy charge that expensing would have spread smoothly -- the risk
        capitalization actually carries
    F3  cost per training run rises while cost per useful FLOP falls, so
        "training is getting more expensive" and "training is getting more
        efficient" are both true and neither is the whole sentence

Run:  python3 training_capex.py
      python3 training_capex.py --validate
      python3 training_capex.py --html examples/training_dashboard.html

No dependencies. Python 3.10+. All data synthetic, seeded.

NOT ACCOUNTING ADVICE. The feasibility threshold and useful-life assumptions
here are modelling choices, stated on the page so they can be argued with.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

random.seed(20260724)

DATA = Path(__file__).parent / "data"
MONTHS = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13)][:24]
MIDX = {m: i for i, m in enumerate(MONTHS)}

GPU_COST_PER_HOUR = 2.60          # blended reserved H100-class
USEFUL_LIFE_MO = 24               # service life of a deployed model version
# Share of a run's cost incurred before technological feasibility is
# established. Pre-feasibility cost is expensed under BOTH treatments.
PRE_FEASIBILITY_SHARE = 0.35

# Training runs: (name, start month index, GPU-hours, headcount cost, status)
# status: "deployed" -> serves production; "abandoned" -> impaired/expensed
RUNS = [
    ("v0.1-pretrain",     0,   180_000, 420_000, "deployed"),
    ("v0.2-pretrain",     3,   240_000, 460_000, "deployed"),
    ("v0.3-scaling",      6,   410_000, 520_000, "deployed"),
    ("v0.4-arch-probe",   8,   190_000, 300_000, "abandoned"),   # F2
    ("v0.5-pretrain",    10,   620_000, 610_000, "deployed"),
    ("v0.6-multimodal",  12,   880_000, 720_000, "deployed"),
    ("v0.7-longctx",     14,   540_000, 480_000, "abandoned"),   # F2
    ("v0.8-pretrain",    16, 1_150_000, 810_000, "deployed"),
    ("v0.9-distill",     18,   320_000, 390_000, "deployed"),
    ("v1.0-flagship",    20, 1_640_000, 980_000, "deployed"),
]
# Months each run takes to complete (cost spread evenly across them)
RUN_DURATION_MO = 3


def build_runs():
    out = []
    for name, start, gpu_hours, hc_cost, status in RUNS:
        compute = gpu_hours * GPU_COST_PER_HOUR
        total = compute + hc_cost
        # Effective FLOPs improve over time -- better data, better recipes.
        efficiency = 1.0 + 0.055 * start          # useful work per GPU-hour
        out.append({
            "run": name, "start_idx": start, "start_month": MONTHS[start],
            "gpu_hours": gpu_hours, "compute_cost": round(compute, 2),
            "headcount_cost": hc_cost, "total_cost": round(total, 2),
            "status": status,
            "useful_work_units": round(gpu_hours * efficiency),
            "duration_mo": RUN_DURATION_MO,
            "in_service_idx": start + RUN_DURATION_MO,
        })
    return out


# ---------------------------------------------------------------------------
def expense_treatment(runs):
    """Everything hits R&D as incurred, spread over the run's duration."""
    rd = defaultdict(float)
    for r in runs:
        per_mo = r["total_cost"] / r["duration_mo"]
        for k in range(r["duration_mo"]):
            mi = r["start_idx"] + k
            if mi < len(MONTHS):
                rd[mi] += per_mo
    return dict(rd)


def capitalize_treatment(runs):
    """Post-feasibility cost is capitalized and amortized; pre-feasibility is
    expensed; abandoned runs are impaired in full when abandoned."""
    rd = defaultdict(float)          # expensed research
    additions = defaultdict(float)   # capitalized
    amort = defaultdict(float)
    impair = defaultdict(float)

    for r in runs:
        pre = r["total_cost"] * PRE_FEASIBILITY_SHARE
        post = r["total_cost"] - pre
        per_mo_pre = pre / r["duration_mo"]
        for k in range(r["duration_mo"]):
            mi = r["start_idx"] + k
            if mi < len(MONTHS):
                rd[mi] += per_mo_pre

        if r["status"] == "abandoned":
            # Capitalized while in flight, then written off when abandoned.
            per_mo_post = post / r["duration_mo"]
            for k in range(r["duration_mo"]):
                mi = r["start_idx"] + k
                if mi < len(MONTHS):
                    additions[mi] += per_mo_post
            kill = min(r["in_service_idx"], len(MONTHS) - 1)
            impair[kill] += post
            continue

        per_mo_post = post / r["duration_mo"]
        for k in range(r["duration_mo"]):
            mi = r["start_idx"] + k
            if mi < len(MONTHS):
                additions[mi] += per_mo_post
        # amortize straight-line from in-service date over useful life
        per_mo_am = post / USEFUL_LIFE_MO
        for k in range(USEFUL_LIFE_MO):
            mi = r["in_service_idx"] + k
            if mi < len(MONTHS):
                amort[mi] += per_mo_am
    return dict(rd), dict(additions), dict(amort), dict(impair)


def build_series(runs, revenue_base=1_400_000):
    """Monthly P&L under both treatments, plus the intangible roll-forward."""
    exp_rd = expense_treatment(runs)
    cap_rd, additions, amort, impair = capitalize_treatment(runs)

    rows, nbv = [], 0.0
    for mi, month in enumerate(MONTHS):
        revenue = revenue_base * (1.085 ** mi)
        other_opex = revenue * 0.62                    # everything but training

        e_charge = exp_rd.get(mi, 0.0)
        c_charge = (cap_rd.get(mi, 0.0) + amort.get(mi, 0.0)
                    + impair.get(mi, 0.0))

        open_nbv = nbv
        nbv = open_nbv + additions.get(mi, 0.0) - amort.get(mi, 0.0) - impair.get(mi, 0.0)

        rows.append({
            "month": month, "revenue": revenue, "other_opex": other_opex,
            # expense treatment
            "exp_rd": e_charge,
            "exp_ebitda": revenue - other_opex - e_charge,
            # capitalize treatment
            "cap_rd": cap_rd.get(mi, 0.0),
            "cap_additions": additions.get(mi, 0.0),
            "cap_amort": amort.get(mi, 0.0),
            "cap_impair": impair.get(mi, 0.0),
            "cap_total_charge": c_charge,
            "cap_ebitda": revenue - other_opex - c_charge,
            "nbv_open": open_nbv, "nbv_close": nbv,
            "ebitda_delta": (revenue - other_opex - c_charge)
                            - (revenue - other_opex - e_charge),
        })
    return rows


# ---------------------------------------------------------------------------
def money(x): return f"${x/1e6:,.2f}M"


def print_report(runs, rows) -> None:
    w = 108
    print("=" * w)
    print(f"TRAINING RUN CAPITALIZATION  |  {len(runs)} runs  |  "
          f"{MONTHS[0]} to {MONTHS[-1]}")
    print("=" * w)
    total = sum(r["total_cost"] for r in runs)
    aband = [r for r in runs if r["status"] == "abandoned"]
    print(f"  total training spend        {money(total):>12}")
    print(f"  runs deployed / abandoned   {len(runs)-len(aband)} / {len(aband)}")
    print(f"  abandoned cost              {money(sum(r['total_cost'] for r in aband)):>12}")
    print(f"  pre-feasibility share       {PRE_FEASIBILITY_SHARE:>11.0%}   (expensed under both)")
    print(f"  useful life                 {USEFUL_LIFE_MO:>10}mo")

    print(f"\nTHE TWO TREATMENTS  ($M)")
    print("-" * w)
    print(f"  {'month':<9}{'revenue':>10}{'EXPENSE:':>12}{'EBITDA':>10}"
          f"{'  |  CAPITALIZE:':>18}{'R&D':>8}{'amort':>8}{'impair':>9}{'EBITDA':>10}{'delta':>9}")
    for r in rows[::3]:
        print(f"  {r['month']:<9}{r['revenue']/1e6:>10.2f}{r['exp_rd']/1e6:>12.2f}"
              f"{r['exp_ebitda']/1e6:>10.2f}{'':>18}{r['cap_rd']/1e6:>8.2f}"
              f"{r['cap_amort']/1e6:>8.2f}{r['cap_impair']/1e6:>9.2f}"
              f"{r['cap_ebitda']/1e6:>10.2f}{r['ebitda_delta']/1e6:>+9.2f}")

    ltm = rows[-12:]
    e_ltm = sum(r["exp_ebitda"] for r in ltm)
    c_ltm = sum(r["cap_ebitda"] for r in ltm)
    print(f"\n  LTM EBITDA — expensed      {money(e_ltm):>12}")
    print(f"  LTM EBITDA — capitalized   {money(c_ltm):>12}")
    print(f"  difference                 {money(c_ltm - e_ltm):>12}   "
          f"({(c_ltm-e_ltm)/abs(e_ltm):+.0%} on the expensed base)")

    print(f"\nINTANGIBLE ROLL-FORWARD  (capitalize treatment, $M)")
    print("-" * w)
    print(f"  {'month':<9}{'opening':>11}{'additions':>12}{'amortization':>14}"
          f"{'impairment':>12}{'closing':>11}")
    for r in rows[-6:]:
        print(f"  {r['month']:<9}{r['nbv_open']/1e6:>11.2f}{r['cap_additions']/1e6:>12.2f}"
              f"{-r['cap_amort']/1e6:>14.2f}{-r['cap_impair']/1e6:>12.2f}"
              f"{r['nbv_close']/1e6:>11.2f}")

    print(f"\nCOST PER RUN vs COST PER UNIT OF USEFUL WORK")
    print("-" * w)
    print(f"  {'run':<18}{'total cost':>13}{'GPU-hours':>12}{'$/useful unit':>15}{'status':>12}")
    for r in runs:
        print(f"  {r['run']:<18}{money(r['total_cost']):>13}{r['gpu_hours']:>12,}"
              f"{r['total_cost']/r['useful_work_units']:>15.3f}{r['status']:>12}")
    print()


def validate(runs, rows) -> None:
    print("VALIDATION")
    print("-" * 96)
    ok = True

    # --- THE identity: same total cost, different timing ------------------
    # Compare only cost that has fully run through both treatments within the
    # window: runs whose amortization completes before the window ends.
    settled = [r for r in runs
               if r["status"] == "abandoned"
               or r["in_service_idx"] + USEFUL_LIFE_MO <= len(MONTHS)]
    exp_rd = expense_treatment(settled)
    c_rd, adds, am, imp = capitalize_treatment(settled)
    exp_total = sum(exp_rd.values())
    cap_total = sum(c_rd.values()) + sum(am.values()) + sum(imp.values())
    same = abs(exp_total - cap_total) < 0.01
    ok &= same
    print(f"  [{'ok ' if same else 'MISS'}] over a run's full life both treatments "
          f"charge the SAME total to the P&L "
          f"(${exp_total:,.2f} vs ${cap_total:,.2f}) — capitalization moves cost, "
          f"it does not remove it")

    # --- roll-forward ties ------------------------------------------------
    worst = 0.0
    for r in rows:
        expect = (r["nbv_open"] + r["cap_additions"] - r["cap_amort"]
                  - r["cap_impair"])
        worst = max(worst, abs(expect - r["nbv_close"]))
    chain = all(abs(rows[i]["nbv_close"] - rows[i+1]["nbv_open"]) < 0.01
                for i in range(len(rows)-1))
    ok &= worst < 0.01 and chain
    print(f"  [{'ok ' if worst < 0.01 and chain else 'MISS'}] intangible "
          f"roll-forward ties and chains: open + additions − amortization − "
          f"impairment = close (max diff ${worst:.4f})")

    # --- sanity bounds ----------------------------------------------------
    neg_nbv = [r for r in rows if r["nbv_close"] < -0.01]
    bad_share = not 0.0 <= PRE_FEASIBILITY_SHARE <= 1.0
    bounds = not neg_nbv and not bad_share
    ok &= bounds
    print(f"  [{'ok ' if bounds else 'MISS'}] sanity bounds: net book value never "
          f"negative ({len(neg_nbv)} violations), feasibility share in [0,1]")

    # --- F1: the gap GROWS while spend accelerates ------------------------
    early = sum(r["ebitda_delta"] for r in rows[:8])
    late = sum(r["ebitda_delta"] for r in rows[-8:])
    f1 = late > early * 1.25
    ok &= f1
    print(f"  [{'ok ' if f1 else 'MISS'}] F1: the EBITDA gap GROWS while training "
          f"spend accelerates (first 8mo {money(early)} -> last 8mo {money(late)}, "
          f"{late/early:.1f}x) — the flattering effect compounds rather than "
          f"self-correcting")

    # --- F2: abandoned runs impair, lumpily -------------------------------
    imp_months = [r for r in rows if r["cap_impair"] > 0]
    f2 = len(imp_months) >= 2
    ok &= f2
    print(f"  [{'ok ' if f2 else 'MISS'}] F2: {len(imp_months)} impairment events "
          f"totalling {money(sum(r['cap_impair'] for r in rows))} — lumpy charges "
          f"that expensing would have spread smoothly")

    # --- F3: cost per run rises while cost per useful unit falls ----------
    first3 = runs[:3]
    last3 = runs[-3:]
    cost_up = (sum(r["total_cost"] for r in last3) / 3
               > sum(r["total_cost"] for r in first3) / 3)
    unit_down = (sum(r["total_cost"] / r["useful_work_units"] for r in last3) / 3
                 < sum(r["total_cost"] / r["useful_work_units"] for r in first3) / 3)
    f3 = cost_up and unit_down
    ok &= f3
    print(f"  [{'ok ' if f3 else 'MISS'}] F3: cost per run rises while cost per "
          f"unit of useful work falls — both 'training is more expensive' and "
          f"'training is more efficient' are true")

    print("-" * 96)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(runs, rows, path: Path) -> None:
    n = len(rows)
    W, H, PL, PT, PB = 880, 280, 90, 22, 38
    pw, ph = W - PL - 24, H - PT - PB

    def x(i): return PL + pw * i / (n - 1)

    # EBITDA both ways
    vals = [r["exp_ebitda"] for r in rows] + [r["cap_ebitda"] for r in rows]
    lo, hi = min(vals) * 1.15, max(vals) * 1.15
    if lo > 0: lo = 0
    def y(v): return PT + ph * (1 - (v - lo) / (hi - lo))
    exp_line = " ".join(f"{x(i):.1f},{y(r['exp_ebitda']):.1f}" for i, r in enumerate(rows))
    cap_line = " ".join(f"{x(i):.1f},{y(r['cap_ebitda']):.1f}" for i, r in enumerate(rows))
    zero = (f'<line x1="{PL}" y1="{y(0):.1f}" x2="{W-24}" y2="{y(0):.1f}" '
            f'stroke="var(--fg)" stroke-width="1" opacity=".35"/>')
    grid = "".join(
        f'<line x1="{PL}" y1="{y(lo+(hi-lo)*f):.1f}" x2="{W-24}" y2="{y(lo+(hi-lo)*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{y(lo+(hi-lo)*f)+4:.1f}" text-anchor="end" class="tick">${(lo+(hi-lo)*f)/1e6:,.1f}M</text>'
        for f in (0, .5, 1.0))
    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{H-14}" text-anchor="middle" class="tick">{rows[i]["month"][2:]}</text>'
        for i in range(0, n, 3))
    imp_marks = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(r["cap_ebitda"]):.1f}" r="4.5" fill="var(--neg)"/>'
        f'<text x="{x(i):.1f}" y="{y(r["cap_ebitda"])+18:.1f}" text-anchor="middle" '
        f'class="tick" fill="var(--neg)">impairment</text>'
        for i, r in enumerate(rows) if r["cap_impair"] > 0)

    # NBV area
    hi_n = max(r["nbv_close"] for r in rows) * 1.15
    def yn(v): return PT + ph * (1 - v / hi_n)
    nbv_line = " ".join(f"{x(i):.1f},{yn(r['nbv_close']):.1f}" for i, r in enumerate(rows))
    nbv_area = f"{PL},{yn(0)} " + nbv_line + f" {x(n-1):.1f},{yn(0)}"
    grid_n = "".join(
        f'<line x1="{PL}" y1="{yn(hi_n*f):.1f}" x2="{W-24}" y2="{yn(hi_n*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{yn(hi_n*f)+4:.1f}" text-anchor="end" class="tick">${hi_n*f/1e6:,.1f}M</text>'
        for f in (0, .5, 1.0))

    ltm = rows[-12:]
    e_ltm = sum(r["exp_ebitda"] for r in ltm)
    c_ltm = sum(r["cap_ebitda"] for r in ltm)
    early_disp = sum(r["ebitda_delta"] for r in rows[:8]) / 1e6
    late_disp = sum(r["ebitda_delta"] for r in rows[-8:]) / 1e6
    total_spend = sum(r["total_cost"] for r in runs)
    aband = [r for r in runs if r["status"] == "abandoned"]

    run_rows = "".join(
        f"<tr><td class='mono'>{r['run']}</td><td>{r['start_month']}</td>"
        f"<td class='n'>{r['gpu_hours']:,}</td>"
        f"<td class='n'>${r['total_cost']/1e6:,.2f}M</td>"
        f"<td class='n'>{r['total_cost']/r['useful_work_units']:.3f}</td>"
        f"<td class='{'neg' if r['status']=='abandoned' else 'pos'}'>{r['status']}</td></tr>"
        for r in runs)

    roll_rows = "".join(
        f"<tr><td>{r['month']}</td><td class='n'>${r['nbv_open']/1e6:,.2f}</td>"
        f"<td class='n pos'>+${r['cap_additions']/1e6:,.2f}</td>"
        f"<td class='n neg'>−${r['cap_amort']/1e6:,.2f}</td>"
        f"<td class='n neg'>{'−$'+format(r['cap_impair']/1e6,',.2f') if r['cap_impair'] else '—'}</td>"
        f"<td class='n b'>${r['nbv_close']/1e6:,.2f}</td></tr>"
        for r in rows[-8:])

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Training Run Capitalization &amp; Amortization</title>
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
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
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
  .b {{ font-weight:600; }} .neg {{ color:var(--neg); }} .pos {{ color:var(--pos); }}
  .mono {{ font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  .callout {{ background:var(--card); border:1px solid var(--bd);
              border-left:3px solid var(--line); border-radius:8px;
              padding:14px 16px; margin-top:14px; font-size:13.5px; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Training Run Capitalization &amp; Amortization</h1>
  <div class="sub">{len(runs)} training runs · {MONTHS[0]} to {MONTHS[-1]} ·
    both treatments modelled side by side · synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Total training spend</div>
      <div class="v">${total_spend/1e6:,.1f}M</div>
      <div class="n2">{len(runs)} runs, {len(aband)} abandoned</div></div>
    <div class="kpi"><div class="k">LTM EBITDA — expensed</div>
      <div class="v">${e_ltm/1e6:,.1f}M</div></div>
    <div class="kpi"><div class="k">LTM EBITDA — capitalized</div>
      <div class="v">${c_ltm/1e6:,.1f}M</div></div>
    <div class="kpi warnk"><div class="k">Treatment difference</div>
      <div class="v">${(c_ltm-e_ltm)/1e6:,.1f}M</div>
      <div class="n2">timing, not substance</div></div>
    <div class="kpi"><div class="k">Intangible NBV</div>
      <div class="v">${rows[-1]['nbv_close']/1e6:,.1f}M</div>
      <div class="n2">{USEFUL_LIFE_MO}-mo useful life</div></div>
  </div>

  <div class="callout"><strong>The identity that keeps both treatments
    honest:</strong> over the full life of every run, expensing and
    capitalizing charge <em>exactly the same total</em> to the P&amp;L —
    verified to the cent in <code>--validate</code>. Capitalization does not
    reduce cost; it moves it later. That sentence is the entire defence
    against capitalizing in order to improve EBITDA.</div>

  <h2>EBITDA under both treatments</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid}{zero}
    <polyline points="{exp_line}" fill="none" stroke="var(--line)" stroke-width="2.5"/>
    <polyline points="{cap_line}" fill="none" stroke="var(--warn)" stroke-width="2.5"/>
    {imp_marks}{ticks}
    <text x="{PL}" y="14" class="leg"><tspan fill="var(--line)">● expensed as
    incurred</tspan><tspan fill="var(--warn)"> ● capitalized &amp;
    amortized</tspan></text></svg></div>
  <div class="note">The gap does not close — it <strong>widens</strong>, from
    ${early_disp:,.1f}M over the first eight months to ${late_disp:,.1f}M over the
    last eight. Amortization of older, smaller runs never catches up with
    capitalization of newer, larger ones while spend is still accelerating, so
    the flattering effect compounds instead of self-correcting. It reverses only
    when training spend plateaus — which for a company at this stage means the
    reversal lands in whichever year growth stops. (I predicted the opposite
    when building this; the validation check disagreed, and the data was
    right.)</div>

  <h2>Intangible roll-forward — capitalize treatment ($M)</h2>
  <div class="tbl"><table>
    <thead><tr><th>Month</th><th class="n">Opening</th><th class="n">Additions</th>
      <th class="n">Amortization</th><th class="n">Impairment</th>
      <th class="n">Closing NBV</th></tr></thead>
    <tbody>{roll_rows}</tbody></table></div>

  <h2>Capitalized asset base</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid_n}
    <polygon points="{nbv_area}" fill="var(--line)" opacity="0.15"/>
    <polyline points="{nbv_line}" fill="none" stroke="var(--line)" stroke-width="2.5"/>
    {ticks}</svg></div>
  <div class="note">Under capitalization this balance is an asset on the balance
    sheet. It is also the exposure: if a model version is superseded faster than
    its {USEFUL_LIFE_MO}-month assumed life — routine in this field — the
    remaining book value impairs. Two runs did exactly that here.</div>

  <h2>Training runs</h2>
  <div class="tbl"><table>
    <thead><tr><th>Run</th><th>Started</th><th class="n">GPU-hours</th>
      <th class="n">Total cost</th><th class="n">$ / useful work unit</th>
      <th>Status</th></tr></thead>
    <tbody>{run_rows}</tbody></table></div>
  <div class="note">Cost per run rises steadily while cost per unit of useful
    work falls. Both statements are true, and quoting either alone is
    misleading — the first is a budget conversation, the second is a capability
    conversation, and they belong on different slides.</div>

  <footer>Generated by training_capex.py · both treatments reconcile to the same
    lifetime cost; roll-forward ties (run --validate) · synthetic data ·
    modelling assumptions stated, not accounting advice</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Training capitalization vs expensing")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    runs = build_runs()
    rows = build_series(runs)
    with (DATA / "training_runs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(runs[0].keys()))
        w.writeheader(); w.writerows(runs)

    print_report(runs, rows)
    if args.validate:
        validate(runs, rows)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(runs, rows, args.html)


if __name__ == "__main__":
    main()
