#!/usr/bin/env python3
"""Multi-entity consolidation under ASC 830 — translation, remeasurement,
intercompany eliminations, and a CTA that must prove itself two ways.

Group: US parent (USD) + three foreign subsidiaries.
  UK Ltd        GBP books, GBP functional  -> TRANSLATION  (rate effects to CTA/OCI)
  Japan KK      JPY books, JPY functional  -> TRANSLATION  (rate effects to CTA/OCI)
  Singapore Pte SGD books, USD functional  -> REMEASUREMENT (rate effects to P&L)

Design decisions (the story the data contains, decided before the generator):
  1. CTA is computed two independent ways every month — as the balance-sheet
     plug, and as an analytical roll-forward (opening net assets x spot move
     + NI x (spot - avg)). They must agree to the cent or validation fails.
     The plug alone can silently absorb a translation coding error; the roll
     cannot.
  2. Singapore deliberately holds no nonmonetary assets, so its remeasurement
     adjustment is arithmetically identical to what CTA would have been. The
     ONLY difference is geography: P&L vs OCI. Functional currency, not
     location, decides where FX lands.
  3. One seeded intercompany break: Japan accrues the November management fee
     with two digits transposed — off by JPY 27,000. A transposition error is
     always divisible by 9, and the IC matrix flags it as such. The engine
     posts a top-side correction in November and reverses it in December when
     Japan's own books catch up.
  4. Intercompany fees are invoiced in each sub's local currency, so the
     parent's IC receivables are foreign-currency monetary assets remeasured
     through parent P&L at each close (ASC 830-20) — they do NOT eliminate
     against anything and are reported as FX in P&L.

Bug the validation caught during development: the first draft translated the
subs' IC payables at the average rate (copying the P&L treatment of the fee).
The CTA plug still balanced — plugs always balance — but the analytical roll
disagreed by exactly (spot - avg) x the IC balance, and check 3 failed. That
is why the roll-forward exists.
"""

import argparse
import csv
import random
from pathlib import Path

random.seed(830)

MONTHS = ["2024-11", "2024-12",
          "2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06",
          "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
REPORT_MONTHS = MONTHS[2:]          # FY2025; first two months are warm-up
FEE_RATE = 0.03                     # management fee: 3% of sub revenue
SETTLE_LAG = 2                      # IC fees settle two months in arrears
TRANSPOSE_LC = 27_000               # JPY: the seeded November transposition
TOL = 0.01                          # "to the cent"

# ---------------------------------------------------------------- FX rates --
# USD per unit of local currency. Seeded random walk with drift; avg is the
# midpoint of the month's endpoints (a simplification stated in the README).
FX_START = {"GBP": 1.266, "JPY": 0.00647, "SGD": 0.741}
FX_DRIFT = {"GBP": -0.0030, "JPY": -0.000040, "SGD": 0.0010}
FX_NOISE = {"GBP": 0.008, "JPY": 0.000055, "SGD": 0.004}
FX_HIST = {"GBP": 1.310, "JPY": 0.00720, "SGD": 0.730}  # equity-formation rates


def gen_rates():
    """spot[ccy][month] (end of month) and avg[ccy][month]."""
    spot, avg = {}, {}
    for ccy in FX_START:
        s_prev = FX_START[ccy]
        spot[ccy], avg[ccy] = {}, {}
        for m in MONTHS:
            s = s_prev + FX_DRIFT[ccy] + random.uniform(-FX_NOISE[ccy], FX_NOISE[ccy])
            spot[ccy][m] = s
            avg[ccy][m] = (s_prev + s) / 2
            s_prev = s
    return spot, avg


# ---------------------------------------------------------- entity ledgers --
SUBS = {
    # ccy, base rev, growth, noise, opex ratio, dep/mo, FA gross, accdep0,
    # CS (LC), opening RE (LC), AR x rev, AP x opex
    "UK":  dict(ccy="GBP", rev0=940_000, g=0.012, nz=0.03, opex=0.80,
                dep=18_000, fa=1_300_000, accdep0=420_000, cs=250_000,
                re0=1_900_000, arx=1.45, apx=0.75),
    "JP":  dict(ccy="JPY", rev0=178_000_000, g=0.008, nz=0.04, opex=0.86,
                dep=2_900_000, fa=210_000_000, accdep0=68_000_000,
                cs=50_000_000, re0=310_000_000, arx=1.60, apx=0.80),
    "SG":  dict(ccy="SGD", rev0=1_050_000, g=0.010, nz=0.03, opex=0.93,
                dep=0, fa=0, accdep0=0, cs=400_000,
                re0=720_000, arx=1.30, apx=0.85),
}
PARENT = dict(rev0=4_150_000, g=0.011, nz=0.02, opex=0.87, dep=95_000,
              fa=6_800_000, accdep0=2_100_000, cs=12_000_000, re0=9_400_000,
              arx=1.40, apx=0.70)
CTA0 = {"UK": -286_000.0, "JP": -1_540_000.0}   # opening accumulated CTA, USD


def gen_ledgers():
    """Monthly local-currency trial balances for every entity.

    Every TB balances by construction: cash is the plug. The management fee
    is computed on TRUE revenue; Japan's BOOKED November fee carries the
    transposition, corrected in Japan's own December books.
    """
    fees_true = {s: {} for s in SUBS}      # LC fee owed, by sub and month
    fees_booked = {s: {} for s in SUBS}    # LC fee the sub actually accrued
    ledgers = {}

    for name, p in SUBS.items():
        rows, re = {}, p["re0"]
        accdep = p["accdep0"]
        for i, m in enumerate(MONTHS):
            rev = p["rev0"] * (1 + p["g"]) ** i * random.uniform(1 - p["nz"], 1 + p["nz"])
            fee = round(rev * FEE_RATE, 2)
            fees_true[name][m] = fee
            booked = fee
            if name == "JP" and m == "2025-11":
                booked = fee - TRANSPOSE_LC          # the transposition
            if name == "JP" and m == "2025-12":
                booked = fee + TRANSPOSE_LC          # Japan's own catch-up
            fees_booked[name][m] = booked
            opex = rev * p["opex"]
            accdep += p["dep"]
            ni = rev - opex - p["dep"] - booked
            re += ni
            i_prev = MONTHS[MONTHS.index(m) - 1] if MONTHS.index(m) else None
            ic_ap = booked + (fees_booked[name].get(i_prev, fee) if i_prev else fee)
            ar, ap = rev * p["arx"], opex * p["apx"]
            liab_eq = ap + ic_ap + p["cs"] + re
            cash = liab_eq - (ar + p["fa"] - accdep)
            rows[m] = dict(rev=rev, opex=opex, dep=p["dep"], fee_exp=booked,
                           ni=ni, cash=cash, ar=ar, fa=p["fa"], accdep=accdep,
                           ap=ap, ic_ap=ic_ap, cs=p["cs"], re=re)
        ledgers[name] = rows
    return ledgers, fees_true, fees_booked


def gen_parent(spot, avg, fees_true):
    """Parent USD ledger. Fee income at the month's average rate; IC AR is a
    foreign-currency monetary asset carried at spot, FX through P&L."""
    rows, re = {}, PARENT["re0"]
    accdep = PARENT["accdep0"]
    investment = sum(SUBS[s]["cs"] * FX_HIST[SUBS[s]["ccy"]] for s in SUBS)
    # opening IC receivable mirrors the subs' opening payable convention:
    # two months outstanding, proxied by the first month's fee
    ar_lc = {s: 2 * fees_true[s][MONTHS[0]] for s in SUBS}
    prev_usd = {s: ar_lc[s] * FX_START[SUBS[s]["ccy"]] for s in SUBS}
    for i, m in enumerate(MONTHS):
        rev = PARENT["rev0"] * (1 + PARENT["g"]) ** i * random.uniform(
            1 - PARENT["nz"], 1 + PARENT["nz"])
        opex = rev * PARENT["opex"]
        accdep += PARENT["dep"]
        fee_inc, fx_gl, ic_ar_usd, settled_usd = 0.0, 0.0, 0.0, 0.0
        for s, p in SUBS.items():
            ccy = p["ccy"]
            invoiced = fees_true[s][m]
            settle_m = MONTHS.index(m) - SETTLE_LAG
            settled = fees_true[s][MONTHS[settle_m]] if settle_m >= 0 \
                else fees_true[s][MONTHS[0]]
            ar_lc[s] += invoiced - settled
            end_usd = ar_lc[s] * spot[ccy][m]
            fx_gl += end_usd - prev_usd[s] - invoiced * avg[ccy][m] \
                + settled * spot[ccy][m]
            fee_inc += invoiced * avg[ccy][m]
            settled_usd += settled * spot[ccy][m]
            ic_ar_usd += end_usd
            prev_usd[s] = end_usd
        ni = rev + fee_inc + fx_gl - opex - PARENT["dep"]
        re += ni
        ar, ap = rev * PARENT["arx"], opex * PARENT["apx"]
        liab_eq = ap + PARENT["cs"] + re
        cash = liab_eq - (ar + PARENT["fa"] - accdep + investment + ic_ar_usd)
        rows[m] = dict(rev=rev, fee_inc=fee_inc, fx_gl=fx_gl, opex=opex,
                       dep=PARENT["dep"], ni=ni, cash=cash, ar=ar,
                       ic_ar=ic_ar_usd, inv=investment, fa=PARENT["fa"],
                       accdep=accdep, ap=ap, cs=PARENT["cs"], re=re)
    return rows, ar_lc


# ------------------------------------------------- translation/remeasurement --
def translate_sub(name, ledgers, spot, avg):
    """Current-rate method (UK, JP) or remeasurement (SG). Returns per-month
    USD statements plus the two independent FX computations."""
    p = SUBS[name]
    ccy = p["ccy"]
    out = {}
    hist = FX_HIST[ccy]
    m0 = MONTHS[0]
    prev_m = None
    # Opening state (start of warm-up): translated RE set so the plug equals
    # the stated opening CTA; SG opening remeasured RE = NA x spot - CS x hist.
    na0 = p["cs"] + p["re0"]
    s0 = FX_START[ccy]
    if name in CTA0:
        re_usd = na0 * s0 - p["cs"] * hist - CTA0[name]
        fx_roll = CTA0[name]
    else:
        re_usd = na0 * s0 - p["cs"] * hist
        fx_roll = 0.0
    na_prev, spot_prev = na0, s0
    for m in MONTHS:
        led = ledgers[name][m]
        sp, av = spot[ccy][m], avg[ccy][m]
        ni_usd = led["ni"] * av
        re_usd += ni_usd
        assets = (led["cash"] + led["ar"] + led["fa"] - led["accdep"]) * sp
        liabs = (led["ap"] + led["ic_ap"]) * sp
        cs_usd = led["cs"] * hist
        fx_plug = assets - liabs - cs_usd - re_usd
        na = led["cs"] + led["re"]
        fx_roll += na_prev * (sp - spot_prev) + led["ni"] * (sp - av)
        out[m] = dict(rev=led["rev"] * av, opex=led["opex"] * av,
                      dep=led["dep"] * av, fee_exp=led["fee_exp"] * av,
                      ni=ni_usd, assets=assets, liabs=liabs, cs=cs_usd,
                      re=re_usd, fx_plug=fx_plug, fx_roll=fx_roll,
                      ic_ap=led["ic_ap"] * sp, cash=led["cash"] * sp,
                      ar=led["ar"] * sp, fa_net=(led["fa"] - led["accdep"]) * sp,
                      ap=led["ap"] * sp)
        na_prev, spot_prev, prev_m = na, sp, m
    return out


def consolidate(parent, subs_usd, fees_true, fees_booked, avg, spot):
    """Monthly consolidation: sum USD columns, post top-side IC corrections,
    eliminate fees / IC balances / investment-vs-equity."""
    consol, breaks = {}, []
    for m in MONTHS:
        # --- top-side corrections from the intercompany matrix -------------
        # P&L side: this month's fee, true vs booked (Japan's December
        # catch-up reverses here). BS side: the receivable/payable balance
        # gap (zero again in December once Japan's own books catch up).
        ts_pl = sum((fees_true[s][m] - fees_booked[s][m]) * avg[SUBS[s]["ccy"]][m]
                    for s in SUBS)
        ts_bs = 0.0
        for s, p in SUBS.items():
            idx = MONTHS.index(m)
            ar_true = fees_true[s][m] + (fees_true[s][MONTHS[idx - 1]] if idx else fees_true[s][m])
            ap_booked = subs_usd[s][m]["ic_ap"] / spot[p["ccy"]][m]
            diff_lc = ar_true - ap_booked
            if abs(diff_lc) > 0.01:
                ts_bs += diff_lc * spot[p["ccy"]][m]
                if m in REPORT_MONTHS:
                    breaks.append(dict(
                        month=m, pair=f"US–{s}", ccy=p["ccy"], diff_lc=diff_lc,
                        transposition=(round(diff_lc) % 9 == 0)))
        fee_inc = parent[m]["fee_inc"]
        ic_ar = parent[m]["ic_ar"]
        inv = parent[m]["inv"]
        rev = parent[m]["rev"] + sum(subs_usd[s][m]["rev"] for s in SUBS)
        # fees eliminate exactly once the monthly top-side lands; the
        # remaining NI adjustment is the top-side expense itself
        ni = parent[m]["ni"] + sum(subs_usd[s][m]["ni"] for s in SUBS) - ts_pl
        assets = (parent[m]["cash"] + parent[m]["ar"] + parent[m]["fa"]
                  - parent[m]["accdep"] + ic_ar + inv
                  + sum(subs_usd[s][m]["assets"] for s in SUBS))
        # IC payables after top-side equal the parent receivable exactly
        liabs = parent[m]["ap"] + sum(subs_usd[s][m]["liabs"] for s in SUBS) + ts_bs
        elim_assets = ic_ar + inv
        elim_liabs = ic_ar
        cta = sum(subs_usd[s][m]["fx_plug"] for s in SUBS if s != "SG")
        # the top-side's whole equity effect is -ts_bs: expense to RE plus a
        # (spot - avg) sliver to CTA; components below carry it as one term
        equity = parent[m]["cs"] + parent[m]["re"] \
            + sum(subs_usd[s][m]["re"] for s in SUBS) + cta \
            + subs_usd["SG"][m]["fx_plug"] - ts_bs
        consol[m] = dict(
            rev=rev, ni=ni, assets=assets - elim_assets,
            liabs=liabs - elim_liabs, equity=equity, cta=cta,
            fee_elim=fee_inc, ic_elim=ic_ar,
            fx_pl=parent[m]["fx_gl"] + (subs_usd["SG"][m]["fx_plug"]
                                        - subs_usd["SG"][MONTHS[MONTHS.index(m) - 1]]["fx_plug"]
                                        if MONTHS.index(m) else 0.0))
    return consol, breaks


# ------------------------------------------------------------------ checks --
def run_checks(ledgers, parent, subs_usd, consol, breaks, fees_true, fees_booked_g, spot, avg):
    checks = []

    def add(name, ok, detail):
        checks.append((name, ok, detail))

    # 1. every local-currency TB balances (cash was the plug; verify anyway)
    worst = 0.0
    for s, months in ledgers.items():
        for m, led in months.items():
            a = led["cash"] + led["ar"] + led["fa"] - led["accdep"]
            le = led["ap"] + led["ic_ap"] + led["cs"] + led["re"]
            worst = max(worst, abs(a - le))
    add("local TBs balance (42 entity-months)", worst < TOL, f"max |A-L-E| ${worst:.6f}")

    # 2. consolidated balance sheet ties every month
    worst = max(abs(consol[m]["assets"] - consol[m]["liabs"] - consol[m]["equity"])
                for m in REPORT_MONTHS)
    add("consolidated A = L + E, 12/12 months", worst < TOL, f"max gap ${worst:.6f}")

    # 3. CTA plug == analytical roll-forward (UK, JP; every month)
    worst = max(abs(subs_usd[s][m]["fx_plug"] - subs_usd[s][m]["fx_roll"])
                for s in ("UK", "JP") for m in MONTHS)
    add("CTA: balance-sheet plug == analytical roll", worst < TOL,
        f"max divergence ${worst:.6f}")

    # 4. remeasurement plug == analytical roll (SG)
    worst = max(abs(subs_usd["SG"][m]["fx_plug"] - subs_usd["SG"][m]["fx_roll"])
                for m in MONTHS)
    add("remeasurement (SG): plug == analytical roll", worst < TOL,
        f"max divergence ${worst:.6f}")

    # 5. seeded break: exactly one, US–JP, 2025-11, JPY 27,000, divisible by 9
    ok = (len(breaks) == 1 and breaks[0]["month"] == "2025-11"
          and breaks[0]["pair"] == "US–JP"
          and abs(breaks[0]["diff_lc"] - TRANSPOSE_LC) < 1
          and breaks[0]["transposition"])
    add("IC matrix finds the seeded transposition (and only it)", ok,
        f"{len(breaks)} break(s): " + "; ".join(
            f"{b['pair']} {b['month']} {b['ccy']} {b['diff_lc']:,.0f}" for b in breaks))

    # 6. after top-side entries every IC pair nets to zero — P&L at avg
    #    (this month's fee true-vs-booked) and BS at spot (balance gap)
    worst = 0.0
    for m in MONTHS:
        fee_exp, ap_usd = 0.0, 0.0
        for s, p in SUBS.items():
            idx = MONTHS.index(m)
            ar_true = fees_true[s][m] + (fees_true[s][MONTHS[idx - 1]] if idx else fees_true[s][m])
            ap = subs_usd[s][m]["ic_ap"] / spot[p["ccy"]][m]
            fee_exp += subs_usd[s][m]["fee_exp"] \
                + (fees_true[s][m] - fees_booked_g[s][m]) * avg[p["ccy"]][m]
            ap_usd += subs_usd[s][m]["ic_ap"] + (ar_true - ap) * spot[p["ccy"]][m]
        worst = max(worst, abs(parent[m]["fee_inc"] - fee_exp),
                    abs(parent[m]["ic_ar"] - ap_usd))
    add("post-top-side, fee and balance eliminations net to zero", worst < TOL,
        f"max residual ${worst:.6f}")

    # 7. consolidated revenue is external only
    worst = max(abs(consol[m]["rev"]
                    - parent[m]["rev"] - sum(subs_usd[s][m]["rev"] for s in SUBS))
                for m in REPORT_MONTHS)
    add("consolidated revenue = external revenue only", worst < TOL,
        f"max gap ${worst:.6f}")

    # 8. sanity: rates stayed inside a plausible band
    ok = all(0.85 < spot[c][m] / FX_START[c] < 1.15 for c in FX_START for m in MONTHS)
    add("FX paths within +/-15% of opening (sanity)", ok, "seeded walk bounded")
    return checks


# ------------------------------------------------------------------- output --
def fy(consol, key):
    return sum(consol[m][key] for m in REPORT_MONTHS)


def write_data(ledgers, parent, fees_true, fees_booked, spot, avg):
    d = Path(__file__).parent / "data"
    d.mkdir(exist_ok=True)
    with open(d / "fx_rates.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "ccy", "avg_usd", "eom_usd"])
        for c in FX_START:
            for m in MONTHS:
                w.writerow([m, c, f"{avg[c][m]:.6f}", f"{spot[c][m]:.6f}"])
    with open(d / "trial_balances.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "entity", "account", "amount_lc"])
        for s, months in ledgers.items():
            for m, led in months.items():
                for k, v in led.items():
                    w.writerow([m, s, k, f"{v:.2f}"])
        for m, led in parent.items():
            for k, v in led.items():
                w.writerow([m, "US", k, f"{v:.2f}"])
    with open(d / "intercompany.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "sub", "fee_lc_true", "fee_lc_booked"])
        for s in SUBS:
            for m in MONTHS:
                w.writerow([m, s, f"{fees_true[s][m]:.2f}", f"{fees_booked[s][m]:.2f}"])


def print_report(consol, subs_usd, breaks, checks, out=print):
    dec = "2025-12"
    out("CONSOLIDATION — FY2025 (USD)")
    out(f"  Consolidated revenue        ${fy(consol, 'rev')/1e6:,.1f}M")
    out(f"  Consolidated net income     ${fy(consol, 'ni')/1e6:,.2f}M")
    out(f"  CTA at Dec-25 (OCI)         ${consol[dec]['cta']/1e6:,.2f}M")
    out(f"  FX in P&L, FY               ${fy(consol, 'fx_pl')/1e3:,.0f}K"
        "  (SG remeasurement + parent IC AR)")
    delta_cta = consol[dec]["cta"] - consol[REPORT_MONTHS[0]]["cta"]
    out(f"  CTA movement in FY2025      ${delta_cta/1e6:,.2f}M — equity moved,"
        " P&L did not")
    for b in breaks:
        out(f"  IC BREAK  {b['pair']} {b['month']}  {b['ccy']} "
            f"{b['diff_lc']:,.0f}  divisible by 9 -> transposition suspect;"
            " top-side posted, reversed next month")
    out("")
    for name, ok, detail in checks:
        out(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    out("")
    out("  " + ("ALL CHECKS PASS" if all(c[1] for c in checks) else "FAILURES PRESENT"))


def svg_line(series, w=940, h=210, pad=34, colors=None, labels=None):
    """Multi-series indexed line chart, inline SVG."""
    all_v = [v for s in series for v in s]
    lo, hi = min(all_v), max(all_v)
    rng = (hi - lo) or 1
    n = len(series[0])
    def pt(i, v):
        x = pad + i * (w - 2 * pad) / (n - 1)
        y = h - pad - (v - lo) / rng * (h - 2 * pad)
        return f"{x:.1f},{y:.1f}"
    out = [f'<svg viewBox="0 0 {w} {h}" role="img">']
    for gy in range(5):
        y = pad + gy * (h - 2 * pad) / 4
        v = hi - gy * rng / 4
        out.append(f'<line x1="{pad}" y1="{y:.0f}" x2="{w-pad}" y2="{y:.0f}" '
                   'stroke="var(--grid)" stroke-width="1"/>')
        out.append(f'<text x="{pad-6}" y="{y+4:.0f}" text-anchor="end" '
                   f'font-size="10" fill="var(--mut)">{v:.2f}</text>')
    for si, s in enumerate(series):
        pts = " ".join(pt(i, v) for i, v in enumerate(s))
        out.append(f'<polyline points="{pts}" fill="none" '
                   f'stroke="{colors[si]}" stroke-width="2"/>')
        out.append(f'<text x="{w-pad+4}" y="{float(pt(n-1, s[-1]).split(",")[1])+4}" '
                   f'font-size="11" fill="{colors[si]}">{labels[si]}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_bars(vals, w=940, h=210, pad=34, months=None):
    """Monthly CTA movement bars, green positive / red negative."""
    hi = max(max(vals), 0)
    lo = min(min(vals), 0)
    rng = (hi - lo) or 1
    zero_y = pad + hi / rng * (h - 2 * pad)
    bw = (w - 2 * pad) / len(vals) * 0.62
    out = [f'<svg viewBox="0 0 {w} {h}" role="img">',
           f'<line x1="{pad}" y1="{zero_y:.0f}" x2="{w-pad}" y2="{zero_y:.0f}" '
           'stroke="var(--grid)"/>']
    for i, v in enumerate(vals):
        x = pad + (i + 0.19) * (w - 2 * pad) / len(vals)
        bh = abs(v) / rng * (h - 2 * pad)
        y = zero_y - bh if v > 0 else zero_y
        col = "var(--pos)" if v > 0 else "var(--neg)"
        out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bw:.0f}" '
                   f'height="{max(bh,1):.0f}" fill="{col}" rx="2"/>')
        out.append(f'<text x="{x+bw/2:.0f}" y="{h-8}" text-anchor="middle" '
                   f'font-size="9" fill="var(--mut)">{months[i][5:]}</text>')
    out.append("</svg>")
    return "".join(out)


def write_html(path, consol, subs_usd, parent, breaks, checks, spot):
    dec = "2025-12"
    jan = REPORT_MONTHS[0]
    idx_series = [[spot[c][m] / FX_START[c] for m in REPORT_MONTHS]
                  for c in ("GBP", "JPY", "SGD")]
    rates_svg = svg_line(idx_series, colors=["var(--line)", "var(--neg)", "var(--pos)"],
                         labels=["GBP", "JPY", "SGD"])
    cta_moves = []
    prevm = MONTHS[1]
    for m in REPORT_MONTHS:
        cta_moves.append(consol[m]["cta"] - consol[prevm]["cta"])
        prevm = m
    cta_svg = svg_bars(cta_moves, months=REPORT_MONTHS)

    def usd(v, k=False):
        if k:
            return f"${v/1e3:,.0f}K"
        return f"${v/1e6:,.2f}M"

    def _assets(e, m):
        if "assets" in e[m]:
            return e[m]["assets"]
        return (e[m]["cash"] + e[m]["ar"] + e[m]["fa"] - e[m]["accdep"]
                + e[m]["ic_ar"] + e[m]["inv"])

    ws_rows = ""
    line_defs = [
        ("Revenue", lambda e, m: e[m]["rev"], "rev"),
        ("Net income", lambda e, m: e[m]["ni"], "ni"),
        ("Assets", _assets, "assets"),
        ("Liabilities", lambda e, m: e[m]["liabs"] if "liabs" in e[m]
            else e[m]["ap"], "liabs"),
    ]
    for label, fn, ckey in line_defs:
        cells = "".join(f"<td>{usd(fn(src, dec))}</td>" for src in
                        (parent, subs_usd['UK'], subs_usd['JP'], subs_usd['SG']))
        elim = {"rev": -consol[dec]["fee_elim"], "ni": 0.0,
                "assets": -(parent[dec]["ic_ar"] + parent[dec]["inv"]),
                "liabs": -(parent[dec]["ic_ar"])}[ckey]
        ws_rows += (f"<tr><td>{label}</td>{cells}"
                    f"<td class='mut'>{usd(elim)}</td>"
                    f"<td><b>{usd(consol[dec][ckey])}</b></td></tr>")

    b = breaks[0]
    checks_html = "".join(
        f"<li><b class='{'ok' if ok else 'bad'}'>{'PASS' if ok else 'FAIL'}</b> "
        f"{name} <span class='mut'>— {detail}</span></li>"
        for name, ok, detail in checks)

    delta_cta = consol[dec]["cta"] - consol[jan]["cta"]
    sg_fy = subs_usd["SG"][dec]["fx_plug"] - subs_usd["SG"][MONTHS[1]]["fx_plug"]
    html = f"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ASC 830 consolidation — FY2025</title>
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
  .flag {{ background:color-mix(in srgb, var(--neg) 9%, transparent); }}
  .note {{ font-size:12.5px; color:var(--mut); margin-top:8px; max-width:88ch; }}
  ul.checks {{ list-style:none; padding:0; margin:0; font-size:13px; }}
  ul.checks li {{ padding:5px 0; border-bottom:1px solid var(--bd); }}
  svg {{ width:100%; height:auto; display:block; }}
</style>
<div class="wrap">
  <h1>Multi-Entity Consolidation — ASC 830</h1>
  <p class="sub">US parent + UK Ltd (GBP functional, translated) + Japan KK
    (JPY functional, translated) + Singapore Pte (USD functional, remeasured).
    Intercompany management fees invoiced in local currency, settled two months
    in arrears. All figures synthetic and seeded; every check below re-runs
    before this page publishes.</p>

  <div class="kpis">
    <div class="kpi"><div class="v">{usd(fy(consol,'rev'), False)[:-1]}</div>
      <div class="l">Consolidated revenue, FY2025 — external only, fees eliminated</div></div>
    <div class="kpi"><div class="v">{usd(fy(consol,'ni'))}</div>
      <div class="l">Consolidated net income, FY2025</div></div>
    <div class="kpi"><div class="v">{usd(consol[dec]['cta'])}</div>
      <div class="l">CTA at Dec-25 — in OCI, proven two ways monthly</div></div>
    <div class="kpi"><div class="v">{usd(fy(consol,'fx_pl'), True)}</div>
      <div class="l">FX in P&amp;L, FY2025 — SG remeasurement + parent IC receivables</div></div>
    <div class="kpi"><div class="v">1</div>
      <div class="l">Intercompany break caught — ¥27,000, divisible by 9</div></div>
    <div class="kpi"><div class="v">12/12</div>
      <div class="l">Months where consolidated A = L + E to the cent</div></div>
  </div>

  <h2>The year in rates — USD per unit, indexed to Jan</h2>
  <div class="card">{rates_svg}
    <p class="note">The yen weakened ~{(1-spot['JPY'][dec]/FX_START['JPY'])*100:.0f}%
      over the year. That is why consolidated equity moved
      {usd(delta_cta)} with zero P&amp;L impact — the answer to "why did equity
      fall when we made money" is translation, not performance.</p></div>

  <h2>CTA movement by month (UK + JP, USD)</h2>
  <div class="card">{cta_svg}
    <p class="note">Every bar is computed twice: as the balance-sheet plug and
      as the analytical roll-forward (opening net assets × spot move + NI ×
      (spot − avg)). Validation fails if they diverge by a cent. A plug always
      balances — that is exactly why it cannot be the only computation.</p></div>

  <h2>December consolidation worksheet (USD)</h2>
  <div class="card"><table>
    <tr><th></th><th>US parent</th><th>UK</th><th>Japan</th><th>Singapore</th>
        <th>Eliminations</th><th>Consolidated</th></tr>
    {ws_rows}
  </table>
  <p class="note">Eliminations: management fees (income vs expense at the same
    average rate), intercompany receivable vs payable (both at spot), parent
    investment vs subsidiary capital (both at historical). The parent's FX
    gain on local-currency IC receivables does <b>not</b> eliminate — it is a
    real ASC 830-20 P&amp;L item, reported in "FX in P&amp;L" above.</p></div>

  <h2>Intercompany matrix — the November break</h2>
  <div class="card"><table>
    <tr><th>Pair</th><th>Month</th><th>Parent AR (LC)</th><th>Sub AP (LC)</th>
        <th>Difference</th><th>Signature</th></tr>
    <tr class="flag"><td>{b['pair']}</td><td>{b['month']}</td>
      <td>booked correctly</td><td>under-accrued</td>
      <td><b>¥{b['diff_lc']:,.0f}</b></td>
      <td>÷ 9 = {b['diff_lc']/9:,.0f} — transposition suspect</td></tr>
  </table>
  <p class="note">Japan accrued the November management fee with two digits
    transposed. A transposition error is always divisible by 9 — the oldest
    trick in the reconciler's book, and the matrix applies it automatically.
    The engine posted a top-side accrual in November and reversed it in
    December when Japan's own catch-up entry landed. Every other pair nets to
    zero in all twelve months.</p></div>

  <h2>Same arithmetic, different geography</h2>
  <div class="card"><table>
    <tr><th></th><th>UK / Japan</th><th>Singapore</th></tr>
    <tr><td>Books kept in</td><td>GBP / JPY</td><td>SGD</td></tr>
    <tr><td>Functional currency</td><td>local</td><td><b>USD</b></td></tr>
    <tr><td>Method</td><td>Translation (current-rate)</td><td>Remeasurement</td></tr>
    <tr><td>Rate effect lands in</td><td><b>OCI (CTA)</b></td><td><b>P&amp;L</b></td></tr>
    <tr><td>FY2025 effect</td><td>{usd(delta_cta)}</td><td>{usd(sg_fy, True)}</td></tr>
  </table>
  <p class="note">Singapore deliberately holds no nonmonetary assets, so its
    remeasurement formula is arithmetically identical to CTA. The only
    difference is where it lands — and that is decided by functional currency,
    not by geography. This is the judgment ASC 830 actually asks for.</p></div>

  <h2>Validation — re-run before every publish</h2>
  <div class="card"><ul class="checks">{checks_html}</ul></div>

  <p class="note" style="margin-top:26px">Synthetic, seeded data
    (<code>random.seed(830)</code>). Generator, engine, and checks:
    <a href="https://github.com/Lumimama/finance/tree/main/consolidation-fx"
       style="color:var(--line)">github.com/Lumimama/finance/consolidation-fx</a>.</p>
</div>
"""
    Path(path).write_text(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--html")
    ap.add_argument("--report")
    args = ap.parse_args()

    spot, avg = gen_rates()
    ledgers, fees_true, fees_booked = gen_ledgers()
    parent, _ = gen_parent(spot, avg, fees_true)
    subs_usd = {s: translate_sub(s, ledgers, spot, avg) for s in SUBS}
    consol, breaks = consolidate(parent, subs_usd, fees_true, fees_booked, avg, spot)
    checks = run_checks(ledgers, parent, subs_usd, consol, breaks, fees_true, fees_booked, spot, avg)
    write_data(ledgers, parent, fees_true, fees_booked, spot, avg)

    if args.report:
        lines = []
        print_report(consol, subs_usd, breaks, checks, out=lines.append)
        Path(args.report).write_text("\n".join(lines) + "\n")
    print_report(consol, subs_usd, breaks, checks)
    if args.html:
        write_html(args.html, consol, subs_usd, parent, breaks, checks, spot)
        print(f"  wrote {args.html}")
    if args.validate and not all(c[1] for c in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
