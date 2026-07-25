"""
Forward Revenue Model: Capacity, Pipeline, Renewals
===================================================
The next four quarters of revenue, built the way FP&A actually builds it --
from the three books that exist today, not from a growth rate:

    SALES CAPACITY   reps x ramp x quota: what the team CAN book
    PIPELINE         stage-weighted open opportunities: what is VISIBLE
    RENEWALS         contracts expiring, risk-weighted: what can be KEPT

The three answer different questions and disagree on purpose. Capacity is a
ceiling, pipeline is evidence, and the forecast for a given quarter should
lean on pipeline near-in (where the pipe is real) and capacity further out
(where the pipe hasn't been generated yet). The model shows both and flags
the gap -- a quarter where weighted pipeline sits far below capacity is a
pipeline-generation problem visible two quarters before it becomes a
bookings miss.

Renewals are forecast per-contract from health scores, not as a blended
churn rate, because renewal risk is lumpy: the report surfaces the largest
at-risk contracts by name, which is the list a CRO actually works.

Seeded findings (--validate proves the analysis surfaces them):
    - Q+2 pipeline coverage is materially below the 3.0x planning floor
    - two of the ten largest renewal contracts are red-health

Run:  python3 forecast.py
      python3 forecast.py --validate
      python3 forecast.py --html examples/forecast_dashboard.html

No dependencies. Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

random.seed(20260710)

DATA = Path(__file__).parent / "data"
QUARTERS = ["2026Q3", "2026Q4", "2027Q1", "2027Q2"]
BEGINNING_ARR = 46_000_000
COVERAGE_FLOOR = 3.0
RAMP = [0.0, 0.30, 0.60, 1.00]          # quarterly ramp to full productivity
STAGE_WIN = {"discovery": 0.10, "demo": 0.25, "proposal": 0.45,
             "negotiation": 0.70}
HEALTH_RENEW = {"green": 0.95, "yellow": 0.80, "red": 0.45}
EXPANSION_RATE_Q = 0.012                 # net expansion on retained base / quarter


# ---------------------------------------------------------------------------
def make_data():
    DATA.mkdir(parents=True, exist_ok=True)

    # --- sales roster: 38 reps, staggered hires, quotas by segment ---------
    reps = []
    for i in range(1, 39):
        seg = random.choices(["enterprise", "mid_market", "smb"],
                             [0.3, 0.45, 0.25])[0]
        quota = {"enterprise": 1_600_000, "mid_market": 950_000,
                 "smb": 550_000}[seg] * random.uniform(0.9, 1.1)
        # hired_q: quarters before the forecast start (>=3 means fully ramped)
        hired_q = random.choices([0, 1, 2, 3, 4, 6, 9],
                                 [0.10, 0.12, 0.13, 0.15, 0.2, 0.15, 0.15])[0]
        reps.append({"rep_id": f"R{i:02d}", "segment": seg,
                     "annual_quota": round(quota), "quarters_ramped": hired_q})

    # --- pipeline: open opps by close quarter ------------------------------
    # Seeded: Q+2 (2027Q1) pipe deliberately thin -- generation lagged.
    pipe = []
    n = 0
    per_q = {0: 210, 1: 150, 2: 55, 3: 90}
    for qi, q in enumerate(QUARTERS):
        for _ in range(per_q[qi]):
            n += 1
            seg = random.choices(["enterprise", "mid_market", "smb"],
                                 [0.22, 0.44, 0.34])[0]
            amt = {"enterprise": (90_000, 380_000),
                   "mid_market": (20_000, 90_000),
                   "smb": (4_000, 20_000)}[seg]
            stage = random.choices(list(STAGE_WIN),
                                   [0.38, 0.28, 0.21, 0.13] if qi < 2
                                   else [0.70, 0.22, 0.06, 0.02])[0]
            pipe.append({"opp_id": f"O{n:04d}", "segment": seg,
                         "close_quarter": q, "stage": stage,
                         "amount": round(random.uniform(*amt), 2)})

    # --- renewal book: contracts expiring, health-scored -------------------
    renewals = []
    n = 0
    for qi, q in enumerate(QUARTERS):
        for _ in range(random.randint(95, 125)):
            n += 1
            seg = random.choices(["enterprise", "mid_market", "smb"],
                                 [0.18, 0.42, 0.40])[0]
            arr = {"enterprise": (70_000, 300_000),
                   "mid_market": (14_000, 70_000),
                   "smb": (2_000, 14_000)}[seg]
            health = random.choices(["green", "yellow", "red"],
                                    [0.68, 0.22, 0.10])[0]
            renewals.append({"contract_id": f"N{n:04d}", "segment": seg,
                             "renewal_quarter": q, "health": health,
                             "arr": round(random.uniform(*arr), 2)})
    # Seeded: two of the largest renewals are red.
    big = sorted(renewals, key=lambda r: -r["arr"])
    big[1]["health"] = "red"
    big[3]["health"] = "red"

    for name, rows in [("reps.csv", reps), ("pipeline.csv", pipe),
                       ("renewals.csv", renewals)]:
        with (DATA / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
    return reps, pipe, renewals


# ---------------------------------------------------------------------------
def capacity_by_quarter(reps):
    out = {}
    for qi, q in enumerate(QUARTERS):
        cap = 0.0
        for r in reps:
            ramp_stage = min(r["quarters_ramped"] + qi, 3)
            cap += r["annual_quota"] / 4 * RAMP[ramp_stage]
        out[q] = cap
    return out


def pipeline_by_quarter(pipe):
    raw = defaultdict(float)
    weighted = defaultdict(float)
    for o in pipe:
        raw[o["close_quarter"]] += o["amount"]
        weighted[o["close_quarter"]] += o["amount"] * STAGE_WIN[o["stage"]]
    return raw, weighted


def renewals_by_quarter(renewals):
    book = defaultdict(float)
    kept = defaultdict(float)
    for r in renewals:
        book[r["renewal_quarter"]] += r["arr"]
        kept[r["renewal_quarter"]] += r["arr"] * HEALTH_RENEW[r["health"]]
    return book, kept


def arr_build(reps, pipe, renewals):
    """Beginning ARR -> ending ARR per quarter, sourced from the three books."""
    cap = capacity_by_quarter(reps)
    _, weighted = pipeline_by_quarter(pipe)
    book, kept = renewals_by_quarter(renewals)
    rows, arr = [], BEGINNING_ARR
    for qi, q in enumerate(QUARTERS):
        # near-in quarters: believe the pipe; far out: believe capacity at a
        # historical 82% attainment. The forecast takes the more evidenced.
        new_from_pipe = weighted[q]
        new_from_cap = cap[q] * 0.82
        new = new_from_pipe if qi < 2 else new_from_cap
        churn = book[q] - kept[q]
        expansion = (arr - book[q]) * EXPANSION_RATE_Q + kept[q] * 0.02
        end = arr + new + expansion - churn
        rows.append({"q": q, "beginning": arr, "new": new,
                     "new_source": "pipeline" if qi < 2 else "capacity",
                     "expansion": expansion, "renewal_book": book[q],
                     "churn": churn, "ending": end,
                     "gross_retention_q": kept[q] / book[q]})
        arr = end
    return rows


# ---------------------------------------------------------------------------
def m(x): return f"${x/1e6:,.1f}M"


def print_report(reps, pipe, renewals) -> None:
    w = 104
    cap = capacity_by_quarter(reps)
    raw, weighted = pipeline_by_quarter(pipe)
    book, kept = renewals_by_quarter(renewals)
    build = arr_build(reps, pipe, renewals)

    print("=" * w)
    print(f"FORWARD REVENUE MODEL  |  next 4 quarters  |  {len(reps)} reps, "
          f"{len(pipe)} open opps, {len(renewals)} renewals")
    print("=" * w)

    print("BOOKINGS: CAPACITY vs PIPELINE")
    print("-" * w)
    print(f"  {'quarter':<9}{'capacity':>12}{'raw pipe':>12}{'weighted':>12}"
          f"{'coverage':>10}{'flag':>28}")
    for q in QUARTERS:
        cov = raw[q] / cap[q] if cap[q] else 0
        flag = f"below {COVERAGE_FLOOR:.1f}x floor -- generate pipe" \
            if cov < COVERAGE_FLOOR else ""
        print(f"  {q:<9}{m(cap[q]):>12}{m(raw[q]):>12}{m(weighted[q]):>12}"
              f"{cov:>9.1f}x{flag:>28}")

    print(f"\nRENEWALS: BOOK AND RISK")
    print("-" * w)
    print(f"  {'quarter':<9}{'book':>12}{'risk-wtd kept':>14}{'gross ret':>11}")
    for q in QUARTERS:
        print(f"  {q:<9}{m(book[q]):>12}{m(kept[q]):>14}{kept[q]/book[q]:>10.1%}")

    print(f"\n  largest at-risk renewals (yellow/red):")
    risky = sorted((r for r in renewals if r["health"] != "green"),
                   key=lambda r: -r["arr"])[:8]
    for r in risky:
        print(f"    {r['contract_id']}  {r['segment']:<12}{r['renewal_quarter']}"
              f"  {r['health']:<7}{m(r['arr']):>10}")

    print(f"\nARR BUILD  (new business from {build[0]['new_source']} near-in, "
          f"capacity x 82% attainment far out)")
    print("-" * w)
    print(f"  {'quarter':<9}{'beginning':>12}{'new':>10}{'expansion':>11}"
          f"{'churn':>10}{'ending':>12}{'source':>10}")
    for b in build:
        print(f"  {b['q']:<9}{m(b['beginning']):>12}{m(b['new']):>10}"
              f"{m(b['expansion']):>11}{m(-b['churn']):>10}{m(b['ending']):>12}"
              f"{b['new_source']:>10}")
    print()


def validate(reps, pipe, renewals) -> None:
    print("VALIDATION")
    print("-" * 86)
    ok = True
    cap = capacity_by_quarter(reps)
    raw, weighted = pipeline_by_quarter(pipe)
    book, kept = renewals_by_quarter(renewals)
    build = arr_build(reps, pipe, renewals)

    # 1. the ARR build reconciles quarter over quarter
    worst = max(abs(b["beginning"] + b["new"] + b["expansion"] - b["churn"]
                    - b["ending"]) for b in build)
    chain = all(abs(build[i]["ending"] - build[i + 1]["beginning"]) < 0.01
                for i in range(len(build) - 1))
    ok &= worst < 0.01 and chain
    print(f"  [{'ok ' if worst < 0.01 and chain else 'MISS'}] ARR build reconciles "
          f"and chains (max diff ${worst:.4f})")

    # 2. seeded coverage gap at Q+2 is flagged
    cov2 = raw[QUARTERS[2]] / cap[QUARTERS[2]]
    ok &= cov2 < COVERAGE_FLOOR
    print(f"  [{'ok ' if cov2 < COVERAGE_FLOOR else 'MISS'}] Q+2 coverage "
          f"{cov2:.1f}x sits below the {COVERAGE_FLOOR:.1f}x floor and is flagged")

    # 3. seeded red whales appear in the at-risk list
    risky = sorted((r for r in renewals if r["health"] != "green"),
                   key=lambda r: -r["arr"])[:8]
    top10 = sorted(renewals, key=lambda r: -r["arr"])[:10]
    reds_in_top10 = [r for r in top10 if r["health"] == "red"]
    surfaced = all(r in risky for r in reds_in_top10)
    ok &= len(reds_in_top10) >= 2 and surfaced
    print(f"  [{'ok ' if surfaced and len(reds_in_top10) >= 2 else 'MISS'}] "
          f"{len(reds_in_top10)} red contracts in the top-10 renewal book, "
          f"all surfaced in the at-risk list")

    # 4. renewal book equals sum of contracts
    total_book = sum(book.values())
    total_rows = sum(r["arr"] for r in renewals)
    tie = abs(total_book - total_rows) < 0.01
    ok &= tie
    print(f"  [{'ok ' if tie else 'MISS'}] renewal book ties to the contract "
          f"file (${total_book:,.0f})")

    print("-" * 86)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(reps, pipe, renewals, path: Path) -> None:
    cap = capacity_by_quarter(reps)
    raw, weighted = pipeline_by_quarter(pipe)
    book, kept = renewals_by_quarter(renewals)
    build = arr_build(reps, pipe, renewals)

    # grouped bars: capacity vs raw vs weighted pipe, per quarter
    W, H, PL, PT, PB = 880, 300, 80, 24, 42
    pw, ph = W - PL - 24, H - PT - PB
    hi = max(max(cap.values()), max(raw.values())) * 1.15

    def y(v): return PT + ph * (1 - v / hi)

    colors = {"capacity": "var(--line)", "raw pipeline": "#8250df",
              "weighted pipeline": "#d97706"}
    group_w = pw / len(QUARTERS)
    bar_w = group_w / 4.4
    bars = ""
    for qi, q in enumerate(QUARTERS):
        vals = [("capacity", cap[q]), ("raw pipeline", raw[q]),
                ("weighted pipeline", weighted[q])]
        for bi, (label, v) in enumerate(vals):
            bx = PL + group_w * qi + bar_w * (bi + 0.55)
            bars += (f'<rect x="{bx:.1f}" y="{y(v):.1f}" width="{bar_w:.1f}" '
                     f'height="{y(0)-y(v):.1f}" fill="{colors[label]}" rx="2" '
                     f'opacity="0.9"/>')
        cov = raw[q] / cap[q]
        flag = f' fill="var(--neg)" font-weight="700"' if cov < COVERAGE_FLOOR else ' fill="var(--mut)"'
        bars += (f'<text x="{PL + group_w * (qi + 0.5):.1f}" y="{H-24}" '
                 f'text-anchor="middle" class="tick">{q}</text>'
                 f'<text x="{PL + group_w * (qi + 0.5):.1f}" y="{H-9}" '
                 f'text-anchor="middle" font-size="11"{flag}>{cov:.1f}x cov</text>')
    grid = ""
    for fr in (0, .5, 1.0):
        v = hi * fr
        grid += (f'<line x1="{PL}" y1="{y(v):.1f}" x2="{W-24}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{PL-10}" y="{y(v)+4:.1f}" text-anchor="end" class="tick">${v/1e6:.0f}M</text>')
    leg = "".join(f'<tspan fill="{c}">■ {k}  </tspan>' for k, c in colors.items())

    build_rows = "".join(
        f"<tr><td>{b['q']}</td><td class='n'>${b['beginning']/1e6:,.1f}</td>"
        f"<td class='n pos'>+${b['new']/1e6:,.1f}</td>"
        f"<td class='n pos'>+${b['expansion']/1e6:,.1f}</td>"
        f"<td class='n neg'>−${b['churn']/1e6:,.1f}</td>"
        f"<td class='n b'>${b['ending']/1e6:,.1f}</td>"
        f"<td class='mut'>{b['new_source']}</td>"
        f"<td class='n'>{b['gross_retention_q']:.1%}</td></tr>"
        for b in build)

    risky = sorted((r for r in renewals if r["health"] != "green"),
                   key=lambda r: -r["arr"])[:10]
    hcolor = {"yellow": "#d97706", "red": "var(--neg)"}
    risk_rows = "".join(
        f"<tr><td class='mono'>{r['contract_id']}</td>"
        f"<td>{r['segment'].replace('_',' ')}</td><td>{r['renewal_quarter']}</td>"
        f"<td style='color:{hcolor[r['health']]};font-weight:600'>{r['health']}</td>"
        f"<td class='n'>${r['arr']:,.0f}</td></tr>"
        for r in risky)

    ren_rows = "".join(
        f"<tr><td>{q}</td><td class='n'>${book[q]/1e6:,.1f}M</td>"
        f"<td class='n'>${kept[q]/1e6:,.1f}M</td>"
        f"<td class='n'>{kept[q]/book[q]:.1%}</td></tr>"
        for q in QUARTERS)

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Forward Revenue Model · capacity, pipeline, renewals</title>
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
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  @media (max-width:760px) {{ .cols {{ grid-template-columns:1fr; }} }}
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
  .b {{ font-weight:600; }} .mut {{ color:var(--mut); }}
  .neg {{ color:var(--neg); }} .pos {{ color:var(--pos); }}
  .mono {{ font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Forward Revenue Model</h1>
  <div class="sub">Next four quarters from the three books that exist today —
    {len(reps)} reps · {len(pipe):,} open opportunities · {len(renewals):,}
    renewal contracts · synthetic data</div>

  <h2>Bookings: capacity vs pipeline, with coverage</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid}{bars}
    <text x="{PL}" y="14" class="leg">{leg}</text></svg></div>
  <div class="note">Coverage = raw pipeline ÷ capacity, against a
    {COVERAGE_FLOOR:.1f}× planning floor. 2027Q1 is the flag that matters:
    thin coverage two quarters out is a pipeline-generation problem visible
    <em>before</em> it becomes a bookings miss — the entire point of running
    this weekly.</div>

  <h2>ARR build — next four quarters</h2>
  <div class="tbl"><table>
    <thead><tr><th>Quarter</th><th class="n">Beginning $M</th><th class="n">New</th>
      <th class="n">Expansion</th><th class="n">Churn</th><th class="n">Ending $M</th>
      <th>New sourced from</th><th class="n">Gross ret (Q)</th></tr></thead>
    <tbody>{build_rows}</tbody></table></div>
  <div class="note">Near-in quarters source new business from stage-weighted
    pipeline (evidence); far-out quarters from capacity × 82% historical
    attainment (the pipe that will exist hasn't been generated yet). Mixing
    the two on purpose, and saying so, beats pretending either is a forecast
    on its own.</div>

  <div class="cols">
    <div>
      <h2>Renewal book by quarter</h2>
      <div class="tbl"><table>
        <thead><tr><th>Quarter</th><th class="n">Book</th>
          <th class="n">Risk-wtd kept</th><th class="n">Gross ret</th></tr></thead>
        <tbody>{ren_rows}</tbody></table></div>
    </div>
    <div>
      <h2>Largest at-risk renewals</h2>
      <div class="tbl"><table>
        <thead><tr><th>Contract</th><th>Segment</th><th>Quarter</th>
          <th>Health</th><th class="n">ARR</th></tr></thead>
        <tbody>{risk_rows}</tbody></table></div>
    </div>
  </div>

  <footer>Generated by forecast.py · ARR build reconciles and chains
    (run --validate) · all data synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Capacity, pipeline, renewals forecast")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    reps, pipe, renewals = make_data()
    print_report(reps, pipe, renewals)
    if args.validate:
        validate(reps, pipe, renewals)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(reps, pipe, renewals, args.html)


if __name__ == "__main__":
    main()
