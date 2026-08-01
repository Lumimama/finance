"""
Pilot-to-Production Funnel
==========================
Robotics does not have a sales funnel; it has a **pilot** funnel, and that
difference is the reason so many robotics companies with good technology have
bad financials.

A SaaS trial costs the vendor a seat. A robotics pilot costs hardware on
loan, a solutions engineer on site, integration into someone else's safety
and workflow systems, and months of calendar time -- real, capitalized-ish
money spent before a single dollar of revenue, on an outcome that is far from
certain. The finance questions follow from that:

    TRUE CAC          cost of ALL pilots divided by pilots WON. The naive
                      version -- cost of won pilots only -- ignores the ones
                      you paid for and lost, and understates acquisition cost
                      by a multiple, not a margin.
    PILOT PURGATORY   pilots that neither convert nor die. They consume
                      engineering capacity indefinitely and convert at close
                      to zero once past a certain age. Naming the age at
                      which to stop is a finance decision, not a sales one.
    CAPITAL AT RISK   hardware sitting at prospect sites, on the balance
                      sheet, earning nothing.

Seeded findings, each proven surfaced by --validate:

    F1  conversion collapses for pilots older than ~9 months -- purgatory is
        real and datable, so there is a defensible kill rule
    F2  pilots with a named executive sponsor AND written success criteria
        convert far better; the ones without are where the money goes
    F3  true CAC (all pilot cost / wins) is several times the naive figure

Run:  python3 pilots.py
      python3 pilots.py --validate
      python3 pilots.py --html examples/pilots_dashboard.html

No dependencies. Python 3.10+. All data synthetic, seeded.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

random.seed(20260723)

DATA = Path(__file__).parent / "data"
MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025, 2026) for m in range(1, 13)][:30]
MIDX = {m: i for i, m in enumerate(MONTHS)}
AS_OF = len(MONTHS) - 1

PURGATORY_MONTHS = 9          # F1: the age past which conversion collapses
HARDWARE_ON_LOAN = 68_000     # per pilot, same unit as the fleet model
SE_COST_PER_MONTH = 14_500    # solutions engineer time on a pilot
INTEGRATION_COST = 22_000     # one-time: safety, workflow, IT integration

INDUSTRIES = ["logistics", "food_bev", "manufacturing", "cold_chain", "automotive"]
COMPANIES = ["Meridian", "Cascade", "Halcyon", "Northwind", "Fairhaven",
             "Silverline", "Orchard", "Kestrel", "Brightpath", "Tidewater",
             "Junction", "Vantage", "Pinewood", "Redshift", "Copperfield",
             "Blue Harbor", "Ninth Street", "Maple", "Ridgeline", "Foxglove"]


def make_pilots():
    out, n = [], 0
    for mi in range(0, AS_OF - 1):
        for _ in range(random.randint(2, 5)):
            n += 1
            # F2: qualification quality is the dominant conversion driver
            sponsor = random.random() < 0.55
            criteria = random.random() < 0.60
            qualified = sponsor and criteria

            base_p = 0.62 if qualified else 0.17
            # Expected duration: qualified pilots move faster
            dur = (random.randint(3, 7) if qualified
                   else random.randint(5, 14))

            robots = random.choice([1, 1, 2, 2, 3])
            out.append({
                "pilot_id": f"P{n:04d}",
                "company": f"{random.choice(COMPANIES)} {random.choice(['Group','Industries','Co','Partners'])}",
                "industry": random.choice(INDUSTRIES),
                "start_month": MONTHS[mi], "start_idx": mi,
                "exec_sponsor": int(sponsor),
                "written_success_criteria": int(criteria),
                "robots_on_loan": robots,
                "_p": base_p, "_dur": dur,
            })

    # Resolve outcomes
    for p in out:
        age = AS_OF - p["start_idx"]
        dur = p["_dur"]
        if age < dur:
            # still running, not yet at its decision point
            p["status"] = "open"
            p["months_elapsed"] = age
            p["decided_idx"] = None
        else:
            # F1: conversion probability decays hard past purgatory threshold
            decay = 1.0 if dur <= PURGATORY_MONTHS else 0.12
            p_conv = p["_p"] * decay
            if random.random() < p_conv:
                p["status"] = "converted"
            elif random.random() < 0.82:
                p["status"] = "lost"
            else:
                p["status"] = "open"          # the purgatory population
            p["months_elapsed"] = age if p["status"] == "open" else dur
            p["decided_idx"] = (p["start_idx"] + dur
                                if p["status"] != "open" else None)

        # A stalled pilot does not consume a full solutions engineer forever.
        # Full rate through the expected duration, then a maintenance rate --
        # modelling it at full rate produced a true CAC that described a
        # company already out of business.
        months = p["months_elapsed"]
        active = min(months, dur)
        stalled = max(0, months - dur)
        p["se_cost"] = round(SE_COST_PER_MONTH * (active + stalled * 0.25), 2)
        p["integration_cost"] = INTEGRATION_COST
        p["total_pilot_cost"] = round(p["se_cost"] + INTEGRATION_COST, 2)
        p["hardware_at_risk"] = (p["robots_on_loan"] * HARDWARE_ON_LOAN
                                 if p["status"] == "open" else 0)
        # Won pilots convert to a deployment contract
        p["contract_acv"] = (round(p["robots_on_loan"] * random.uniform(78_000, 132_000), 2)
                             if p["status"] == "converted" else 0.0)
        for k in ("_p", "_dur"):
            p.pop(k)
    return out


# ---------------------------------------------------------------------------
def funnel(pilots):
    conv = [p for p in pilots if p["status"] == "converted"]
    lost = [p for p in pilots if p["status"] == "lost"]
    open_ = [p for p in pilots if p["status"] == "open"]
    total_cost = sum(p["total_pilot_cost"] for p in pilots)
    won_cost = sum(p["total_pilot_cost"] for p in conv)
    return {
        "total": len(pilots), "converted": len(conv), "lost": len(lost),
        "open": len(open_),
        "conversion_rate": len(conv) / max(1, len(conv) + len(lost)),
        "total_pilot_cost": total_cost,
        "won_pilot_cost": won_cost,
        "naive_cac": won_cost / max(1, len(conv)),
        "true_cac": total_cost / max(1, len(conv)),
        "acv_won": sum(p["contract_acv"] for p in conv),
        "hardware_at_risk": sum(p["hardware_at_risk"] for p in pilots),
        "median_time_to_prod": sorted(p["months_elapsed"] for p in conv)[len(conv)//2] if conv else 0,
        "conv_list": conv, "lost_list": lost, "open_list": open_,
    }


def by_age_band(pilots):
    """F1: conversion rate by how long the pilot ran."""
    bands = [(0, 3), (4, 6), (7, 9), (10, 12), (13, 99)]
    out = []
    for lo, hi in bands:
        g = [p for p in pilots if lo <= p["months_elapsed"] <= hi
             and p["status"] in ("converted", "lost")]
        stuck = [p for p in pilots if lo <= p["months_elapsed"] <= hi
                 and p["status"] == "open"]
        conv = sum(1 for p in g if p["status"] == "converted")
        out.append({
            "band": f"{lo}-{hi}mo" if hi < 99 else f"{lo}mo+",
            "decided": len(g), "converted": conv,
            "rate": conv / len(g) if g else 0.0,
            "still_open": len(stuck),
            "open_cost": sum(p["total_pilot_cost"] for p in stuck),
        })
    return out


def by_qualification(pilots):
    """F2: does qualification quality predict conversion?"""
    out = []
    for label, fn in [
        ("sponsor + criteria", lambda p: p["exec_sponsor"] and p["written_success_criteria"]),
        ("sponsor only", lambda p: p["exec_sponsor"] and not p["written_success_criteria"]),
        ("criteria only", lambda p: not p["exec_sponsor"] and p["written_success_criteria"]),
        ("neither", lambda p: not p["exec_sponsor"] and not p["written_success_criteria"]),
    ]:
        g = [p for p in pilots if fn(p)]
        d = [p for p in g if p["status"] in ("converted", "lost")]
        c = [p for p in g if p["status"] == "converted"]
        out.append({
            "label": label, "pilots": len(g), "decided": len(d),
            "converted": len(c),
            "rate": len(c) / len(d) if d else 0.0,
            "cost": sum(p["total_pilot_cost"] for p in g),
            "acv": sum(p["contract_acv"] for p in g),
        })
    return out


# ---------------------------------------------------------------------------
def money(x): return f"${x:,.0f}"


def print_report(pilots) -> None:
    w = 104
    f = funnel(pilots)
    print("=" * w)
    print(f"PILOT-TO-PRODUCTION FUNNEL  |  {f['total']} pilots  |  through {MONTHS[AS_OF]}")
    print("=" * w)
    print(f"  pilots started              {f['total']:>12}")
    print(f"  converted                   {f['converted']:>12}   "
          f"({f['conversion_rate']:.0%} of decided)")
    print(f"  lost                        {f['lost']:>12}")
    print(f"  still open                  {f['open']:>12}")
    print(f"  median time to production   {f['median_time_to_prod']:>10}mo")
    print(f"  ACV won                     {money(f['acv_won']):>12}")

    print(f"\nTHE CAC THAT MATTERS")
    print("-" * w)
    print(f"  naive CAC (won pilots only) {money(f['naive_cac']):>12}")
    print(f"  TRUE CAC (all pilot cost)   {money(f['true_cac']):>12}   "
          f"{f['true_cac']/f['naive_cac']:.1f}x the naive figure")
    print(f"  total spent on pilots       {money(f['total_pilot_cost']):>12}")
    print(f"  of which on pilots not won  {money(f['total_pilot_cost']-f['won_pilot_cost']):>12}")
    avg_acv = f["acv_won"] / max(1, f["converted"])
    payback = f["true_cac"] / avg_acv * 12
    tcv_3yr = avg_acv * 3
    print(f"  average ACV won             {money(avg_acv):>12}")
    print(f"  months of first-year ACV to repay true CAC {payback:>10.1f}mo")
    print(f"  true CAC as % of 3-year TCV {f['true_cac']/tcv_3yr:>11.0%}   "
          f"<- pilot economics only work on multi-year terms")

    # Counterfactual: what if the qualification gate had been enforced?
    q = [p_ for p_ in pilots if p_["exec_sponsor"] and p_["written_success_criteria"]]
    qf = funnel(q)
    q_tcv = (qf["acv_won"] / max(1, qf["converted"])) * 3
    print(f"\n  COUNTERFACTUAL -- qualified pilots only (sponsor + written criteria):")
    print(f"    pilots run                {len(q):>12}   vs {f['total']} actual")
    print(f"    true CAC                  {money(qf['true_cac']):>12}   "
          f"vs {money(f['true_cac'])} actual")
    print(f"    CAC as % of 3-year TCV    {qf['true_cac']/q_tcv:>11.0%}   "
          f"vs {f['true_cac']/tcv_3yr:.0%} actual")
    print(f"    -> the unqualified pilots are not underperforming; they are the")
    print(f"       entire reason the acquisition motion does not pay for itself.")

    print(f"\nF1  CONVERSION BY PILOT AGE  (the purgatory line)")
    print("-" * w)
    print(f"  {'age band':<12}{'decided':>9}{'converted':>11}{'rate':>8}"
          f"{'still open':>12}{'cost of open':>15}")
    for b in by_age_band(pilots):
        flag = "  <- purgatory" if b["band"] in ("10-12mo", "13mo+") else ""
        print(f"  {b['band']:<12}{b['decided']:>9}{b['converted']:>11}{b['rate']:>8.0%}"
              f"{b['still_open']:>12}{money(b['open_cost']):>15}{flag}")

    print(f"\nF2  CONVERSION BY QUALIFICATION")
    print("-" * w)
    print(f"  {'qualification':<22}{'pilots':>8}{'decided':>9}{'rate':>8}"
          f"{'cost':>14}{'ACV won':>14}")
    for q in by_qualification(pilots):
        print(f"  {q['label']:<22}{q['pilots']:>8}{q['decided']:>9}{q['rate']:>8.0%}"
              f"{money(q['cost']):>14}{money(q['acv']):>14}")

    stuck = sorted((p for p in f["open_list"] if p["months_elapsed"] > PURGATORY_MONTHS),
                   key=lambda p: -p["total_pilot_cost"])
    print(f"\nPILOT PURGATORY  ({len(stuck)} pilots open longer than {PURGATORY_MONTHS} months)")
    print("-" * w)
    print(f"  sunk cost                   {money(sum(p['total_pilot_cost'] for p in stuck)):>12}")
    print(f"  hardware still on site      {money(sum(p['hardware_at_risk'] for p in stuck)):>12}")
    for p in stuck[:6]:
        print(f"    {p['pilot_id']}  {p['company']:<26}{p['industry']:<15}"
              f"{p['months_elapsed']:>3}mo   {money(p['total_pilot_cost']):>9}")
    print()


def validate(pilots) -> None:
    print("VALIDATION")
    print("-" * 92)
    ok = True
    f = funnel(pilots)

    # --- identities -------------------------------------------------------
    ties = f["converted"] + f["lost"] + f["open"] == f["total"]
    ok &= ties
    print(f"  [{'ok ' if ties else 'MISS'}] funnel ties: converted + lost + open "
          f"= pilots started ({f['converted']}+{f['lost']}+{f['open']}="
          f"{f['total']})")

    worst = max(abs(p["total_pilot_cost"] - p["se_cost"] - p["integration_cost"])
                for p in pilots)
    ok &= worst < 0.01
    print(f"  [{'ok ' if worst < 0.01 else 'MISS'}] pilot cost = SE time + "
          f"integration, every pilot (max diff ${worst:.4f})")

    # --- sanity bounds ----------------------------------------------------
    bad_rate = not 0.0 <= f["conversion_rate"] <= 1.0
    bad_months = [p for p in pilots if p["months_elapsed"] < 0]
    bad_acv = [p for p in pilots if p["status"] != "converted" and p["contract_acv"] > 0]
    bounds = not (bad_rate or bad_months or bad_acv)
    ok &= bounds
    print(f"  [{'ok ' if bounds else 'MISS'}] sanity bounds: conversion rate in "
          f"[0,1], no negative durations, ACV only on converted pilots "
          f"({len(bad_months)+len(bad_acv)} violations)")

    # --- F1 ---------------------------------------------------------------
    bands = {b["band"]: b for b in by_age_band(pilots)}
    early = bands["4-6mo"]["rate"]
    late = bands["10-12mo"]["rate"]
    f1 = early > 0 and late < early * 0.5
    ok &= f1
    print(f"  [{'ok ' if f1 else 'MISS'}] F1: conversion collapses past "
          f"{PURGATORY_MONTHS} months (4-6mo {early:.0%} -> 10-12mo {late:.0%}) "
          f"— purgatory is datable, so a kill rule is defensible")

    # --- F2 ---------------------------------------------------------------
    q = {x["label"]: x for x in by_qualification(pilots)}
    f2 = q["sponsor + criteria"]["rate"] > q["neither"]["rate"] * 2
    ok &= f2
    print(f"  [{'ok ' if f2 else 'MISS'}] F2: qualified pilots convert "
          f"{q['sponsor + criteria']['rate']:.0%} vs {q['neither']['rate']:.0%} "
          f"unqualified ({q['sponsor + criteria']['rate']/max(q['neither']['rate'],1e-9):.1f}x)")

    # --- F3 ---------------------------------------------------------------
    f3 = f["true_cac"] > f["naive_cac"] * 2
    ok &= f3
    print(f"  [{'ok ' if f3 else 'MISS'}] F3: true CAC {money(f['true_cac'])} is "
          f"{f['true_cac']/f['naive_cac']:.1f}x the naive "
          f"{money(f['naive_cac'])} — the lost pilots are the acquisition cost")

    print("-" * 92)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(pilots, path: Path) -> None:
    f = funnel(pilots)
    bands = by_age_band(pilots)
    quals = by_qualification(pilots)
    stuck = sorted((p for p in f["open_list"] if p["months_elapsed"] > PURGATORY_MONTHS),
                   key=lambda p: -p["total_pilot_cost"])

    W, H, PL, PT, PB = 880, 260, 84, 22, 42
    pw, ph = W - PL - 24, H - PT - PB

    # F1 bars: conversion rate by age band
    def yb(v): return PT + ph * (1 - v)
    bw = pw / len(bands) * 0.5
    bars = ""
    for i, b in enumerate(bands):
        bx = PL + pw * (i + 0.25) / len(bands)
        purg = b["band"] in ("10-12mo", "13mo+")
        bars += (f'<rect x="{bx:.1f}" y="{yb(b["rate"]):.1f}" width="{bw:.1f}" '
                 f'height="{yb(0)-yb(b["rate"]):.1f}" '
                 f'fill="{"var(--neg)" if purg else "var(--line)"}" rx="2" opacity="0.88"/>'
                 f'<text x="{bx+bw/2:.1f}" y="{yb(b["rate"])-7:.1f}" text-anchor="middle" '
                 f'class="tick">{b["rate"]:.0%}</text>'
                 f'<text x="{bx+bw/2:.1f}" y="{H-24}" text-anchor="middle" class="tick">{b["band"]}</text>'
                 f'<text x="{bx+bw/2:.1f}" y="{H-10}" text-anchor="middle" class="tick">'
                 f'n={b["decided"]}</text>')
    grid = "".join(
        f'<line x1="{PL}" y1="{yb(v):.1f}" x2="{W-24}" y2="{yb(v):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{yb(v)+4:.1f}" text-anchor="end" class="tick">{v:.0%}</text>'
        for v in (0, .25, .5))
    purg_line = (f'<line x1="{PL + pw*3/len(bands):.1f}" y1="{PT}" '
                 f'x2="{PL + pw*3/len(bands):.1f}" y2="{H-PB}" class="trig"/>'
                 f'<text x="{PL + pw*3/len(bands)+6:.1f}" y="{PT+12}" class="tick" '
                 f'fill="var(--neg)">{PURGATORY_MONTHS}-month purgatory line</text>')

    # funnel bar
    stages = [("Pilots started", f["total"]), ("Decided", f["converted"]+f["lost"]),
              ("Converted", f["converted"])]
    fw = pw
    fun = ""
    for i, (label, v) in enumerate(stages):
        width = fw * v / stages[0][1]
        fy = PT + i * 46
        fun += (f'<rect x="{PL}" y="{fy}" width="{width:.1f}" height="34" '
                f'fill="var(--line)" opacity="{0.9 - i*0.2:.2f}" rx="3"/>'
                f'<text x="{PL+10}" y="{fy+22}" class="fl">{label}: {v}</text>')

    qual_rows = "".join(
        f"<tr><td>{q['label']}</td><td class='n'>{q['pilots']}</td>"
        f"<td class='n'>{q['decided']}</td>"
        f"<td class='n {'pos' if q['rate']>0.4 else 'neg' if q['rate']<0.2 else ''}'>{q['rate']:.0%}</td>"
        f"<td class='n'>${q['cost']/1e6:,.2f}M</td>"
        f"<td class='n'>${q['acv']/1e6:,.2f}M</td></tr>"
        for q in quals)

    stuck_rows = "".join(
        f"<tr><td class='mono'>{p['pilot_id']}</td><td>{p['company']}</td>"
        f"<td>{p['industry'].replace('_',' ')}</td>"
        f"<td class='n neg'>{p['months_elapsed']} mo</td>"
        f"<td class='n'>${p['total_pilot_cost']:,.0f}</td>"
        f"<td class='n'>${p['hardware_at_risk']:,.0f}</td></tr>"
        for p in stuck[:10])

    avg_acv = f["acv_won"] / max(1, f["converted"])
    payback = f["true_cac"] / avg_acv * 12
    tcv_3yr = avg_acv * 3
    qp = [x for x in pilots if x["exec_sponsor"] and x["written_success_criteria"]]
    qf = funnel(qp)
    q_tcv = (qf["acv_won"] / max(1, qf["converted"])) * 3
    q_ratio = qf["true_cac"] / q_tcv if q_tcv else 0

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pilot-to-Production Funnel</title>
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
  .warn .v {{ color:var(--neg); }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .trig {{ stroke:var(--neg); stroke-width:1.5; stroke-dasharray:5 4; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .fl {{ fill:#fff; font-size:13px; font-weight:600; }}
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
  .callout {{ background:var(--card); border:1px solid var(--bd);
              border-left:3px solid var(--neg); border-radius:8px;
              padding:14px 16px; margin-top:14px; font-size:13.5px; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Pilot-to-Production Funnel</h1>
  <div class="sub">{f['total']} pilots · through {MONTHS[AS_OF]} ·
    ${HARDWARE_ON_LOAN:,} of hardware per unit on loan · synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Pilots started</div><div class="v">{f['total']}</div>
      <div class="n2">{f['open']} still open</div></div>
    <div class="kpi"><div class="k">Conversion rate</div>
      <div class="v">{f['conversion_rate']:.0%}</div>
      <div class="n2">of decided pilots</div></div>
    <div class="kpi"><div class="k">Median time to production</div>
      <div class="v">{f['median_time_to_prod']} mo</div></div>
    <div class="kpi warn"><div class="k">True CAC</div>
      <div class="v">${f['true_cac']:,.0f}</div>
      <div class="n2">{f['true_cac']/f['naive_cac']:.1f}x the naive ${f['naive_cac']:,.0f}</div></div>
    <div class="kpi warn"><div class="k">Hardware at prospect sites</div>
      <div class="v">${f['hardware_at_risk']/1e6:,.1f}M</div>
      <div class="n2">earning nothing</div></div>
  </div>

  <div class="callout"><strong>The number that changes the conversation:</strong>
    naive CAC counts only the pilots you won — ${f['naive_cac']:,.0f}. True CAC
    divides <em>all</em> pilot cost by the wins:
    <strong>${f['true_cac']:,.0f}</strong>, or {f['true_cac']/f['naive_cac']:.1f}×.
    The lost and stalled pilots are not overhead; they are the cost of acquiring
    the customers you did win. At an average ${avg_acv:,.0f} ACV, that CAC takes
    <strong>{payback:.0f} months of first-year revenue</strong> to repay — which
    is the real conclusion on this page: <strong>pilot-heavy acquisition is only
    solvent on multi-year terms.</strong> Against a three-year deployment
    contract the same CAC is {f['true_cac']/tcv_3yr:.0%} of TCV, which is
    workable. Against a one-year contract it is not. In robotics, contract
    <em>term</em> is a financial lever every bit as important as price, and it
    is usually negotiated by people who have never seen this number.
    <br><br><strong>And the counterfactual is the actionable half:</strong> had
    only the qualified pilots been run — named sponsor plus written success
    criteria — true CAC would be <strong>${qf['true_cac']:,.0f}</strong>, or
    <strong>{q_ratio:.0%} of three-year TCV</strong> against
    {f['true_cac']/tcv_3yr:.0%} actual. The unqualified pilots are not
    underperforming; they are the entire reason the acquisition motion does not
    pay for itself.</div>

  <h2>The funnel</h2>
  <div class="chart"><svg viewBox="0 0 {W} {PT + 3*46 + 20}">{fun}</svg></div>

  <h2>F1 — Conversion by pilot age</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid}{purg_line}{bars}</svg></div>
  <div class="note">Conversion collapses past the {PURGATORY_MONTHS}-month mark.
    That makes pilot purgatory <em>datable</em>, which is what turns "we should
    probably close some of these" into a defensible kill rule with a number
    attached. Everything to the right of the dashed line is engineering capacity
    being spent at close to zero expected return.</div>

  <h2>F2 — Conversion by qualification quality</h2>
  <div class="tbl"><table>
    <thead><tr><th>Qualification</th><th class="n">Pilots</th><th class="n">Decided</th>
      <th class="n">Conversion</th><th class="n">Cost</th><th class="n">ACV won</th></tr></thead>
    <tbody>{qual_rows}</tbody></table></div>
  <div class="note">A named executive sponsor <em>and</em> written success
    criteria is the difference between a pilot and an experiment. The
    unqualified cohort consumes real cost and returns little — the cheapest
    intervention available here is a qualification gate before a robot ever
    ships, not a better pilot.</div>

  <h2>Pilot purgatory — open longer than {PURGATORY_MONTHS} months</h2>
  <div class="tbl"><table>
    <thead><tr><th>Pilot</th><th>Company</th><th>Industry</th>
      <th class="n">Age</th><th class="n">Sunk cost</th>
      <th class="n">Hardware on site</th></tr></thead>
    <tbody>{stuck_rows}</tbody></table></div>
  <div class="note"><strong>{len(stuck)} pilots</strong>,
    <strong>${sum(p['total_pilot_cost'] for p in stuck):,.0f}</strong> sunk, and
    <strong>${sum(p['hardware_at_risk'] for p in stuck):,.0f}</strong> of hardware
    sitting at prospect sites earning nothing. This is the list to work, and the
    finance recommendation is not "try harder" — it is a decision date on each
    one, and recovery of the units from the ones that miss it.</div>

  <footer>Generated by pilots.py · funnel ties, sanity bounds enforced, seeded
    findings verified (run --validate) · all data synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Pilot-to-production funnel economics")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    pilots = make_pilots()
    with (DATA / "pilots.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pilots[0].keys()))
        w.writeheader(); w.writerows(pilots)

    print_report(pilots)
    if args.validate:
        validate(pilots)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(pilots, args.html)


if __name__ == "__main__":
    main()
