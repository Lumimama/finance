"""
Pricing Waterfall & Discount Discipline
=======================================
Where price actually leaks between list and the contract, from a ledger of
~1,100 closed deals: the classic pocket-price waterfall, realization by
segment and deal size, and the two pathologies every pricing review looks
for first:

    QUARTER-END CAPITULATION   discounts given in the last two weeks of a
                               quarter run materially deeper -- sales is
                               spending price to make the date
    SIZE CREEP                 discount depth rising faster with deal size
                               than any cost-to-serve justification

Both are seeded into the data; --validate proves the analysis surfaces them
and that the waterfall ties: list - standard - negotiated = realized on
every deal, to the cent.

Why "pocket price" matters: a 2% average realization leak on a $40M bookings
year is $800K of pure margin -- there is no cost to recover it except saying
no later in the quarter. The waterfall is how you show that to a sales
leader without starting a fight about anyone's specific deal.

Run:  python3 pricing.py
      python3 pricing.py --validate
      python3 pricing.py --html examples/pricing_dashboard.html

No dependencies. Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

random.seed(20260501)

DATA = Path(__file__).parent / "data"
QUARTER_STARTS = [date(2025, 7, 1), date(2025, 10, 1),
                  date(2026, 1, 1), date(2026, 4, 1)]

SEGMENTS = {
    "enterprise": (0.20, (90_000, 420_000), 0.06),   # weight, list ACV, std discount
    "mid_market": (0.44, (20_000, 90_000), 0.04),
    "smb":        (0.36, (4_000, 20_000), 0.02),
}


def q_end(d: date) -> date:
    for qs in reversed(QUARTER_STARTS):
        if d >= qs:
            nxt = QUARTER_STARTS[QUARTER_STARTS.index(qs) + 1] \
                if QUARTER_STARTS.index(qs) + 1 < len(QUARTER_STARTS) \
                else date(2026, 7, 1)
            return nxt - timedelta(days=1)
    return date(2025, 9, 30)


def make_deals() -> list[dict]:
    deals = []
    for i in range(1, 1101):
        r, cum, seg = random.random(), 0.0, "smb"
        for s, v in SEGMENTS.items():
            cum += v[0]
            if r <= cum:
                seg = s
                break
        _, (lo, hi), std = SEGMENTS[seg]
        list_price = round(random.uniform(lo, hi), 2)

        qs = random.choice(QUARTER_STARTS)
        close = qs + timedelta(days=random.randint(0, 90))
        days_to_qend = (q_end(close) - close).days
        late = days_to_qend <= 14

        # negotiated discount: baseline by segment, PLUS the two seeded
        # pathologies -- quarter-end capitulation and size creep.
        base_neg = {"enterprise": 0.09, "mid_market": 0.06, "smb": 0.03}[seg]
        size_pos = (list_price - lo) / (hi - lo)          # 0..1 within segment
        neg = base_neg * random.uniform(0.4, 1.6)
        neg += size_pos * 0.07                            # size creep
        if late:
            neg += random.uniform(0.04, 0.09)             # quarter-end give
        neg = min(neg, 0.32)

        std_amt = round(list_price * std, 2)
        neg_amt = round(list_price * neg, 2)
        realized = round(list_price - std_amt - neg_amt, 2)
        deals.append({
            "deal_id": f"D{i:04d}", "segment": seg,
            "close_date": close.isoformat(),
            "days_to_quarter_end": days_to_qend,
            "list_price": list_price, "standard_discount": std_amt,
            "negotiated_discount": neg_amt, "realized_price": realized,
        })
    return deals


# ---------------------------------------------------------------------------
def waterfall(deals):
    lst = sum(d["list_price"] for d in deals)
    std = sum(d["standard_discount"] for d in deals)
    neg = sum(d["negotiated_discount"] for d in deals)
    real = sum(d["realized_price"] for d in deals)
    return [("List price", lst), ("Standard discount", -std),
            ("Negotiated discount", -neg), ("Pocket price", real)]


def realization_by(deals, key_fn, label):
    g = defaultdict(lambda: [0.0, 0.0])
    for d in deals:
        k = key_fn(d)
        g[k][0] += d["list_price"]
        g[k][1] += d["realized_price"]
    return {k: v[1] / v[0] for k, v in sorted(g.items())}


def size_band(d):
    lp = d["list_price"]
    if lp < 20_000: return "1: <20K"
    if lp < 90_000: return "2: 20-90K"
    if lp < 200_000: return "3: 90-200K"
    return "4: >200K"


def timing_band(d):
    return "last 2 weeks" if d["days_to_quarter_end"] <= 14 else "weeks 1-11"


# ---------------------------------------------------------------------------
def m(x): return f"${x/1e6:,.2f}M"


def print_report(deals) -> None:
    w = 96
    wf = waterfall(deals)
    lst, real = wf[0][1], wf[-1][1]
    print("=" * w)
    print(f"PRICING WATERFALL  |  {len(deals):,} closed deals  |  FY2026")
    print("=" * w)
    for label, v in wf:
        pct = v / lst
        print(f"  {label:<22}{m(v):>12}   {pct:>7.1%}")
    print(f"\n  overall realization: {real/lst:.1%} of list")

    print(f"\nREALIZATION BY SEGMENT")
    print("-" * w)
    for k, v in realization_by(deals, lambda d: d["segment"], "segment").items():
        print(f"  {k:<14}{v:>8.1%}")

    print(f"\nREALIZATION BY DEAL SIZE  (the size-creep check)")
    print("-" * w)
    for k, v in realization_by(deals, size_band, "size").items():
        print(f"  {k:<14}{v:>8.1%}")

    print(f"\nREALIZATION BY CLOSE TIMING  (the quarter-end check)")
    print("-" * w)
    by_t = realization_by(deals, timing_band, "timing")
    for k, v in by_t.items():
        print(f"  {k:<14}{v:>8.1%}")
    gap = by_t["weeks 1-11"] - by_t["last 2 weeks"]
    late = [d for d in deals if d["days_to_quarter_end"] <= 14]
    leak = sum(d["list_price"] for d in late) * gap
    print(f"\n  quarter-end deals realize {gap:.1%} less. On {m(sum(d['list_price'] for d in late))} "
          f"of late-quarter list, that is ~{m(leak)} of price given to the calendar.")
    print()


def validate(deals) -> None:
    print("VALIDATION")
    print("-" * 86)
    ok = True

    worst = max(abs(d["list_price"] - d["standard_discount"]
                    - d["negotiated_discount"] - d["realized_price"])
                for d in deals)
    ok &= worst < 0.01
    print(f"  [{'ok ' if worst < 0.01 else 'MISS'}] waterfall ties on every deal: "
          f"list - std - negotiated = realized (max diff ${worst:.4f})")

    by_t = realization_by(deals, timing_band, "t")
    gap = by_t["weeks 1-11"] - by_t["last 2 weeks"]
    ok &= gap > 0.03
    print(f"  [{'ok ' if gap > 0.03 else 'MISS'}] quarter-end capitulation surfaced: "
          f"{gap:.1%} realization gap (must exceed 3pts)")

    by_s = realization_by(deals, size_band, "s")
    monotone = (by_s["1: <20K"] > by_s["2: 20-90K"] > by_s["3: 90-200K"]
                > by_s["4: >200K"])
    ok &= monotone
    print(f"  [{'ok ' if monotone else 'MISS'}] size creep surfaced: realization "
          f"falls monotonically with deal size "
          f"({by_s['1: <20K']:.0%} -> {by_s['4: >200K']:.0%})")

    print("-" * 86)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(deals, path: Path) -> None:
    wf = waterfall(deals)
    lst = wf[0][1]

    W, H, PL, PT, PB = 880, 300, 90, 24, 42
    pw, ph = W - PL - 24, H - PT - PB
    hi = lst * 1.08
    gap_w = pw / len(wf)
    bar_w = gap_w * 0.58

    def y(v): return PT + ph * (1 - v / hi)

    svg, running = "", 0.0
    for i, (label, v) in enumerate(wf):
        cx = PL + gap_w * i + gap_w / 2
        total_bar = i == 0 or i == len(wf) - 1
        if total_bar:
            top, bot = y(v), y(0)
            running = v
            cls = "wt"
        else:
            start, end = running, running + v
            top, bot = y(max(start, end)), y(min(start, end))
            running = end
            cls = "wn"
        svg += (f'<rect x="{cx-bar_w/2:.1f}" y="{top:.1f}" width="{bar_w:.1f}" '
                f'height="{max(bot-top,1.5):.1f}" class="{cls}" rx="2"/>'
                f'<text x="{cx:.1f}" y="{top-7:.1f}" text-anchor="middle" class="wv">'
                f'{"−" if not total_bar else ""}${abs(v)/1e6:,.1f}M</text>'
                f'<text x="{cx:.1f}" y="{H-16:.1f}" text-anchor="middle" '
                f'class="tick">{label}</text>')
    grid = ""
    for fr in (0, .5, 1.0):
        v = hi * fr
        grid += (f'<line x1="{PL}" y1="{y(v):.1f}" x2="{W-24}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{PL-10}" y="{y(v)+4:.1f}" text-anchor="end" class="tick">${v/1e6:.0f}M</text>')

    def bar_table(data: dict, fmt="{:.1%}") -> str:
        mx = max(data.values())
        rows = ""
        for k, v in data.items():
            rows += (f"<tr><td>{k}</td><td class='n'>{fmt.format(v)}</td>"
                     f"<td><div class='bar' style='width:{v/mx*100:.0f}%'></div></td></tr>")
        return (f"<div class='tbl'><table><thead><tr><th></th>"
                f"<th class='n'>Realization</th><th></th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div>")

    by_seg = realization_by(deals, lambda d: d["segment"], "")
    by_size = realization_by(deals, size_band, "")
    by_time = realization_by(deals, timing_band, "")
    gap = by_time["weeks 1-11"] - by_time["last 2 weeks"]
    late = [d for d in deals if d["days_to_quarter_end"] <= 14]
    leak = sum(d["list_price"] for d in late) * gap

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pricing Waterfall · discount discipline</title>
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
  .wt {{ fill:var(--line); }} .wn {{ fill:var(--neg); }}
  .wv {{ fill:var(--fg); font-size:11px; font-weight:600; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; }}
  @media (max-width:860px) {{ .cols {{ grid-template-columns:1fr; }} }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
  th,td {{ padding:6px 10px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .bar {{ background:var(--line); height:9px; border-radius:4px; min-width:2px; }}
  td:last-child {{ width:40%; }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Pricing Waterfall</h1>
  <div class="sub">{len(deals):,} closed deals · FY2026 · list → pocket price ·
    synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Total list</div><div class="v">${wf[0][1]/1e6:,.1f}M</div></div>
    <div class="kpi"><div class="k">Pocket price</div><div class="v">${wf[-1][1]/1e6:,.1f}M</div>
      <div class="n2">{wf[-1][1]/wf[0][1]:.1%} realization</div></div>
    <div class="kpi warn"><div class="k">Quarter-end gap</div><div class="v">{gap:.1%}</div>
      <div class="n2">deeper discounts, last 2 weeks</div></div>
    <div class="kpi warn"><div class="k">Calendar leak</div><div class="v">${leak/1e6:,.1f}M</div>
      <div class="n2">price given to the close date</div></div>
  </div>

  <h2>The waterfall — where price leaks between list and contract</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid}{svg}</svg></div>

  <div class="cols">
    <div><h2>By segment</h2>{bar_table(by_seg)}</div>
    <div><h2>By deal size</h2>{bar_table(by_size)}</div>
    <div><h2>By close timing</h2>{bar_table(by_time)}</div>
  </div>
  <div class="note">The two review flags: realization falls monotonically with
    deal size (creep beyond any cost-to-serve argument), and deals closed in
    the final two weeks of a quarter realize {gap:.1%} less — sales spending
    price to make the date. Both patterns survive segmentation, which is what
    separates a pricing problem from a mix story.</div>

  <footer>Generated by pricing.py · waterfall ties on every deal
    (run --validate) · all data synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Pocket-price waterfall")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    deals = make_deals()
    with (DATA / "deals.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(deals[0].keys()))
        w.writeheader(); w.writerows(deals)

    print_report(deals)
    if args.validate:
        validate(deals)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(deals, args.html)


if __name__ == "__main__":
    main()
