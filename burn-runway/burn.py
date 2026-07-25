"""
Cash Burn & Runway Monitor
==========================
The standing weekly artifact a CEO actually glances at: burn, runway, the
direction runway is moving, and the date the fundraise clock starts.

Four things this shows that a KPI tile can't:

    GROSS vs NET BURN     gross burn (total cash out) is the number that
                          doesn't lie when a one-time collection flatters net
    TRAILING 3-MO BURN    the quotable number; single months are noise
    RUNWAY TRAJECTORY     not "14 months today" but whether runway is
                          lengthening or shrinking month over month --
                          a company can grow revenue while runway shrinks
    THE FUNDRAISE TRIGGER runway floor (months) + raise duration = the date
                          you must START raising, marked on the chart

Plus the burn bridge: why this month's net burn differs from last month's,
by driver -- and the bridge must tie to the actual change, to the cent.

Run:  python3 burn.py
      python3 burn.py --validate
      python3 burn.py --html examples/burn_dashboard.html

No dependencies. Python 3.10+. All data synthetic, seeded.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

random.seed(20260731)

MONTHS = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13)][:19]
RUNWAY_FLOOR_MONTHS = 12      # board policy: never let runway fall below this
RAISE_DURATION_MONTHS = 6     # realistic time to close a round
OPENING_CASH = 31_500_000

CATEGORIES = ["payroll", "cloud_compute", "sales_marketing", "g_and_a",
              "professional_fees"]


def make_series():
    """Monthly cash ledger: collections in, spend out by category."""
    rows = []
    collections = 1_450_000
    spend = {"payroll": 1_480_000, "cloud_compute": 410_000,
             "sales_marketing": 520_000, "g_and_a": 240_000,
             "professional_fees": 95_000}
    cash = OPENING_CASH
    for mi, month in enumerate(MONTHS):
        collections *= random.uniform(1.02, 1.07)          # revenue growing
        for k in spend:
            drift = {"payroll": 1.030, "cloud_compute": 1.045,
                     "sales_marketing": 1.015, "g_and_a": 1.008,
                     "professional_fees": 1.0}[k]
            spend[k] *= drift * random.uniform(0.96, 1.05)
        row = {"month": month, "collections": round(collections, 2)}
        # one-time events that make single-month net burn lie:
        oneoff_in = 0.0
        if month == "2026-02":
            oneoff_in = 2_400_000        # annual prepay collected early
        if month == "2026-05":
            row_extra = 380_000          # audit + legal one-time
            spend_extra = {"professional_fees": spend["professional_fees"] + row_extra}
        for k in CATEGORIES:
            row[k] = round(spend[k] + (380_000 if (k == "professional_fees"
                            and month == "2026-05") else 0), 2)
        row["oneoff_collections"] = round(oneoff_in, 2)
        gross_out = sum(row[k] for k in CATEGORIES)
        net = row["collections"] + row["oneoff_collections"] - gross_out
        cash += net
        row["gross_burn"] = round(gross_out, 2)
        row["net_burn"] = round(-net, 2)          # positive = burning
        row["ending_cash"] = round(cash, 2)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
def analyze(rows):
    for i, r in enumerate(rows):
        window = rows[max(0, i - 2):i + 1]
        r["t3_net_burn"] = sum(x["net_burn"] for x in window) / len(window)
        r["runway_months"] = (r["ending_cash"] / r["t3_net_burn"]
                              if r["t3_net_burn"] > 0 else float("inf"))
    latest = rows[-1]
    # fundraise trigger: the month runway is projected to hit
    # floor + raise duration, assuming trailing burn holds.
    threshold = RUNWAY_FLOOR_MONTHS + RAISE_DURATION_MONTHS
    months_until_trigger = max(0.0, latest["runway_months"] - threshold)
    return {
        "latest": latest,
        "trigger_threshold": threshold,
        "months_until_trigger": months_until_trigger,
        "runway_delta_3mo": rows[-1]["runway_months"] - rows[-4]["runway_months"],
    }


def bridge(rows, i=None):
    """Why did net burn change vs last month, by driver? Must tie."""
    i = len(rows) - 1 if i is None else i
    cur, prev = rows[i], rows[i - 1]
    steps = [("Collections", -(cur["collections"] - prev["collections"])),
             ("One-time collections", -(cur["oneoff_collections"] - prev["oneoff_collections"]))]
    for k in CATEGORIES:
        steps.append((k.replace("_", " ").title(), cur[k] - prev[k]))
    total = sum(v for _, v in steps)
    return steps, total, cur["net_burn"] - prev["net_burn"]


# ---------------------------------------------------------------------------
def money(x): return f"${x/1e6:,.2f}M" if abs(x) >= 1e6 else f"${x/1e3:,.0f}K"


def print_report(rows) -> None:
    w = 100
    a = analyze(rows)
    latest = a["latest"]
    print("=" * w)
    print(f"CASH BURN & RUNWAY  |  as of {latest['month']}")
    print("=" * w)
    print(f"  cash                        {money(latest['ending_cash']):>12}")
    print(f"  net burn (month)            {money(latest['net_burn']):>12}")
    print(f"  net burn (trailing 3-mo)    {money(latest['t3_net_burn']):>12}   <- the quotable number")
    print(f"  gross burn (month)          {money(latest['gross_burn']):>12}")
    print(f"  runway at trailing burn     {latest['runway_months']:>10.1f}mo")
    print(f"  runway 3-mo trend           {a['runway_delta_3mo']:>+10.1f}mo   "
          f"({'lengthening' if a['runway_delta_3mo'] > 0 else 'SHRINKING'})")
    print(f"  fundraise trigger           {a['months_until_trigger']:>10.1f}mo away   "
          f"(floor {RUNWAY_FLOOR_MONTHS}mo + raise {RAISE_DURATION_MONTHS}mo)")

    print(f"\n  {'month':<9}{'collections':>13}{'gross burn':>12}{'net burn':>11}"
          f"{'t3 burn':>11}{'cash':>11}{'runway':>9}")
    print("-" * w)
    for r in rows[-9:]:
        print(f"  {r['month']:<9}{money(r['collections']+r['oneoff_collections']):>13}"
              f"{money(r['gross_burn']):>12}{money(r['net_burn']):>11}"
              f"{money(r['t3_net_burn']):>11}{money(r['ending_cash']):>11}"
              f"{r['runway_months']:>8.1f}m")

    steps, total, actual = bridge(rows)
    print(f"\nBURN BRIDGE  ({rows[-2]['month']} -> {rows[-1]['month']}: net burn "
          f"{money(rows[-2]['net_burn'])} -> {money(rows[-1]['net_burn'])})")
    print("-" * w)
    for label, v in steps:
        if abs(v) > 100:
            print(f"  {label:<24}{'+' if v > 0 else ''}{money(v) if abs(v)>=1e3 else f'${v:,.0f}':>12}")
    print(f"  {'Total change':<24}{money(total):>12}   (ties: {abs(total-actual) < 0.01})")
    print()


def validate(rows) -> None:
    print("VALIDATION")
    print("-" * 86)
    ok = True
    # 1. cash ledger reconciles
    cash = OPENING_CASH
    worst = 0.0
    for r in rows:
        cash += r["collections"] + r["oneoff_collections"] - r["gross_burn"]
        worst = max(worst, abs(cash - r["ending_cash"]))
    ok &= worst < 0.01
    print(f"  [{'ok ' if worst < 0.01 else 'MISS'}] cash ledger reconciles every "
          f"month (max diff ${worst:.4f})")
    # 2. net burn definition consistent
    worst2 = max(abs(r["net_burn"] - (r["gross_burn"] - r["collections"]
                 - r["oneoff_collections"])) for r in rows)
    ok &= worst2 < 0.01
    print(f"  [{'ok ' if worst2 < 0.01 else 'MISS'}] net burn = gross burn - "
          f"collections on every row (max diff ${worst2:.4f})")
    # 3. every month's bridge ties
    worst3 = 0.0
    for i in range(1, len(rows)):
        steps, total, actual = bridge(rows, i)
        worst3 = max(worst3, abs(total - actual))
    ok &= worst3 < 0.01
    print(f"  [{'ok ' if worst3 < 0.01 else 'MISS'}] burn bridge ties to the "
          f"change in net burn, every month (max diff ${worst3:.4f})")
    # 4. the one-off distortion is visible: Feb-26 monthly runway vs t3
    feb = next(r for r in rows if r["month"] == "2026-02")
    mono = feb["ending_cash"] / feb["net_burn"] if feb["net_burn"] > 0 else float("inf")
    ok &= (mono == float("inf") or mono > feb["runway_months"] * 1.5)
    print(f"  [{'ok ' if ok else 'MISS'}] one-time collection makes single-month "
          f"runway lie ({'infinite' if mono == float('inf') else f'{mono:.0f}mo'} "
          f"vs {feb['runway_months']:.1f}mo trailing) -- the reason t3 is the "
          f"quotable number")
    print("-" * 86)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(rows, path: Path) -> None:
    a = analyze(rows)
    latest = a["latest"]
    W, H, PL, PT, PB = 880, 280, 84, 22, 40
    pw, ph = W - PL - 24, H - PT - PB
    n = len(rows)

    def x(i): return PL + pw * i / (n - 1)

    # burn bars: gross + net, with t3 line
    hi_b = max(r["gross_burn"] for r in rows) * 1.15
    def yb(v): return PT + ph * (1 - max(v, 0) / hi_b)
    bw = pw / n * 0.32
    bars = ""
    for i, r in enumerate(rows):
        bars += (f'<rect x="{x(i)-bw:.1f}" y="{yb(r["gross_burn"]):.1f}" width="{bw:.1f}" '
                 f'height="{yb(0)-yb(r["gross_burn"]):.1f}" fill="var(--mut)" opacity="0.45" rx="1.5"/>')
        v = max(r["net_burn"], 0)
        bars += (f'<rect x="{x(i):.1f}" y="{yb(v):.1f}" width="{bw:.1f}" '
                 f'height="{yb(0)-yb(v):.1f}" fill="var(--neg)" opacity="0.85" rx="1.5"/>')
    t3 = " ".join(f"{x(i)+bw/2:.1f},{yb(r['t3_net_burn']):.1f}" for i, r in enumerate(rows))
    grid_b = "".join(
        f'<line x1="{PL}" y1="{yb(hi_b*f):.1f}" x2="{W-24}" y2="{yb(hi_b*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{yb(hi_b*f)+4:.1f}" text-anchor="end" class="tick">${hi_b*f/1e6:.1f}M</text>'
        for f in (0, .5, 1.0))
    ticks = "".join(f'<text x="{x(i):.1f}" y="{H-16}" text-anchor="middle" class="tick">{rows[i]["month"][2:]}</text>'
                    for i in range(0, n, 3))

    # runway trajectory with trigger threshold
    finite_rw = [min(r["runway_months"], 40) for r in rows]
    hi_r = max(finite_rw) * 1.15
    def yr(v): return PT + ph * (1 - min(v, hi_r) / hi_r)
    rw_line = " ".join(f"{x(i):.1f},{yr(v):.1f}" for i, v in enumerate(finite_rw))
    thr = a["trigger_threshold"]
    trigger_line = (f'<line x1="{PL}" y1="{yr(thr):.1f}" x2="{W-24}" y2="{yr(thr):.1f}" class="trig"/>'
                    f'<text x="{W-28}" y="{yr(thr)-7:.1f}" text-anchor="end" class="tick" fill="var(--neg)">'
                    f'fundraise trigger: {thr}mo (floor {RUNWAY_FLOOR_MONTHS} + raise {RAISE_DURATION_MONTHS})</text>')
    grid_r = "".join(
        f'<line x1="{PL}" y1="{yr(hi_r*f):.1f}" x2="{W-24}" y2="{yr(hi_r*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{yr(hi_r*f)+4:.1f}" text-anchor="end" class="tick">{hi_r*f:.0f}mo</text>'
        for f in (0, .5, 1.0))

    steps, total, actual = bridge(rows)
    br_rows = "".join(
        f"<tr><td>{label}</td><td class='n {'neg' if v > 0 else 'pos'}'>"
        f"{'+' if v > 0 else '−'}${abs(v):,.0f}</td></tr>"
        for label, v in steps if abs(v) > 100)

    tbl = "".join(
        f"<tr><td>{r['month']}</td>"
        f"<td class='n'>${(r['collections']+r['oneoff_collections'])/1e6:,.2f}</td>"
        f"<td class='n'>${r['gross_burn']/1e6:,.2f}</td>"
        f"<td class='n'>${r['net_burn']/1e6:,.2f}</td>"
        f"<td class='n'>${r['t3_net_burn']/1e6:,.2f}</td>"
        f"<td class='n'>${r['ending_cash']/1e6:,.1f}</td>"
        f"<td class='n b'>{r['runway_months']:,.1f}</td></tr>"
        for r in rows[-12:])

    shrinking = a["runway_delta_3mo"] < 0
    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Burn &amp; Runway · {latest['month']}</title>
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
  .wrap {{ max-width:980px; margin:0 auto; }}
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
  .warn .v {{ color:var(--neg); }} .good .v {{ color:var(--pos); }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .trig {{ stroke:var(--neg); stroke-width:1.5; stroke-dasharray:5 4; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .leg {{ font-size:12px; font-weight:600; }}
  .cols {{ display:grid; grid-template-columns:2fr 1fr; gap:16px; }}
  @media (max-width:820px) {{ .cols {{ grid-template-columns:1fr; }} }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
  th,td {{ padding:6px 10px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .b {{ font-weight:600; }} .neg {{ color:var(--neg); }} .pos {{ color:var(--pos); }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Cash Burn &amp; Runway</h1>
  <div class="sub">As of {latest['month']} · trailing-burn basis · synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Cash</div><div class="v">${latest['ending_cash']/1e6:,.1f}M</div></div>
    <div class="kpi"><div class="k">Net burn (t3)</div><div class="v">${latest['t3_net_burn']/1e6:,.2f}M</div>
      <div class="n2">month: ${latest['net_burn']/1e6:,.2f}M</div></div>
    <div class="kpi"><div class="k">Gross burn</div><div class="v">${latest['gross_burn']/1e6:,.2f}M</div>
      <div class="n2">the number that doesn't lie</div></div>
    <div class="kpi"><div class="k">Runway</div><div class="v">{latest['runway_months']:,.1f} mo</div>
      <div class="n2">at trailing 3-mo burn</div></div>
    <div class="kpi {'warn' if shrinking else 'good'}"><div class="k">Runway trend (3mo)</div>
      <div class="v">{a['runway_delta_3mo']:+.1f} mo</div>
      <div class="n2">{'shrinking' if shrinking else 'lengthening'}</div></div>
    <div class="kpi warn"><div class="k">Fundraise trigger</div>
      <div class="v">{a['months_until_trigger']:,.1f} mo</div>
      <div class="n2">until raise must start</div></div>
  </div>

  <h2>Gross vs net burn, with trailing 3-month line</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid_b}{bars}
    <polyline points="{t3}" fill="none" stroke="var(--fg)" stroke-width="2"/>
    {ticks}
    <text x="{PL}" y="14" class="leg"><tspan fill="var(--mut)">■ gross</tspan>
    <tspan fill="var(--neg)"> ■ net</tspan><tspan> — t3 net</tspan></text></svg></div>
  <div class="note">2026-02: a one-time annual prepay makes single-month net
    burn go briefly negative — and single-month runway infinite. The trailing
    line barely moves. That contrast is why the t3 number is the quotable one.</div>

  <h2>Runway trajectory, with the fundraise trigger</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid_r}{trigger_line}
    <polyline points="{rw_line}" fill="none" stroke="var(--line)" stroke-width="2.5"/>
    {ticks}</svg></div>
  <div class="note">The slope matters more than the level: a company can grow
    revenue while runway shrinks. When the blue line crosses the dashed one,
    the raise must begin — that crossing date is the only date on this page a
    board truly needs.</div>

  <div class="cols">
    <div>
      <h2>Monthly detail — $M</h2>
      <div class="tbl"><table>
        <thead><tr><th>Month</th><th class="n">Collections</th><th class="n">Gross burn</th>
          <th class="n">Net burn</th><th class="n">T3 burn</th><th class="n">Cash</th>
          <th class="n">Runway mo</th></tr></thead>
        <tbody>{tbl}</tbody></table></div>
    </div>
    <div>
      <h2>Burn bridge — {rows[-2]['month']} → {rows[-1]['month']}</h2>
      <div class="tbl"><table>
        <thead><tr><th>Driver</th><th class="n">Δ net burn</th></tr></thead>
        <tbody>{br_rows}
        <tr><td class="b">Total (ties)</td><td class="n b">{'+' if total > 0 else '−'}${abs(total):,.0f}</td></tr>
        </tbody></table></div>
    </div>
  </div>

  <footer>Generated by burn.py · ledger reconciles and every month's bridge
    ties (run --validate) · all data synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Burn and runway monitor")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    rows = make_series()
    analyze(rows)
    print_report(rows)
    if args.validate:
        validate(rows)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(rows, args.html)


if __name__ == "__main__":
    main()
