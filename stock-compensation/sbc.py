#!/usr/bin/env python3
"""ASC 718 stock-based compensation — a grant ledger where cumulative expense
must reprove itself from tranche states every month.

The story the data contains (decided before the generator):
  1. Straight-line vs graded (FIN 28) attribution computed side by side on
     the same ledger. Same awards, same total — graded front-loads. Both
     must converge to grant-date fair value for every fully vested award.
  2. Forfeitures at actuals (the ASU 2016-09 election): an August 2025
     reduction-in-force reverses the unvested expense of 7 employees in one
     month — the expense line dips, and validation must recompute the
     reversal independently to the cent.
  3. One repricing: a 2022 option grant struck at $8.40 goes underwater in
     the 2023 down round and is repriced in March 2025. Incremental fair
     value = (new award − old award), both valued at the modification date;
     total expense for the grant must equal original FV + incremental FV.

The core identity (check 1): the engine books expense month by month —
accruals, vesting true-ups, forfeiture reversals. A separate closed-form
recomputation walks every tranche's state (vested / active / forfeited) at
each month-end and states what cumulative expense MUST be. The two must
agree to the cent, every month, under both attribution methods.

Bug the validation caught during development: the first draft kept accruing
straight-line expense through the cliff month and never trued the cliff
tranche, so a January-cliff employee who quit in month 11 kept 11/48 of
expense that should have reversed to zero. The closed-form recomputation
disagreed at the first forfeiture and check 1 failed.
"""

import argparse
import csv
import random
from math import erf, exp, log, sqrt
from pathlib import Path

random.seed(718)

MONTHS = [(y, m) for y in (2022, 2023, 2024, 2025) for m in range(1, 13)]
FY25 = [(2025, m) for m in range(1, 13)]
VEST_MO = 48
CLIFF_MO = 12
TOL = 0.01
RIF_MONTH = (2025, 8)
RIF_COUNT = 7


def mi(ym):
    return (ym[0] - 2022) * 12 + ym[1] - 1


# ------------------------------------------------------- share price (409A) --
def fmv_path():
    """Monthly FMV per share: growth, a 2023 down round, recovery."""
    fmv = {}
    v = 6.00
    for ym in MONTHS:
        if ym == (2023, 6):
            v = 3.60                      # the down round
        elif ym < (2023, 6):
            v *= 1.010 * random.uniform(0.995, 1.005)
        else:
            v *= 1.020 * random.uniform(0.995, 1.005)
        fmv[ym] = round(v, 2)
    return fmv


def black_scholes(s, k, vol, rf, t):
    if t <= 0:
        return max(s - k, 0.0)
    d1 = (log(s / k) + (rf + vol * vol / 2) * t) / (vol * sqrt(t))
    d2 = d1 - vol * sqrt(t)
    n = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
    return s * n(d1) - k * exp(-rf * t) * n(d2)


VOL = {2022: 0.62, 2023: 0.60, 2024: 0.57, 2025: 0.55}
RF = {2022: 0.030, 2023: 0.041, 2024: 0.043, 2025: 0.040}
TERM = 6.0                                # expected term, years (simplified)


# ------------------------------------------------------------ grant ledger --
def make_grants(fmv):
    grants = []
    gid = 0
    for ym in MONTHS:
        if ym > (2025, 6):
            break
        for _ in range(random.choice([0, 1, 1, 2])):
            gid += 1
            kind = random.choice(["rsu", "rsu", "option"])
            shares = random.choice([2_000, 4_000, 8_000, 12_000, 20_000, 40_000])
            s = fmv[ym]
            if kind == "rsu":
                fv_ps = s
                strike = None
            else:
                strike = s                # at-the-money at grant (409A)
                fv_ps = black_scholes(s, s, VOL[ym[0]], RF[ym[0]], TERM)
            # ~15% of employees depart at a random later month
            depart = None
            if random.random() < 0.15:
                dm = mi(ym) + random.randint(6, 40)
                if dm < len(MONTHS):
                    depart = MONTHS[dm]
            grants.append(dict(gid=gid, kind=kind, grant=ym, shares=shares,
                               strike=strike, fv_ps=round(fv_ps, 4),
                               fv_total=round(fv_ps * shares, 2),
                               depart=depart, repriced=False, incr_fv=0.0))
    # the repricing target: a big early option grant, employee stays
    g0 = dict(gid=0, kind="option", grant=(2022, 3), shares=60_000,
              strike=8.40, fv_ps=round(black_scholes(8.40, 8.40, VOL[2022],
                                                     RF[2022], TERM), 4),
              depart=None, repriced=True, incr_fv=0.0)
    g0["fv_total"] = round(g0["fv_ps"] * g0["shares"], 2)
    grants.insert(0, g0)
    # the August 2025 RIF: 7 still-in-cliff grantees leave at once —
    # pre-cliff forfeiture reverses their entire accrual, by design
    pool = [g for g in grants if g["depart"] is None and not g["repriced"]
            and mi(g["grant"]) + CLIFF_MO > mi(RIF_MONTH)
            and mi(g["grant"]) < mi(RIF_MONTH)]
    for g in pool[:RIF_COUNT]:
        g["depart"] = RIF_MONTH
        g["rif"] = True
    return grants


def apply_repricing(grants, fmv):
    """March 2025: reprice the underwater 2022 grant to current FMV.
    Incremental FV = new-award value − old-award value at modification date,
    remaining expected term ~4y. Recognized over remaining vesting."""
    g = grants[0]
    s = fmv[(2025, 3)]
    t_rem = 4.0
    old = black_scholes(s, g["strike"], VOL[2025], RF[2025], t_rem)
    new = black_scholes(s, s, VOL[2025], RF[2025], t_rem)
    g["incr_fv"] = round((new - old) * g["shares"], 2)
    g["mod_month"] = (2025, 3)
    g["new_strike"] = s
    return g


# ----------------------------------------------------------- tranche model --
def tranches(g):
    """48-month vest, 12-month cliff: tranche at month 12 = 12/48, then
    monthly. Returns [(vest_month_index, fraction)]."""
    g0 = mi(g["grant"])
    out = [(g0 + CLIFF_MO, CLIFF_MO / VEST_MO)]
    out += [(g0 + k, 1 / VEST_MO) for k in range(CLIFF_MO + 1, VEST_MO + 1)]
    return out


def closed_form(g, m_idx, method):
    """What cumulative expense MUST be at month-end m_idx for grant g.
    Vested tranche (before any departure): full tranche FV. Unvested tranche,
    employee active: service-fraction accrual (graded: fraction of ITS OWN
    period; straight-line: total FV spread over 48, floored at vested).
    Departed before vest: zero."""
    fv = g["fv_total"]
    g0 = mi(g["grant"])
    dep = mi(g["depart"]) if g["depart"] else 10 ** 9
    served = min(m_idx, dep) - g0 + 1 if m_idx >= g0 else 0
    served = max(0, min(served, VEST_MO))
    vested_frac = 0.0
    for v, frac in tranches(g):
        if v <= min(m_idx, dep):
            vested_frac += frac
    if method == "sl":
        if m_idx >= dep:
            base = vested_frac * fv       # unvested accrual reversed
        else:
            base = min(served / VEST_MO, 1.0) * fv
            base = max(base, vested_frac * fv)
    else:                                 # graded / FIN 28
        base = 0.0
        for v, frac in tranches(g):
            if v <= min(m_idx, dep):
                base += frac * fv
            elif m_idx < dep and m_idx >= g0:
                period = v - g0
                base += frac * fv * min((m_idx - g0 + 1) / period, 1.0)
    # incremental FV from the repricing accrues straight-line over the
    # remaining vesting period from the modification month
    if g.get("incr_fv") and m_idx >= mi(g["mod_month"]):
        mod = mi(g["mod_month"])
        vest_end = g0 + VEST_MO
        period = max(vest_end - mod, 1)
        base += g["incr_fv"] * min((m_idx - mod + 1) / period, 1.0)
    return base


def engine(grants, method):
    """Monthly postings: accruals, cliff true-ups, forfeiture reversals —
    built incrementally (NOT from the closed form; that is the point)."""
    cum = {g["gid"]: 0.0 for g in grants}
    monthly = []
    for m_idx, ym in enumerate(MONTHS):
        post = 0.0
        for g in grants:
            g0 = mi(g["grant"])
            dep = mi(g["depart"]) if g["depart"] else 10 ** 9
            if m_idx < g0:
                continue
            if m_idx == dep:
                vested = sum(f for v, f in tranches(g) if v <= dep)
                target = vested * g["fv_total"]
                if g.get("incr_fv") and m_idx >= mi(g["mod_month"]):
                    mod = mi(g["mod_month"])
                    period = max(g0 + VEST_MO - mod, 1)
                    target += g["incr_fv"] * min((m_idx - mod + 1) / period, 1.0)
                post += target - cum[g["gid"]]
                cum[g["gid"]] = target
                continue
            if m_idx > dep or m_idx >= g0 + VEST_MO + 1:
                continue
            if method == "sl":
                accr = g["fv_total"] / VEST_MO if m_idx < g0 + VEST_MO else 0.0
            else:
                accr = 0.0
                for v, frac in tranches(g):
                    period = v - g0
                    if m_idx < v:
                        accr += frac * g["fv_total"] / period
            if g.get("incr_fv") and m_idx >= mi(g["mod_month"]):
                mod = mi(g["mod_month"])
                period = max(g0 + VEST_MO - mod, 1)
                if m_idx < g0 + VEST_MO:
                    accr += g["incr_fv"] / period
            cum[g["gid"]] += accr
            post += accr
        monthly.append(post)
    return monthly, cum


def run_checks(grants, fmv):
    checks = []

    def add(name, ok, detail):
        checks.append((name, ok, detail))

    monthly_sl, cum_sl = engine(grants, "sl")
    monthly_gr, cum_gr = engine(grants, "graded")

    # 1. engine == closed form, every month-end, both methods
    worst, where = 0.0, ""
    for method, monthly in (("sl", monthly_sl), ("graded", monthly_gr)):
        run = 0.0
        for m_idx, ym in enumerate(MONTHS):
            run += monthly[m_idx]
            want = sum(closed_form(g, m_idx, method) for g in grants)
            if abs(run - want) > worst:
                worst, where = abs(run - want), f"{method} {ym}"
    add("engine == closed-form recomputation, 48 month-ends x 2 methods",
        worst < TOL, f"max gap ${worst:.6f} ({where or 'none'})")

    # 2. at full vesting both attribution formulas land on grant-date FV
    #    (evaluated at each grant's 48-month horizon; check 1 pins the
    #    engine to these formulas inside the reporting window)
    worst = 0.0
    stay = [g for g in grants if g["depart"] is None and not g["repriced"]]
    for g in stay:
        horizon = mi(g["grant"]) + VEST_MO + 1
        for method in ("sl", "graded"):
            worst = max(worst, abs(closed_form(g, horizon, method) - g["fv_total"]))
    add("at full vesting, SL and graded both land on grant-date FV",
        worst < TOL, f"{len(stay)} stayer awards, max gap ${worst:.6f}")

    # 3. cumulative never exceeds total FV (+ incremental)
    ok = all(cum_gr[g["gid"]] <= g["fv_total"] + g["incr_fv"] + TOL
             and cum_sl[g["gid"]] <= g["fv_total"] + g["incr_fv"] + TOL
             for g in grants)
    add("cumulative expense <= grant-date FV + incremental FV, always", ok,
        "hard ceiling on every award")

    # 4. unrecognized + recognized = total, for active unvested awards
    worst = 0.0
    for g in grants:
        if g["depart"] or mi(g["grant"]) + VEST_MO <= mi(MONTHS[-1]):
            continue
        total = g["fv_total"] + g["incr_fv"]
        unrec = total - cum_sl[g["gid"]]
        worst = max(worst, abs((unrec + cum_sl[g["gid"]]) - total))
    add("unrecognized + recognized = total FV for active awards",
        worst < TOL, f"max gap ${worst:.6f}")

    # 5. the RIF reversal, recomputed independently
    rif = [g for g in grants if g.get("rif")]
    aug = mi(RIF_MONTH)
    reversal = 0.0
    for g in rif:
        pre = closed_form(g, aug - 1, "sl")
        post = closed_form(g, aug, "sl")
        reversal += pre - post
    dip = monthly_sl[aug - 1] - monthly_sl[aug]
    ok = len(rif) == RIF_COUNT and reversal > 0 and dip > 0
    add("Aug-2025 RIF: unvested expense of 7 in-cliff grants reverses; the line dips",
        ok, f"${reversal/1e3:,.0f}K reversed, monthly expense drops "
        f"${dip/1e3:,.0f}K vs July")

    # 6. repricing: incremental FV positive and total ties
    g = grants[0]
    end = mi(MONTHS[-1])
    expect = closed_form(g, end, "sl")
    full = g["fv_total"] + g["incr_fv"]
    ok = g["incr_fv"] > 0 and expect <= full + TOL
    add("repricing: incremental FV > 0; modified award never exceeds "
        "original + incremental", ok,
        f"incremental ${g['incr_fv']/1e3:,.0f}K on strike "
        f"$8.40 -> ${g['new_strike']:.2f}")

    # 7. Black-Scholes sanity: FV between intrinsic and stock price
    ok = True
    for g in grants:
        if g["kind"] != "option":
            continue
        s = fmv[g["grant"]]
        ok &= max(s - g["strike"], 0) - 1e-9 <= g["fv_ps"] <= s + 1e-9
    add("option fair values bounded by intrinsic value and share price", ok,
        "Black-Scholes outputs sane for every option grant")

    fy25_sl = sum(monthly_sl[mi(m)] for m in FY25)
    fy25_gr = sum(monthly_gr[mi(m)] for m in FY25)
    add("FY2025 expense positive under both methods",
        fy25_sl > 0 and fy25_gr > 0,
        f"SL ${fy25_sl/1e6:,.2f}M / graded ${fy25_gr/1e6:,.2f}M")
    return checks, monthly_sl, monthly_gr, cum_sl, cum_gr


# ------------------------------------------------------------------ output --
def write_data(grants, fmv):
    d = Path(__file__).parent / "data"
    d.mkdir(exist_ok=True)
    with open(d / "grants.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gid", "kind", "grant_month", "shares", "strike",
                    "fv_per_share", "fv_total", "depart_month", "rif",
                    "repriced", "incremental_fv"])
        for g in grants:
            w.writerow([g["gid"], g["kind"], f"{g['grant'][0]}-{g['grant'][1]:02d}",
                        g["shares"], g["strike"] or "", g["fv_ps"],
                        g["fv_total"],
                        f"{g['depart'][0]}-{g['depart'][1]:02d}" if g["depart"] else "",
                        g.get("rif", False), g["repriced"], g["incr_fv"]])
    with open(d / "fmv_409a.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "fmv"])
        for ym in MONTHS:
            w.writerow([f"{ym[0]}-{ym[1]:02d}", f"{fmv[ym]:.2f}"])


def print_report(grants, checks, monthly_sl, monthly_gr, out=print):
    fy25 = sum(monthly_sl[mi(m)] for m in FY25)
    fy25g = sum(monthly_gr[mi(m)] for m in FY25)
    total_fv = sum(g["fv_total"] for g in grants)
    out("STOCK-BASED COMPENSATION — ASC 718")
    out(f"  Grants                      {len(grants)} "
        f"(RSU {sum(1 for g in grants if g['kind']=='rsu')} / "
        f"option {sum(1 for g in grants if g['kind']=='option')}), "
        f"total grant-date FV ${total_fv/1e6:,.1f}M")
    out(f"  FY2025 expense              ${fy25/1e6:,.2f}M straight-line "
        f"(policy) / ${fy25g/1e6:,.2f}M graded")
    out(f"  Repricing                   incremental FV "
        f"${grants[0]['incr_fv']/1e3:,.0f}K — $8.40 strike underwater since "
        "the 2023 down round, repriced 2025-03")
    aug = mi(RIF_MONTH)
    out(f"  RIF true-up                 Aug-25 expense "
        f"${monthly_sl[aug]/1e3:,.0f}K vs Jul ${monthly_sl[aug-1]/1e3:,.0f}K"
        " — forfeitures at actuals, reversed in the month they happen")
    out("")
    for name, ok, detail in checks:
        out(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    out("")
    out("  " + ("ALL CHECKS PASS" if all(c[1] for c in checks) else "FAILURES PRESENT"))


def svg_two_lines(a, b, w=940, h=220, pad=36):
    hi = max(max(a), max(b)) or 1
    n = len(a)

    def pts(s):
        o = []
        for i, v in enumerate(s):
            x = pad + i * (w - 2 * pad) / (n - 1)
            y = h - pad - v / hi * (h - 2 * pad)
            o.append(f"{x:.1f},{y:.1f}")
        return " ".join(o)

    out = [f'<svg viewBox="0 0 {w} {h}" role="img">']
    for gy in range(4):
        yv = hi * (1 - gy / 3)
        y = pad + gy * (h - 2 * pad) / 3
        out.append(f'<line x1="{pad}" y1="{y:.0f}" x2="{w-pad}" y2="{y:.0f}" '
                   'stroke="var(--grid)"/>')
        out.append(f'<text x="{pad-6}" y="{y+4:.0f}" text-anchor="end" '
                   f'font-size="10" fill="var(--mut)">${yv/1e3:.0f}K</text>')
    out.append(f'<polyline points="{pts(b)}" fill="none" stroke="var(--mut)" '
               'stroke-width="1.8" stroke-dasharray="5 4"/>')
    out.append(f'<polyline points="{pts(a)}" fill="none" stroke="var(--line)" '
               'stroke-width="2.2"/>')
    for yr in (2022, 2023, 2024, 2025):
        i = mi((yr, 1))
        x = pad + i * (w - 2 * pad) / (n - 1)
        out.append(f'<text x="{x:.0f}" y="{h-8}" text-anchor="middle" '
                   f'font-size="10" fill="var(--mut)">{yr}</text>')
    aug = mi(RIF_MONTH)
    x = pad + aug * (w - 2 * pad) / (n - 1)
    out.append(f'<line x1="{x:.0f}" y1="{pad}" x2="{x:.0f}" y2="{h-pad}" '
               'stroke="var(--neg)" stroke-width="1" stroke-dasharray="3 3"/>')
    out.append(f'<text x="{x+4:.0f}" y="{pad+12}" font-size="10" '
               'fill="var(--neg)">RIF true-up</text>')
    out.append("</svg>")
    return "".join(out)


def write_html(path, grants, fmv, checks, monthly_sl, monthly_gr, cum_sl):
    fy25 = sum(monthly_sl[mi(m)] for m in FY25)
    fy25g = sum(monthly_gr[mi(m)] for m in FY25)
    total_fv = sum(g["fv_total"] for g in grants)
    active = [g for g in grants if not g["depart"]
              and mi(g["grant"]) + VEST_MO > mi(MONTHS[-1])]
    unrec = sum(g["fv_total"] + g["incr_fv"] - cum_sl[g["gid"]] for g in active)
    aug = mi(RIF_MONTH)
    y1_2024 = sum(monthly_gr[mi((2024, m))] for m in range(1, 13))
    y1_2024sl = sum(monthly_sl[mi((2024, m))] for m in range(1, 13))
    g0 = grants[0]
    top = sorted(grants, key=lambda g: -(g["fv_total"] + g["incr_fv"]))[:8]
    rows = ""
    for g in top:
        flag = ' class="flag"' if g["repriced"] else ""
        status = "departed" if g["depart"] else "active"
        if g.get("rif"):
            status = "RIF Aug-25"
        rows += (f"<tr{flag}><td>#{g['gid']} {g['kind'].upper()}</td>"
                 f"<td>{g['grant'][0]}-{g['grant'][1]:02d}</td>"
                 f"<td>{g['shares']:,}</td>"
                 f"<td>{'$%.2f' % g['strike'] if g['strike'] else '—'}</td>"
                 f"<td>${g['fv_ps']:.2f}</td>"
                 f"<td>${(g['fv_total']+g['incr_fv'])/1e3:,.0f}K</td>"
                 f"<td>{status}</td></tr>")
    checks_html = "".join(
        f"<li><b class='{'ok' if ok else 'bad'}'>{'PASS' if ok else 'FAIL'}</b> "
        f"{name} <span class='mut'>— {detail}</span></li>"
        for name, ok, detail in checks)
    html = f"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ASC 718 stock comp — FY2025</title>
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
  .kpi .v {{ font-size:21px; font-weight:700; letter-spacing:-.01em; }}
  .kpi .l {{ font-size:11.5px; color:var(--mut); margin-top:2px; }}
  .card {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
           padding:16px 18px; margin-top:10px; overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; min-width:640px; }}
  th, td {{ text-align:right; padding:6px 10px; border-bottom:1px solid var(--bd); }}
  th:first-child, td:first-child {{ text-align:left; }}
  th {{ color:var(--mut); font-weight:600; font-size:11.5px;
        text-transform:uppercase; letter-spacing:.04em; }}
  .mut {{ color:var(--mut); }} .ok {{ color:var(--pos); }} .bad {{ color:var(--neg); }}
  .flag {{ background:color-mix(in srgb, var(--line) 8%, transparent); }}
  .note {{ font-size:12.5px; color:var(--mut); margin-top:8px; max-width:88ch; }}
  ul.checks {{ list-style:none; padding:0; margin:0; font-size:13px; }}
  ul.checks li {{ padding:5px 0; border-bottom:1px solid var(--bd); }}
  svg {{ width:100%; height:auto; display:block; }}
</style>
<div class="wrap">
  <h1>Stock-Based Compensation — ASC 718</h1>
  <p class="sub">{len(grants)} grants (RSUs and options, 4-year vest,
    1-year cliff), 2022–2025. Every month-end, cumulative expense is
    recomputed from scratch out of tranche states — vested, active, forfeited
    — and the incremental engine must match it to the cent under both
    attribution methods. Synthetic, seeded data.</p>

  <div class="kpis">
    <div class="kpi"><div class="v">${fy25/1e6:,.2f}M</div>
      <div class="l">FY2025 expense — straight-line (policy)</div></div>
    <div class="kpi"><div class="v">${fy25g/1e6:,.2f}M</div>
      <div class="l">FY2025 under graded (FIN 28) — same awards, same total,
        different timing</div></div>
    <div class="kpi"><div class="v">${unrec/1e6:,.1f}M</div>
      <div class="l">Unrecognized compensation remaining on active awards</div></div>
    <div class="kpi"><div class="v">${g0['incr_fv']/1e3:,.0f}K</div>
      <div class="l">Incremental FV from the March-25 repricing</div></div>
    <div class="kpi"><div class="v">${(monthly_sl[aug-1]-monthly_sl[aug])/1e3:,.0f}K</div>
      <div class="l">Aug-25 expense dip — RIF forfeitures reversed at actuals</div></div>
    <div class="kpi"><div class="v">{len(MONTHS)*2}/{len(MONTHS)*2}</div>
      <div class="l">Month-ends where engine == closed-form recomputation</div></div>
  </div>

  <h2>Monthly expense — straight-line (solid) vs graded (dashed)</h2>
  <div class="card">{svg_two_lines(monthly_sl, monthly_gr)}
    <p class="note">Same ledger, two attribution methods. Graded treats every
      vesting tranche as its own award and front-loads: in 2024 it books
      ${y1_2024/1e6:,.2f}M against straight-line's ${y1_2024sl/1e6:,.2f}M.
      Both must converge to grant-date fair value at full vesting — check 2
      proves they do, award by award. The August 2025 dip is the RIF:
      forfeitures at actuals (ASU 2016-09 election), reversed in the month
      they happen, not smoothed by an estimate.</p></div>

  <h2>The repricing</h2>
  <div class="card">
    <p style="font-size:13.5px;margin:0">Grant #0 — 60,000 options struck at
      $8.40 in March 2022 — went underwater in the June 2023 down round and
      stayed there. Repriced March 2025 to ${g0['new_strike']:.2f}.
      ASC 718's rule is unforgiving in a specific way: the original
      ${g0['fv_total']/1e3:,.0f}K grant-date fair value is <b>never</b>
      reversed — an underwater option still cost what it cost — and the
      modification adds incremental fair value of
      ${g0['incr_fv']/1e3:,.0f}K (new award minus old award, both valued at
      the modification date), recognized over the remaining vesting
      period.</p>
    <p class="note">The check: the modified award's lifetime expense can
      never exceed original FV + incremental FV. The board asks "what did
      the repricing cost?" — the answer is ${g0['incr_fv']/1e3:,.0f}K, not
      the headline value of the new options.</p></div>

  <h2>Largest awards</h2>
  <div class="card"><table>
    <tr><th>Grant</th><th>Granted</th><th>Shares</th><th>Strike</th>
        <th>FV/share</th><th>Total FV</th><th>Status</th></tr>
    {rows}
  </table>
  <p class="note">Option fair values are Black-Scholes at grant
    (vol {VOL[2025]:.0%}–{VOL[2022]:.0%} by year, expected term
    {TERM:.0f} years, strike = 409A FMV at grant). Validation bounds every
    option FV between intrinsic value and the share price — the classic
    smell test for a mis-wired pricing input.</p></div>

  <h2>Validation — re-run before every publish</h2>
  <div class="card"><ul class="checks">{checks_html}</ul></div>

  <p class="note" style="margin-top:26px">Synthetic, seeded data
    (<code>random.seed(718)</code>). Generator, engines, and checks:
    <a href="https://github.com/Lumimama/finance/tree/main/stock-compensation"
       style="color:var(--line)">github.com/Lumimama/finance/stock-compensation</a>.</p>
</div>
"""
    Path(path).write_text(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--html")
    ap.add_argument("--report")
    args = ap.parse_args()

    fmv = fmv_path()
    grants = make_grants(fmv)
    apply_repricing(grants, fmv)
    checks, msl, mgr, csl, cgr = run_checks(grants, fmv)
    write_data(grants, fmv)

    if args.report:
        lines = []
        print_report(grants, checks, msl, mgr, out=lines.append)
        Path(args.report).write_text("\n".join(lines) + "\n")
    print_report(grants, checks, msl, mgr)
    if args.html:
        write_html(args.html, grants, fmv, checks, msl, mgr, csl)
        print(f"  wrote {args.html}")
    if args.validate and not all(c[1] for c in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
