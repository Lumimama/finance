"""
AI Infrastructure Metrics
=========================
The unit-economics layer between the P&L and the GPU cluster: 90 days of
daily ops data turned into the metrics an AI-native finance team actually
manages -- because "cloud compute" as one P&L line is where AI gross margin
goes to hide.

    COST SIDE      cost per 1K tokens (by model and blended), cost per
                   inference, GPU utilization, model mix
    REVENUE SIDE   revenue per 1K tokens, consumption vs committed-drawdown
                   revenue, API calls, DAU / MAU
    THE JOIN       gross margin after AI costs, daily -- the number that
                   decides whether usage growth is good news

Three seeded findings (--validate proves each is surfaced):

    F1  a mid-window model-mix shift (routing simple requests to a small
        model) cuts blended cost per call ~30% with no revenue change --
        the single highest-leverage finance action in an AI company
    F2  weekend GPU utilization collapses while the reserved cluster bills
        24/7 -- idle reserved capacity, quantified in $/year
    F3  p95 latency degrades on exactly the days utilization runs hot --
        the cost-latency tradeoff made visible, so the "just add GPUs"
        conversation happens with numbers attached

Run:  python3 ai_metrics.py
      python3 ai_metrics.py --validate
      python3 ai_metrics.py --html examples/ai_dashboard.html

No dependencies. Python 3.10+. All data synthetic, seeded.
"""

from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(20260801)

DAYS = [date(2026, 4, 1) + timedelta(days=i) for i in range(91)]
MIX_SHIFT_DAY = 45           # F1: router deployed, small model takes share

# (cost per 1M input tokens, per 1M output tokens) -- what WE pay per model
MODELS = {
    "frontier": {"cost_in": 3.00, "cost_out": 15.00, "tok_per_call": (2600, 900)},
    "mid":      {"cost_in": 0.80, "cost_out": 4.00,  "tok_per_call": (2100, 700)},
    "small":    {"cost_in": 0.15, "cost_out": 0.60,  "tok_per_call": (1500, 400)},
}
# customer pricing: consumption billed per 1K total tokens
PRICE_PER_1K_TOKENS = 0.045
COMMITTED_SHARE = 0.63        # share of usage drawing down prepaid commits
GPU_CLUSTER_HOURS_PER_DAY = 24 * 76          # 76 reserved GPUs
GPU_COST_PER_HOUR = 2.10                     # blended reserved rate
SERVING_SHARE_ON_GPU = 0.42   # share of inference served on own cluster
                              # (rest via per-token API above)


def make_days():
    rows = []
    calls_base = 410_000
    dau_base = 5_900
    for i, d in enumerate(DAYS):
        weekend = d.weekday() >= 5
        growth = 1.012 ** i
        calls = calls_base * growth * (0.55 if weekend else 1.0) \
            * random.uniform(0.93, 1.07)

        # F1: model mix shifts at the router deploy
        if i < MIX_SHIFT_DAY:
            mix = {"frontier": 0.42, "mid": 0.40, "small": 0.18}
        else:
            mix = {"frontier": 0.22, "mid": 0.36, "small": 0.42}

        day = {"date": d.isoformat(), "weekend": weekend,
               "api_calls": round(calls),
               "dau": round(dau_base * growth * (0.6 if weekend else 1.0)
                            * random.uniform(0.95, 1.05))}
        total_tokens = total_cost = 0.0
        for mname, share in mix.items():
            mcalls = calls * share * random.uniform(0.97, 1.03)
            ti, to = MODELS[mname]["tok_per_call"]
            tin = mcalls * ti * random.uniform(0.95, 1.05)
            tout = mcalls * to * random.uniform(0.95, 1.05)
            cost = (tin / 1e6 * MODELS[mname]["cost_in"]
                    + tout / 1e6 * MODELS[mname]["cost_out"])
            day[f"calls_{mname}"] = round(mcalls)
            day[f"tokens_{mname}"] = round(tin + tout)
            day[f"cost_{mname}"] = round(cost, 2)
            total_tokens += tin + tout
            total_cost += cost

        # GPU utilization tracks demand: it rises ~62% -> ~92% across the
        # window as call volume grows, and runs materially cooler on weekends.
        # Modeled as a utilization TARGET, not a clipped call count, so the
        # cluster is hot but never pinned at exactly 100% -- a flat 100% line is
        # a chart artifact, and real reserved clusters saturate below the cap.
        util_target = 0.62 + 0.30 * (i / (len(DAYS) - 1))
        util = util_target * (0.72 if weekend else 1.0) * random.uniform(0.95, 1.05)
        util = min(util, 0.99)
        day["gpu_hours_available"] = GPU_CLUSTER_HOURS_PER_DAY
        day["gpu_hours_used"] = round(GPU_CLUSTER_HOURS_PER_DAY * util, 1)
        day["gpu_cost"] = round(GPU_CLUSTER_HOURS_PER_DAY * GPU_COST_PER_HOUR, 2)

        # F3: latency degrades when utilization runs hot
        util = day["gpu_hours_used"] / GPU_CLUSTER_HOURS_PER_DAY
        day["latency_p50_ms"] = round(420 * random.uniform(0.92, 1.08))
        day["latency_p95_ms"] = round((980 + max(0, util - 0.75) * 4200)
                                      * random.uniform(0.92, 1.08))

        day["total_tokens"] = round(total_tokens)
        day["api_cost"] = round(total_cost, 2)
        day["total_ai_cost"] = round(total_cost + day["gpu_cost"], 2)
        rev = total_tokens / 1000 * PRICE_PER_1K_TOKENS
        day["revenue"] = round(rev, 2)
        day["committed_drawdown"] = round(rev * COMMITTED_SHARE, 2)
        # residual, so the split sums to revenue exactly
        day["consumption_revenue"] = round(day["revenue"] - day["committed_drawdown"], 2)
        rows.append(day)
    return rows


# ---------------------------------------------------------------------------
def analyze(rows):
    mau = max(r["dau"] for r in rows) * 3.1   # synthetic MAU proxy
    last30 = rows[-30:]

    def window(rs):
        tok = sum(r["total_tokens"] for r in rs)
        cost = sum(r["total_ai_cost"] for r in rs)
        rev = sum(r["revenue"] for r in rs)
        calls = sum(r["api_calls"] for r in rs)
        return {
            "tokens": tok, "revenue": rev, "cost": cost, "calls": calls,
            "cost_per_1k_tok": cost / tok * 1000,
            "rev_per_1k_tok": rev / tok * 1000,
            "cost_per_call": cost / calls,
            "gm_after_ai": 1 - cost / rev,
        }

    pre = window(rows[:MIX_SHIFT_DAY])
    post = window(rows[MIX_SHIFT_DAY:])
    cur = window(last30)

    wk = [r for r in last30 if not r["weekend"]]
    we = [r for r in last30 if r["weekend"]]
    util_wk = sum(r["gpu_hours_used"] for r in wk) / sum(r["gpu_hours_available"] for r in wk)
    util_we = sum(r["gpu_hours_used"] for r in we) / sum(r["gpu_hours_available"] for r in we)
    idle_we_cost = sum((r["gpu_hours_available"] - r["gpu_hours_used"])
                       * GPU_COST_PER_HOUR for r in we) / len(we) * 104  # weekend days/yr

    hot = [r for r in rows if r["gpu_hours_used"] / r["gpu_hours_available"] > 0.8]
    cool = [r for r in rows if r["gpu_hours_used"] / r["gpu_hours_available"] <= 0.8]
    p95_hot = sum(r["latency_p95_ms"] for r in hot) / max(1, len(hot))
    p95_cool = sum(r["latency_p95_ms"] for r in cool) / max(1, len(cool))

    return {
        "cur": cur, "pre": pre, "post": post,
        # Display the SAME figure the ratio uses -- average weekday DAU over the
        # trailing 30 days. An earlier version showed a single day's DAU beside
        # a ratio computed from the 30-day average, so the card did not
        # reproduce: 16,674 / 54,978 read as 30% while the ratio said 27%.
        "dau": round(sum(r["dau"] for r in wk) / len(wk)),
        "dau_latest_day": last30[-1]["dau"],
        "mau": round(mau),
        "dau_mau": (sum(r["dau"] for r in wk) / len(wk)) / mau,
        "util_weekday": util_wk, "util_weekend": util_we,
        "idle_weekend_annual": idle_we_cost,
        "p95_hot": p95_hot, "p95_cool": p95_cool,
        "committed_share": sum(r["committed_drawdown"] for r in last30)
                           / sum(r["revenue"] for r in last30),
    }


# ---------------------------------------------------------------------------
def print_report(rows) -> None:
    w = 100
    a = analyze(rows)
    c = a["cur"]
    print("=" * w)
    print(f"AI INFRASTRUCTURE METRICS  |  trailing 30 days  |  "
          f"{c['calls']/1e6:.1f}M calls, {c['tokens']/1e9:.1f}B tokens")
    print("=" * w)
    print(f"  cost per 1K tokens          ${c['cost_per_1k_tok']:.4f}")
    print(f"  revenue per 1K tokens       ${c['rev_per_1k_tok']:.4f}")
    print(f"  cost per inference (call)   ${c['cost_per_call']:.4f}")
    print(f"  gross margin after AI cost  {c['gm_after_ai']:.1%}")
    print(f"  GPU utilization (weekday)   {a['util_weekday']:.0%}")
    print(f"  GPU utilization (weekend)   {a['util_weekend']:.0%}")
    print(f"  DAU / MAU                   {a['dau']:,} / {a['mau']:,}  "
          f"({a['dau_mau']:.0%} stickiness)   [avg weekday DAU, trailing 30d]")
    print(f"  committed vs consumption    {a['committed_share']:.0%} committed drawdown / "
          f"{1-a['committed_share']:.0%} pay-as-you-go")

    print(f"\nMODEL MIX & COST  (per call, pre vs post router deploy on day {MIX_SHIFT_DAY})")
    print("-" * w)
    print(f"  cost per call    ${a['pre']['cost_per_call']:.4f} -> "
          f"${a['post']['cost_per_call']:.4f}   "
          f"({a['post']['cost_per_call']/a['pre']['cost_per_call']-1:+.0%})")
    print(f"  GM after AI      {a['pre']['gm_after_ai']:.1%} -> {a['post']['gm_after_ai']:.1%}")
    print(f"  same revenue per token; routing simple requests to the small model.")

    print(f"\nFINDINGS")
    print("-" * w)
    print(f"  F1 router deploy cut blended cost/call "
          f"{abs(a['post']['cost_per_call']/a['pre']['cost_per_call']-1):.0%} at flat pricing")
    print(f"  F2 weekend GPU utilization {a['util_weekend']:.0%} vs weekday "
          f"{a['util_weekday']:.0%}; idle reserved weekend capacity ~"
          f"${a['idle_weekend_annual']:,.0f}/yr -- batch/training backfill candidate")
    print(f"  F3 p95 latency {a['p95_hot']:,.0f}ms on days above 80% utilization vs "
          f"{a['p95_cool']:,.0f}ms below -- the cost-latency tradeoff, quantified")
    print()


def validate(rows) -> None:
    print("VALIDATION")
    print("-" * 90)
    ok = True
    a = analyze(rows)

    worst = max(abs(r["api_cost"] - sum(r[f"cost_{m}"] for m in MODELS))
                for r in rows)
    ok &= worst < 0.05
    print(f"  [{'ok ' if worst < 0.05 else 'MISS'}] per-model costs roll up to "
          f"daily API cost (max diff ${worst:.4f})")

    worst2 = max(abs(r["revenue"] - r["consumption_revenue"] - r["committed_drawdown"])
                 for r in rows)
    ok &= worst2 < 0.01
    print(f"  [{'ok ' if worst2 < 0.01 else 'MISS'}] consumption + committed "
          f"drawdown = revenue, every day (max diff ${worst2:.4f})")

    f1 = a["post"]["cost_per_call"] < a["pre"]["cost_per_call"] * 0.8
    ok &= f1
    print(f"  [{'ok ' if f1 else 'MISS'}] F1 surfaced: cost/call fell "
          f"{abs(a['post']['cost_per_call']/a['pre']['cost_per_call']-1):.0%} "
          f"at the mix shift (must exceed 20%)")

    f2 = a["util_weekend"] < a["util_weekday"] - 0.15
    ok &= f2
    print(f"  [{'ok ' if f2 else 'MISS'}] F2 surfaced: weekend utilization gap "
          f"{a['util_weekday']-a['util_weekend']:.0%} (must exceed 15pts)")

    f3 = a["p95_hot"] > a["p95_cool"] * 1.25
    ok &= f3
    print(f"  [{'ok ' if f3 else 'MISS'}] F3 surfaced: p95 on hot days "
          f"{a['p95_hot']/a['p95_cool']:.1f}x cool days (must exceed 1.25x)")

    print("-" * 90)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(rows, path: Path) -> None:
    a = analyze(rows)
    c = a["cur"]
    n = len(rows)
    W, H, PL, PT, PB = 880, 270, 84, 22, 38
    pw, ph = W - PL - 24, H - PT - PB

    def x(i): return PL + pw * i / (n - 1)

    # cost per call daily + shift marker
    cpc = [r["total_ai_cost"] / r["api_calls"] for r in rows]
    hi_c = max(cpc) * 1.15
    def yc(v): return PT + ph * (1 - v / hi_c)
    cpc_line = " ".join(f"{x(i):.1f},{yc(v):.1f}" for i, v in enumerate(cpc))
    shift = (f'<line x1="{x(MIX_SHIFT_DAY):.1f}" y1="{PT}" x2="{x(MIX_SHIFT_DAY):.1f}" '
             f'y2="{H-PB}" class="trig"/>'
             f'<text x="{x(MIX_SHIFT_DAY)+6:.1f}" y="{PT+14}" class="tick" '
             f'fill="var(--pos)">router deploy — small model takes 42% of calls</text>')
    grid_c = "".join(
        f'<line x1="{PL}" y1="{yc(hi_c*f):.1f}" x2="{W-24}" y2="{yc(hi_c*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{yc(hi_c*f)+4:.1f}" text-anchor="end" class="tick">${hi_c*f:.3f}</text>'
        for f in (0, .5, 1.0))
    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{H-14}" text-anchor="middle" class="tick">{rows[i]["date"][5:]}</text>'
        for i in range(0, n, 14))

    # utilization daily
    util = [r["gpu_hours_used"] / r["gpu_hours_available"] for r in rows]
    def yu(v): return PT + ph * (1 - v)
    util_line = " ".join(f"{x(i):.1f},{yu(v):.1f}" for i, v in enumerate(util))
    grid_u = "".join(
        f'<line x1="{PL}" y1="{yu(f):.1f}" x2="{W-24}" y2="{yu(f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{yu(f)+4:.1f}" text-anchor="end" class="tick">{f:.0%}</text>'
        for f in (0, .5, 1.0))
    weekend_bands = "".join(
        f'<rect x="{x(i)-pw/n/2:.1f}" y="{PT}" width="{pw/n:.1f}" height="{ph}" '
        f'fill="var(--mut)" opacity="0.10"/>'
        for i, r in enumerate(rows) if r["weekend"])

    # latency vs utilization scatter
    hi_l = max(r["latency_p95_ms"] for r in rows) * 1.1
    def yl(v): return PT + ph * (1 - v / hi_l)
    dots = "".join(
        f'<circle cx="{PL + pw * (r["gpu_hours_used"]/r["gpu_hours_available"]):.1f}" '
        f'cy="{yl(r["latency_p95_ms"]):.1f}" r="3.5" '
        f'fill="{"var(--neg)" if r["gpu_hours_used"]/r["gpu_hours_available"] > 0.8 else "var(--line)"}" '
        f'opacity="0.6"/>' for r in rows)
    grid_l = "".join(
        f'<line x1="{PL}" y1="{yl(hi_l*f):.1f}" x2="{W-24}" y2="{yl(hi_l*f):.1f}" class="grid"/>'
        f'<text x="{PL-10}" y="{yl(hi_l*f)+4:.1f}" text-anchor="end" class="tick">{hi_l*f/1000:.1f}s</text>'
        for f in (0, .5, 1.0))
    xt = "".join(
        f'<text x="{PL + pw * f:.1f}" y="{H-14}" text-anchor="middle" class="tick">{f:.0%} util</text>'
        for f in (0.25, 0.5, 0.75, 1.0))

    model_rows = ""
    last30 = rows[-30:]
    for mname, spec in MODELS.items():
        calls = sum(r[f"calls_{mname}"] for r in last30)
        tok = sum(r[f"tokens_{mname}"] for r in last30)
        cost = sum(r[f"cost_{mname}"] for r in last30)
        model_rows += (f"<tr><td>{mname}</td>"
                       f"<td class='n'>{calls/1e6:,.1f}M</td>"
                       f"<td class='n'>{tok/1e9:,.2f}B</td>"
                       f"<td class='n'>${cost:,.0f}</td>"
                       f"<td class='n'>${cost/tok*1000:.4f}</td>"
                       f"<td class='n'>${cost/calls:.4f}</td></tr>")

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Infrastructure Metrics</title>
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
  .kpi .v {{ font-size:18px; font-weight:600; margin-top:3px;
             font-variant-numeric:tabular-nums; }}
  .kpi .n2 {{ font-size:11px; color:var(--mut); margin-top:1px; }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .trig {{ stroke:var(--pos); stroke-width:1.5; stroke-dasharray:5 4; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
  th,td {{ padding:6px 10px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>AI Infrastructure Metrics</h1>
  <div class="sub">Trailing 30 days · {c['calls']/1e6:,.1f}M API calls ·
    {c['tokens']/1e9:,.1f}B tokens · synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Cost / 1K tokens</div><div class="v">${c['cost_per_1k_tok']:.4f}</div></div>
    <div class="kpi"><div class="k">Revenue / 1K tokens</div><div class="v">${c['rev_per_1k_tok']:.4f}</div></div>
    <div class="kpi"><div class="k">Cost / inference</div><div class="v">${c['cost_per_call']:.4f}</div></div>
    <div class="kpi"><div class="k">GM after AI cost</div><div class="v">{c['gm_after_ai']:.1%}</div></div>
    <div class="kpi"><div class="k">GPU utilization</div><div class="v">{a['util_weekday']:.0%}</div>
      <div class="n2">weekend: {a['util_weekend']:.0%}</div></div>
    <div class="kpi"><div class="k">DAU / MAU</div><div class="v">{a['dau_mau']:.0%}</div>
      <div class="n2">{a['dau']:,} avg weekday DAU / {a['mau']:,} MAU</div>
      <div class="n2">trailing 30 days</div></div>
    <div class="kpi"><div class="k">Committed drawdown</div><div class="v">{a['committed_share']:.0%}</div>
      <div class="n2">of usage revenue</div></div>
  </div>

  <h2>F1 — Cost per inference, daily (router deploy on day {MIX_SHIFT_DAY})</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid_c}{shift}
    <polyline points="{cpc_line}" fill="none" stroke="var(--line)" stroke-width="2"/>
    {ticks}</svg></div>
  <div class="note">Routing simple requests to the small model cut blended cost
    per call {abs(a['post']['cost_per_call']/a['pre']['cost_per_call']-1):.0%} at
    identical customer pricing — GM after AI cost moved
    {a['pre']['gm_after_ai']:.1%} → {a['post']['gm_after_ai']:.1%}. Model routing
    is the highest-leverage finance action in an AI company, and this chart is
    how finance participates in it.</div>

  <h2>F2 — GPU utilization, daily (weekends shaded)</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{weekend_bands}{grid_u}
    <polyline points="{util_line}" fill="none" stroke="var(--line)" stroke-width="2"/>
    {ticks}</svg></div>
  <div class="note">The reserved cluster bills 24/7; weekend demand halves.
    Idle weekend capacity ≈ <strong>${a['idle_weekend_annual']:,.0f}/yr</strong>
    — a batch-workload / training-backfill candidate, not a cost cut.</div>

  <h2>F3 — p95 latency vs GPU utilization (each dot one day)</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid_l}{dots}{xt}</svg></div>
  <div class="note">Above ~80% utilization, p95 degrades sharply
    ({a['p95_hot']/1000:,.1f}s hot vs {a['p95_cool']/1000:,.1f}s cool). This is
    the cost-latency frontier: running the cluster hotter is cheaper per token
    and slower per user, and the tradeoff should be priced, not discovered.</div>

  <h2>Model economics — trailing 30 days</h2>
  <div class="tbl"><table>
    <thead><tr><th>Model</th><th class="n">Calls</th><th class="n">Tokens</th>
      <th class="n">Cost</th><th class="n">$/1K tok</th><th class="n">$/call</th></tr></thead>
    <tbody>{model_rows}</tbody></table></div>

  <footer>Generated by ai_metrics.py · cost roll-ups and revenue splits tie
    daily (run --validate) · all data synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="AI infrastructure unit economics")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    rows = make_days()
    print_report(rows)
    if args.validate:
        validate(rows)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(rows, args.html)


if __name__ == "__main__":
    main()
