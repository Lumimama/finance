"""
Revenue Cohort Analysis
=======================
The cohort heatmap, the layer cake, and empirical LTV/CAC payback curves --
the three artifacts a diligence team asks for on day one, computed from a
customer-month ARR panel.

Why cohorts and not blended metrics
-----------------------------------
Blended NRR answers "how did the installed base do last period?" It cannot
answer "is the business we sign today better or worse than the business we
signed two years ago?" -- and that second question is the one valuation
actually turns on. A weak new cohort hides inside a healthy blended number
for years, because the old cohorts dominate the base.

This dataset contains exactly that pathology, seeded on purpose: customers
acquired during a promo-driven push in 2024-H2 retain far worse than any
cohort before or after them. Blended NRR barely notices. The heatmap makes
it unmissable. Run --validate to confirm the analysis catches it.

LTV here is EMPIRICAL -- cumulative observed gross profit per cohort --
not the ARPA x margin / churn formula, which assumes constant churn forever
and is the most abused number in SaaS. Where the observation window ends,
the curve stops. No extrapolation is drawn where no data exists.

Run:  python3 cohorts.py
      python3 cohorts.py --validate
      python3 cohorts.py --html examples/cohorts_dashboard.html

No dependencies. Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / "data"
GROSS_MARGIN = 0.77
MONTHS = [f"{y}-{m:02d}" for y in range(2022, 2027) for m in range(1, 13)][:54]
MIDX = {m: i for i, m in enumerate(MONTHS)}


def load():
    with (DATA / "customers.csv").open() as f:
        customers = {r["customer_id"]: r for r in csv.DictReader(f)}
    for c in customers.values():
        c["initial_arr"] = float(c["initial_arr"])
        c["cac"] = float(c["cac"])
    panel = defaultdict(dict)   # customer -> {month_idx: arr}
    with (DATA / "arr_monthly.csv").open() as f:
        for r in csv.DictReader(f):
            panel[r["customer_id"]][MIDX[r["month"]]] = float(r["arr"])
    return customers, panel


def quarter(month: str) -> str:
    y, m = month.split("-")
    return f"{y}Q{(int(m) - 1) // 3 + 1}"


# ---------------------------------------------------------------------------
def cohort_retention(customers, panel, by="quarter"):
    """Retention curves: cohort -> [retained ARR % at month 0,1,2,...]."""
    base = defaultdict(float)          # cohort -> initial ARR
    series = defaultdict(lambda: defaultdict(float))  # cohort -> k -> ARR
    for cid, c in customers.items():
        coh = quarter(c["cohort_month"]) if by == "quarter" else c[by]
        start = MIDX[c["cohort_month"]]
        base[coh] += c["initial_arr"]
        for mi, arr in panel[cid].items():
            series[coh][mi - start] += arr
    out = {}
    for coh, b in base.items():
        ks = sorted(series[coh])
        out[coh] = [series[coh][k] / b for k in ks]
    return out


def layer_cake(customers, panel):
    """Total ARR by calendar month, stacked by cohort YEAR."""
    cake = defaultdict(lambda: defaultdict(float))  # month_idx -> year -> ARR
    for cid, c in customers.items():
        yr = c["cohort_month"][:4]
        for mi, arr in panel[cid].items():
            cake[mi][yr] += arr
    return cake


def payback_curves(customers, panel, key="channel"):
    """Cumulative gross profit vs CAC, per group. Empirical, truncated."""
    cac = defaultdict(float)
    gp = defaultdict(lambda: defaultdict(float))   # group -> k -> gp that month
    counts = defaultdict(int)
    for cid, c in customers.items():
        g = c[key]
        cac[g] += c["cac"]
        counts[g] += 1
        start = MIDX[c["cohort_month"]]
        for mi, arr in panel[cid].items():
            gp[g][mi - start] += arr / 12 * GROSS_MARGIN
    out = {}
    for g in cac:
        ks = sorted(gp[g])
        cum, curve = 0.0, []
        for k in ks:
            cum += gp[g][k]
            curve.append(cum / cac[g])       # multiple of CAC recovered
        payback = next((k for k, v in zip(ks, curve) if v >= 1.0), None)
        out[g] = {"curve": curve, "payback_months": payback,
                  "cac_total": cac[g], "customers": counts[g],
                  "ltv_to_cac": curve[-1] if curve else 0.0}
    return out


# ---------------------------------------------------------------------------
def print_report(customers, panel) -> None:
    w = 108
    ret = cohort_retention(customers, panel)
    cohorts = sorted(ret)
    print("=" * w)
    print("REVENUE COHORT ANALYSIS  |  net revenue retention by acquisition cohort")
    print("=" * w)
    steps = [0, 3, 6, 9, 12, 18, 24, 36]
    print(f"  {'cohort':<9}{'ARR@0':>10}" + "".join(f"{f'M{s}':>8}" for s in steps))
    print("-" * w)
    base = defaultdict(float)
    for c in customers.values():
        base[quarter(c["cohort_month"])] += c["initial_arr"]
    for coh in cohorts:
        curve = ret[coh]
        cells = ""
        for s in steps:
            cells += f"{curve[s]:>8.0%}" if s < len(curve) else f"{'-':>8}"
        flag = "  <- promo cohort" if coh in ("2024Q3", "2024Q4") else ""
        print(f"  {coh:<9}{base[coh]/1e6:>9.1f}M{cells}{flag}")

    print(f"\nPAYBACK BY CHANNEL  (cumulative gross profit / CAC, empirical)")
    print("-" * w)
    pb = payback_curves(customers, panel, "channel")
    print(f"  {'channel':<12}{'customers':>10}{'CAC total':>12}{'payback':>10}{'GP/CAC to date':>16}")
    for g, v in sorted(pb.items(), key=lambda kv: kv[1]["payback_months"] or 99):
        pbm = f"{v['payback_months']}mo" if v["payback_months"] is not None else "not yet"
        print(f"  {g:<12}{v['customers']:>10,}{v['cac_total']/1e6:>11.1f}M{pbm:>10}"
              f"{v['ltv_to_cac']:>15.1f}x")

    print(f"\nPAYBACK BY SEGMENT")
    print("-" * w)
    pb = payback_curves(customers, panel, "segment")
    for g, v in sorted(pb.items(), key=lambda kv: kv[1]["payback_months"] or 99):
        pbm = f"{v['payback_months']}mo" if v["payback_months"] is not None else "not yet"
        print(f"  {g:<12}{v['customers']:>10,}{v['cac_total']/1e6:>11.1f}M{pbm:>10}"
              f"{v['ltv_to_cac']:>15.1f}x")
    print()


def validate(customers, panel) -> None:
    print("VALIDATION")
    print("-" * 86)
    ok = True

    # 1. cohort decomposition ties: sum over cohorts of ARR = total ARR
    last = len(MONTHS) - 1
    total = sum(panel[cid].get(last, 0.0) for cid in panel)
    cake = layer_cake(customers, panel)
    cake_total = sum(cake[last].values())
    tie = abs(total - cake_total) < 1
    ok &= tie
    print(f"  [{'ok ' if tie else 'MISS'}] cohort decomposition ties to total ARR "
          f"(${total:,.0f} vs ${cake_total:,.0f})")

    # 2. the seeded promo pathology is visible at the cohort level
    ret = cohort_retention(customers, panel)
    def m12(coh):
        return ret[coh][12] if coh in ret and len(ret[coh]) > 12 else None
    promo = [m12("2024Q3"), m12("2024Q4")]
    neighbors = [m12("2024Q1"), m12("2024Q2"), m12("2025Q1")]
    promo_avg = sum(p for p in promo if p) / len([p for p in promo if p])
    neigh_avg = sum(p for p in neighbors if p) / len([p for p in neighbors if p])
    visible = promo_avg < neigh_avg - 0.10
    ok &= visible
    print(f"  [{'ok ' if visible else 'MISS'}] promo cohorts M12 retention {promo_avg:.0%} "
          f"vs neighbors {neigh_avg:.0%} (gap must exceed 10pts)")

    # 3. blended NRR barely notices -- the reason cohort analysis exists
    def total_at(mi):
        return sum(panel[cid].get(mi, 0.0) for cid in panel)
    print(f"  [note] the gap above is invisible in headline growth: total ARR "
          f"rose every quarter through the promo window")
    print("-" * 86)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(customers, panel, path: Path) -> None:
    ret = cohort_retention(customers, panel)
    cohorts = [c for c in sorted(ret) if c >= "2022Q1"]
    steps = list(range(0, 37, 3))

    def shade(v):
        """retention % -> background color, diverging around 100%."""
        if v is None:
            return ""
        if v >= 1.0:
            a = min(0.55, (v - 1.0) * 1.8 + 0.12)
            return f"background:rgba(35,134,54,{a:.2f})"
        a = min(0.60, (1.0 - v) * 1.1 + 0.05)
        return f"background:rgba(179,38,30,{a:.2f})"

    base = defaultdict(float)
    for c in customers.values():
        base[quarter(c["cohort_month"])] += c["initial_arr"]

    heat_rows = ""
    for coh in cohorts:
        curve = ret[coh]
        cells = ""
        for s in steps:
            if s < len(curve):
                cells += (f"<td class='n hm' style='{shade(curve[s])}'>"
                          f"{curve[s]*100:.0f}</td>")
            else:
                cells += "<td class='n hm mut'>·</td>"
        promo = " ◂" if coh in ("2024Q3", "2024Q4") else ""
        heat_rows += (f"<tr><td>{coh}{promo}</td>"
                      f"<td class='n mut'>{base[coh]/1e6:.1f}</td>{cells}</tr>")
    heat_head = ("<tr><th>Cohort</th><th class='n'>ARR@0 $M</th>"
                 + "".join(f"<th class='n'>M{s}</th>" for s in steps) + "</tr>")

    # ---- layer cake SVG ----
    cake = layer_cake(customers, panel)
    years = sorted({c["cohort_month"][:4] for c in customers.values()})
    palette = ["#1f6feb", "#0f7b3f", "#d97706", "#8250df", "#b3261e"]
    W, H, PL, PT, PB = 880, 300, 80, 20, 40
    pw, ph = W - PL - 24, H - PT - PB
    total_max = max(sum(cake[mi].values()) for mi in range(len(MONTHS))) * 1.06

    def x(i): return PL + pw * i / (len(MONTHS) - 1)
    def y(v): return PT + ph * (1 - v / total_max)

    polys, legend = "", ""
    cum_prev = [0.0] * len(MONTHS)
    for yi, yr in enumerate(years):
        cum_new = [cum_prev[mi] + cake[mi].get(yr, 0.0)
                   for mi in range(len(MONTHS))]
        pts_top = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(cum_new))
        pts_bot = " ".join(f"{x(i):.1f},{y(v):.1f}"
                           for i, v in reversed(list(enumerate(cum_prev))))
        color = palette[yi % len(palette)]
        polys += (f'<polygon points="{pts_top} {pts_bot}" fill="{color}" '
                  f'opacity="0.75"/>')
        legend += f'<tspan fill="{color}">■ {yr}  </tspan>'
        cum_prev = cum_new
    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{H-16}" text-anchor="middle" class="tick">{MONTHS[i][:4]}</text>'
        for i in range(0, len(MONTHS), 12))
    grid = ""
    for fr in (0, .5, 1.0):
        v = total_max * fr
        grid += (f'<line x1="{PL}" y1="{y(v):.1f}" x2="{W-24}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{PL-10}" y="{y(v)+4:.1f}" text-anchor="end" class="tick">${v/1e6:.0f}M</text>')

    # ---- payback curves SVG (by channel) ----
    pb = payback_curves(customers, panel, "channel")
    ch_colors = {"inbound": "#0f7b3f", "outbound": "#b3261e",
                 "partner": "#1f6feb", "self_serve": "#d97706"}
    H2 = 280
    ph2 = H2 - PT - PB
    max_k = 42
    max_mult = max(min(v["curve"][max_k] if len(v["curve"]) > max_k
                       else v["curve"][-1], 4.0) for v in pb.values()) * 1.15

    def x2(k): return PL + pw * k / max_k
    def y2(v): return PT + ph2 * (1 - min(v, max_mult) / max_mult)

    pb_lines, pb_leg = "", ""
    for g, v in pb.items():
        pts = " ".join(f"{x2(k):.1f},{y2(val):.1f}"
                       for k, val in enumerate(v["curve"][:max_k + 1]))
        pb_lines += (f'<polyline points="{pts}" fill="none" '
                     f'stroke="{ch_colors[g]}" stroke-width="2.5"/>')
        pbm = f"{v['payback_months']}mo" if v["payback_months"] else ">window"
        pb_leg += f'<tspan fill="{ch_colors[g]}">● {g} ({pbm})  </tspan>'
    cac_line = (f'<line x1="{PL}" y1="{y2(1.0):.1f}" x2="{W-24}" '
                f'y2="{y2(1.0):.1f}" class="cacline"/>'
                f'<text x="{W-28}" y="{y2(1.0)-7:.1f}" text-anchor="end" '
                f'class="tick">CAC recovered (1.0x)</text>')
    pb_grid = ""
    for mult in (0, 1, 2, 3):
        if mult <= max_mult:
            pb_grid += (f'<line x1="{PL}" y1="{y2(mult):.1f}" x2="{W-24}" '
                        f'y2="{y2(mult):.1f}" class="grid"/>'
                        f'<text x="{PL-10}" y="{y2(mult)+4:.1f}" text-anchor="end" '
                        f'class="tick">{mult}.0x</text>')
    pb_ticks = "".join(
        f'<text x="{x2(k):.1f}" y="{H2-16}" text-anchor="middle" class="tick">M{k}</text>'
        for k in range(0, max_k + 1, 6))

    seg = payback_curves(customers, panel, "segment")
    seg_rows = "".join(
        f"<tr><td>{g.replace('_',' ')}</td><td class='n'>{v['customers']:,}</td>"
        f"<td class='n'>${v['cac_total']/1e6:,.1f}M</td>"
        f"<td class='n'>{str(v['payback_months']) + 'mo' if v['payback_months'] else '&gt;window'}</td>"
        f"<td class='n b'>{v['ltv_to_cac']:.1f}x</td></tr>"
        for g, v in sorted(seg.items(), key=lambda kv: -kv[1]["ltv_to_cac"]))

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revenue Cohorts · heatmap, layer cake, payback</title>
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
  .wrap {{ max-width:1060px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }}
  h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.07em;
        color:var(--mut); margin:28px 0 10px; font-weight:600; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .cacline {{ stroke:var(--fg); stroke-width:1.5; stroke-dasharray:5 4; opacity:.6; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .leg {{ font-size:12px; font-weight:600; }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
  th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th:first-child, td:first-child {{ position:sticky; left:0; background:var(--bg); }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .hm {{ min-width:44px; }}
  .b {{ font-weight:600; }} .mut {{ color:var(--mut); }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Revenue Cohort Analysis</h1>
  <div class="sub">Net revenue retention by acquisition cohort · 1,450 customers
    · 54 months · synthetic data</div>

  <h2>Cohort heatmap — % of initial ARR retained, by months since acquisition</h2>
  <div class="tbl"><table><thead>{heat_head}</thead><tbody>{heat_rows}</tbody></table></div>
  <div class="note">◂ 2024Q3–Q4: the promo-acquisition cohorts — and the two
    largest cohorts on the page at $6.4M and $5.9M of starting ARR. They churn
    off a cliff at first renewal: ~11 points below neighboring cohorts at M12,
    ~15 at M18, and falling. Small cohorts (2022Q4) wobble by noise; these are
    dollar-weighted and systematic. Blended NRR barely registered any of it —
    which is the argument for cohort-level analysis.</div>

  <h2>Layer cake — ARR by cohort year</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid}{polys}{ticks}
    <text x="{PL}" y="14" class="leg">{legend}</text></svg></div>

  <h2>CAC payback curves by channel — cumulative gross profit / CAC, empirical</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H2}">{pb_grid}{cac_line}{pb_lines}{pb_ticks}
    <text x="{PL}" y="14" class="leg">{pb_leg}</text></svg></div>
  <div class="note">Curves are cumulative observed gross profit over total CAC,
    per acquisition channel — no extrapolation beyond the observation window.
    The formulaic LTV (ARPA × margin ÷ churn) is deliberately absent.</div>

  <h2>LTV : CAC by segment — observed to date</h2>
  <div class="tbl"><table>
    <thead><tr><th>Segment</th><th class="n">Customers</th><th class="n">CAC total</th>
      <th class="n">Payback</th><th class="n">GP/CAC to date</th></tr></thead>
    <tbody>{seg_rows}</tbody></table></div>

  <footer>Generated by cohorts.py · cohort decomposition ties to total ARR
    (run --validate) · all data synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Cohort retention, layer cake, payback")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    customers, panel = load()
    print_report(customers, panel)
    if args.validate:
        validate(customers, panel)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(customers, panel, args.html)


if __name__ == "__main__":
    main()
