"""
Payments Unit Economics
=======================
Per-transaction contribution by rail, region, and merchant segment, from a
quarter of transaction-level data -- the analysis behind "which volume do we
actually want more of?"

Why per-transaction and not per-P&L-line
----------------------------------------
A payments P&L aggregates rails with wildly different economics. Blended
margin can look healthy while the mix quietly rots: tap-to-pay grows fast and
earns little, cross-border earns 4x domestic debit but carries 7x the fraud.
Decisions -- pricing, incentives, which corridors to push -- happen at the
unit level, so the model works there and only then rolls up.

Contribution stack per transaction:

    revenue           take-rate on volume + fixed fee
    - rewards         funding the issuer-side value prop (credit rails)
    - fraud loss      realized, not provisioned
    - chargebacks     realized loss + a per-event ops cost
    - processing      per-transaction network/compute cost
    - incentives      merchant/consumer promos allocated to the txn
    = contribution    per transaction, and in bps of volume

Outputs: rail/region/segment tables, a contribution waterfall, a mix-shift
sensitivity ("what happens to blended take if cross-border grows 2x"), and a
self-contained HTML dashboard.

Run:  python3 unit_economics.py
      python3 unit_economics.py --html examples/unit_econ_dashboard.html

No dependencies. Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / "data" / "transactions.csv"

COST_COLS = ["rewards_cost_usd", "fraud_loss_usd", "chargeback_loss_usd",
             "processing_cost_usd", "incentive_cost_usd"]
CB_OPS_COST = 12.0   # per chargeback event, handling cost


# ---------------------------------------------------------------------------
def load() -> list[dict]:
    with DATA.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["gross_usd"] = float(r["gross_usd"])
        r["revenue_usd"] = float(r["revenue_usd"])
        for c in COST_COLS:
            r[c] = float(r[c])
        # Chargeback ops cost attaches to the event, not the dollar value.
        if r["chargeback_loss_usd"] > 0:
            r["chargeback_loss_usd"] += CB_OPS_COST
        r["contribution_usd"] = r["revenue_usd"] - sum(r[c] for c in COST_COLS)
    return rows


# ---------------------------------------------------------------------------
def rollup(rows: list[dict], key: str) -> list[dict]:
    g: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        b = g[r[key]]
        b["count"] += 1
        b["volume"] += r["gross_usd"]
        b["revenue"] += r["revenue_usd"]
        b["contribution"] += r["contribution_usd"]
        for c in COST_COLS:
            b[c] += r[c]
    out = []
    for name, b in g.items():
        out.append({
            "name": name,
            "count": int(b["count"]),
            "volume": b["volume"],
            "revenue": b["revenue"],
            "contribution": b["contribution"],
            "take_bps": b["revenue"] / b["volume"] * 10_000,
            "contribution_bps": b["contribution"] / b["volume"] * 10_000,
            "contribution_per_txn": b["contribution"] / b["count"],
            "margin_pct": b["contribution"] / b["revenue"] if b["revenue"] else 0,
            "fraud_bps": b["fraud_loss_usd"] / b["volume"] * 10_000,
            **{c: b[c] for c in COST_COLS},
        })
    return sorted(out, key=lambda x: -x["contribution"])


def waterfall(rows: list[dict]) -> list[tuple[str, float]]:
    rev = sum(r["revenue_usd"] for r in rows)
    steps = [("Net revenue", rev)]
    labels = {"rewards_cost_usd": "Rewards", "fraud_loss_usd": "Fraud",
              "chargeback_loss_usd": "Chargebacks",
              "processing_cost_usd": "Processing",
              "incentive_cost_usd": "Incentives"}
    for c in COST_COLS:
        steps.append((labels[c], -sum(r[c] for r in rows)))
    steps.append(("Contribution", sum(r["contribution_usd"] for r in rows)))
    return steps


def mix_shift(rails: list[dict], scale: dict[str, float]) -> dict:
    """Re-weight rail volumes and recompute the blended economics.

    Holds each rail's own unit economics fixed -- this isolates pure mix
    effect, which is the question pricing committees actually ask.
    """
    base_vol = sum(r["volume"] for r in rails)
    base_contrib = sum(r["contribution"] for r in rails)
    new_vol = sum(r["volume"] * scale.get(r["name"], 1.0) for r in rails)
    new_contrib = sum(r["contribution"] * scale.get(r["name"], 1.0) for r in rails)
    return {
        "base_bps": base_contrib / base_vol * 10_000,
        "new_bps": new_contrib / new_vol * 10_000,
        "base_contribution": base_contrib,
        "new_contribution": new_contrib,
        "volume_change_pct": (new_vol / base_vol - 1),
    }


# ---------------------------------------------------------------------------
def bps(x: float) -> str:
    return f"{x:,.1f} bps"


def money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def print_report(rows: list[dict]) -> None:
    w = 100
    rails = rollup(rows, "rail")
    regions = rollup(rows, "region")
    segments = rollup(rows, "merchant_segment")
    total_vol = sum(r["gross_usd"] for r in rows)
    total_rev = sum(r["revenue_usd"] for r in rows)
    total_con = sum(r["contribution_usd"] for r in rows)

    print("=" * w)
    print("PAYMENTS UNIT ECONOMICS  |  Q2 2026  |  contribution by rail / region / segment")
    print("=" * w)
    print(f"  transactions       {len(rows):>13,}")
    print(f"  gross volume       {money(total_vol):>13}")
    print(f"  net revenue        {money(total_rev):>13}   ({bps(total_rev/total_vol*10_000)})")
    print(f"  contribution       {money(total_con):>13}   ({bps(total_con/total_vol*10_000)}, "
          f"{total_con/total_rev:.1%} of revenue)")

    print(f"\nCONTRIBUTION WATERFALL (quarter)")
    print("-" * w)
    for label, v in waterfall(rows):
        print(f"  {label:<14}{money(v):>13}")

    def table(title: str, data: list[dict]) -> None:
        print(f"\n{title}")
        print("-" * w)
        print(f"  {'':<20}{'txns':>9}{'volume':>13}{'take':>11}{'contrib':>11}"
              f"{'contrib/txn':>13}{'margin':>9}{'fraud':>10}")
        for r in data:
            print(f"  {r['name']:<20}{r['count']:>9,}{money(r['volume']):>13}"
                  f"{bps(r['take_bps']):>11}{bps(r['contribution_bps']):>11}"
                  f"{'$'+format(r['contribution_per_txn'], '.4f'):>13}{r['margin_pct']:>8.1%}"
                  f"{bps(r['fraud_bps']):>10}")

    table("BY RAIL", rails)
    table("BY REGION", regions)
    table("BY MERCHANT SEGMENT", segments)

    print(f"\nMIX-SHIFT SENSITIVITY  (unit economics held fixed; pure mix effect)")
    print("-" * w)
    scenarios = [
        ("Cross-border volume 2x", {"cross_border": 2.0}),
        ("Tap-to-pay volume 2x", {"tap_to_pay": 2.0}),
        ("E-com credit +50%", {"ecom_credit": 1.5}),
        ("Debit shifts to credit (-25% / +25%)",
         {"domestic_debit": 0.75, "domestic_credit": 1.25}),
    ]
    base = mix_shift(rails, {})
    print(f"  {'scenario':<40}{'blended contrib':>17}{'Δ vs base':>12}{'Δ contribution $':>18}")
    print(f"  {'base':<40}{bps(base['base_bps']):>17}{'':>12}{'':>18}")
    for name, scale in scenarios:
        s = mix_shift(rails, scale)
        print(f"  {name:<40}{bps(s['new_bps']):>17}"
              f"{s['new_bps']-s['base_bps']:>+9.1f} bps"
              f"{money(s['new_contribution']-s['base_contribution']):>18}")
    print()


# ---------------------------------------------------------------------------
def write_html(rows: list[dict], path: Path) -> None:
    rails = rollup(rows, "rail")
    regions = rollup(rows, "region")
    segments = rollup(rows, "merchant_segment")
    steps = waterfall(rows)
    total_vol = sum(r["gross_usd"] for r in rows)
    total_rev = sum(r["revenue_usd"] for r in rows)
    total_con = sum(r["contribution_usd"] for r in rows)

    # --- waterfall SVG ---
    W, H, PL, PT, PB = 880, 300, 90, 24, 46
    pw, ph = W - PL - 24, H - PT - PB
    hi = steps[0][1] * 1.1
    bw = pw / len(steps) * 0.6
    gap = pw / len(steps)

    def y(v): return PT + ph * (1 - v / hi)

    svg, running = "", 0.0
    for i, (label, v) in enumerate(steps):
        cx = PL + gap * i + gap / 2
        total_bar = (i == 0 or i == len(steps) - 1)
        if total_bar:
            top, bot = y(v), y(0)
            running = v
            cls = "wf-total"
        else:
            start, end = running, running + v
            top, bot = y(max(start, end)), y(min(start, end))
            running = end
            cls = "wf-neg"
        svg += (f'<rect x="{cx-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                f'height="{max(bot-top,1.5):.1f}" class="{cls}" rx="2"/>'
                f'<text x="{cx:.1f}" y="{top-7:.1f}" text-anchor="middle" class="wv">'
                f'{"" if total_bar else "−"}${abs(v)/1000:,.1f}K</text>'
                f'<text x="{cx:.1f}" y="{H-18:.1f}" text-anchor="middle" class="tick">{label}</text>')
    grid = ""
    for fr in (0, .5, 1.0):
        v = hi * fr
        grid += (f'<line x1="{PL}" y1="{y(v):.1f}" x2="{W-24}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{PL-10}" y="{y(v)+4:.1f}" text-anchor="end" class="tick">'
                 f'${v/1000:,.0f}K</text>')

    def table_html(data: list[dict]) -> str:
        rows_h = "".join(
            f"<tr><td>{r['name'].replace('_',' ')}</td>"
            f"<td class='n'>{r['count']:,}</td>"
            f"<td class='n'>${r['volume']:,.0f}</td>"
            f"<td class='n'>{r['take_bps']:.1f}</td>"
            f"<td class='n b'>{r['contribution_bps']:.1f}</td>"
            f"<td class='n'>${r['contribution_per_txn']:.4f}</td>"
            f"<td class='n'>{r['margin_pct']:.1%}</td>"
            f"<td class='n'>{r['fraud_bps']:.1f}</td></tr>"
            for r in data)
        return f"""<div class="tbl"><table>
      <thead><tr><th></th><th class="n">Txns</th><th class="n">Volume</th>
        <th class="n">Take bps</th><th class="n">Contrib bps</th>
        <th class="n">Contrib/txn</th><th class="n">Margin</th>
        <th class="n">Fraud bps</th></tr></thead>
      <tbody>{rows_h}</tbody></table></div>"""

    base = mix_shift(rails, {})
    scen_rows = ""
    for name, scale in [("Cross-border volume 2×", {"cross_border": 2.0}),
                        ("Tap-to-pay volume 2×", {"tap_to_pay": 2.0}),
                        ("E-com credit +50%", {"ecom_credit": 1.5}),
                        ("Debit → credit shift (−25% / +25%)",
                         {"domestic_debit": 0.75, "domestic_credit": 1.25})]:
        s = mix_shift(rails, scale)
        d = s["new_bps"] - s["base_bps"]
        dc = s["new_contribution"] - s["base_contribution"]
        cls = "pos" if d >= 0 else "neg"
        scen_rows += (f"<tr><td>{name}</td>"
                      f"<td class='n'>{s['new_bps']:.1f}</td>"
                      f"<td class='n {cls}'>{d:+.1f}</td>"
                      f"<td class='n {cls}'>${dc:+,.0f}</td></tr>")

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Payments Unit Economics · Q2 2026</title>
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
        color:var(--mut); margin:30px 0 12px; font-weight:600; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
           gap:12px; margin-top:22px; }}
  .kpi {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
          padding:13px 15px; }}
  .kpi .k {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
             color:var(--mut); }}
  .kpi .v {{ font-size:20px; font-weight:600; margin-top:3px;
             font-variant-numeric:tabular-nums; }}
  .kpi .n2 {{ font-size:11px; color:var(--mut); margin-top:1px; }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .wf-total {{ fill:var(--line); }} .wf-neg {{ fill:var(--neg); }}
  .wv {{ fill:var(--fg); font-size:11px; font-weight:600; }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th,td {{ padding:7px 11px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  td:first-child {{ text-transform:capitalize; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .b {{ font-weight:600; }} .neg {{ color:var(--neg); }} .pos {{ color:var(--pos); }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Payments Unit Economics</h1>
  <div class="sub">Q2 2026 · contribution per transaction by rail, region, segment · synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Transactions</div><div class="v">{len(rows):,}</div></div>
    <div class="kpi"><div class="k">Gross volume</div><div class="v">${total_vol/1e6:,.1f}M</div></div>
    <div class="kpi"><div class="k">Net revenue</div><div class="v">${total_rev/1e3:,.0f}K</div>
      <div class="n2">{total_rev/total_vol*10_000:.1f} bps of volume</div></div>
    <div class="kpi"><div class="k">Contribution</div><div class="v">${total_con/1e3:,.0f}K</div>
      <div class="n2">{total_con/total_rev:.1%} of revenue</div></div>
    <div class="kpi"><div class="k">Contribution yield</div><div class="v">{total_con/total_vol*10_000:.1f} bps</div></div>
  </div>

  <h2>Contribution waterfall — quarter</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}" role="img"
    aria-label="Contribution waterfall">{grid}{svg}</svg></div>

  <h2>By rail</h2>
  {table_html(rails)}

  <h2>By region</h2>
  {table_html(regions)}

  <h2>By merchant segment</h2>
  {table_html(segments)}

  <h2>Mix-shift sensitivity — unit economics held fixed</h2>
  <div class="tbl"><table>
    <thead><tr><th>Scenario</th><th class="n">Blended contrib bps</th>
      <th class="n">Δ bps</th><th class="n">Δ contribution</th></tr></thead>
    <tbody>
      <tr><td>Base</td><td class="n">{base['base_bps']:.1f}</td><td class="n"></td><td class="n"></td></tr>
      {scen_rows}
    </tbody>
  </table></div>

  <footer>Generated by unit_economics.py · all data synthetic · contribution =
    revenue − rewards − fraud − chargebacks − processing − incentives</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Per-transaction payments unit economics")
    ap.add_argument("--html", type=Path, default=None)
    args = ap.parse_args()
    rows = load()
    print_report(rows)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(rows, args.html)


if __name__ == "__main__":
    main()
