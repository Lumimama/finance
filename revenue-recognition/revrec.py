"""
Revenue Recognition: Bookings -> Billings -> Revenue
====================================================
The controller-grade view of a subscription business: a contract ledger
expanded into billing schedules and ratable recognition, producing the three
series everyone conflates and the bridges that keep them honest.

    BOOKINGS   total contract value signed in the period  (sales reality)
    BILLINGS   what was invoiced in the period             (cash reality)
    REVENUE    what was earned, ratably                    (GAAP reality)

plus the two balances they throw off:

    DEFERRED REVENUE   billed but not yet earned   (a liability)
    RPO / BACKLOG      booked but not yet earned   (disclosure, not on BS)
      of which unbilled backlog = RPO - deferred

The invariant that makes this a model rather than three charts:

    deferred(end) = deferred(begin) + billings - revenue     ... every month
    RPO(end)      = RPO(begin)      + bookings - revenue     ... every month

Both are checked to the cent, every month, in --validate. A rev-rec schedule
whose roll-forwards don't tie is how audit adjustments happen.

The generator lives in this file (contracts are simple enough not to need a
separate one): 857 contracts, 12-36 month terms, annual-upfront / quarterly /
monthly billing mixes by segment.

Run:  python3 revrec.py
      python3 revrec.py --validate
      python3 revrec.py --html examples/revrec_dashboard.html

No dependencies. Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

random.seed(20260315)

DATA = Path(__file__).parent / "data"
MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025, 2026) for m in range(1, 13)][:30]
MIDX = {m: i for i, m in enumerate(MONTHS)}
WINDOW_END = len(MONTHS) - 1   # analysis through 2026-06

SEGMENTS = {
    # weight, ACV range, term months choices, billing mix (annual/quarterly/monthly)
    "enterprise": (0.18, (80_000, 400_000), [12, 24, 36], (0.80, 0.15, 0.05)),
    "mid_market": (0.42, (18_000, 80_000), [12, 24], (0.60, 0.25, 0.15)),
    "smb":        (0.40, (3_000, 18_000), [12], (0.35, 0.20, 0.45)),
}


def make_contracts() -> list[dict]:
    out, n = [], 0
    for mi, month in enumerate(MONTHS[:-1]):
        for _ in range(round((16 + mi * 0.9) * random.uniform(0.7, 1.3))):
            n += 1
            r, cum, seg = random.random(), 0.0, "smb"
            for s, v in SEGMENTS.items():
                cum += v[0]
                if r <= cum:
                    seg = s
                    break
            _, (lo, hi), terms, (a, q, _m) = SEGMENTS[seg]
            acv = round(random.uniform(lo, hi), 2)
            term = random.choice(terms)
            tcv = round(acv * term / 12, 2)
            rb = random.random()
            billing = "annual" if rb < a else ("quarterly" if rb < a + q else "monthly")
            out.append({
                "contract_id": f"K{n:05d}", "segment": seg,
                "booked_month": month, "term_months": term,
                "acv": acv, "tcv": tcv, "billing": billing,
            })
    return out


def billing_schedule(c: dict) -> list[tuple[int, float]]:
    """(month_index, amount) invoices over the contract term."""
    start = MIDX[c["booked_month"]]
    term = c["term_months"]
    monthly = c["tcv"] / term
    if c["billing"] == "annual":
        events = [(start + k, min(12, term - k) * monthly)
                  for k in range(0, term, 12)]
    elif c["billing"] == "quarterly":
        events = [(start + k, min(3, term - k) * monthly)
                  for k in range(0, term, 3)]
    else:
        events = [(start + k, monthly) for k in range(term)]
    out = [(mi, round(amt, 2)) for mi, amt in events]
    # penny true-up on the final invoice so the schedule sums exactly to TCV
    drift = round(c["tcv"] - sum(a for _, a in out), 2)
    mi, amt = out[-1]
    out[-1] = (mi, round(amt + drift, 2))
    return out


def recognition_schedule(c: dict) -> list[tuple[int, float]]:
    """Ratable straight-line: TCV / term, monthly, rounding to the last month."""
    start = MIDX[c["booked_month"]]
    term = c["term_months"]
    per = round(c["tcv"] / term, 2)
    sched = [(start + k, per) for k in range(term)]
    # penny true-up so the schedule sums exactly to TCV
    drift = round(c["tcv"] - per * term, 2)
    mi, amt = sched[-1]
    sched[-1] = (mi, round(amt + drift, 2))
    return sched


# ---------------------------------------------------------------------------
def build_series(contracts):
    bookings = defaultdict(float)
    billings = defaultdict(float)
    revenue = defaultdict(float)
    # deferred waterfall: for the last month, when does today's deferred unwind?
    for c in contracts:
        bookings[MIDX[c["booked_month"]]] += c["tcv"]
        for mi, amt in billing_schedule(c):
            billings[mi] += amt
        for mi, amt in recognition_schedule(c):
            revenue[mi] += amt

    deferred, rpo = [], []
    d = r = 0.0
    for mi in range(len(MONTHS)):
        d = d + billings[mi] - revenue[mi]
        r = r + bookings[mi] - revenue[mi]
        deferred.append(d)
        rpo.append(r)
    return bookings, billings, revenue, deferred, rpo


def deferred_unwind(contracts, as_of: int):
    """Of deferred revenue at as_of, how much converts in each future quarter?"""
    unwind = defaultdict(float)
    for c in contracts:
        billed = sum(a for mi, a in billing_schedule(c) if mi <= as_of)
        recognized = sum(a for mi, a in recognition_schedule(c) if mi <= as_of)
        residual = round(billed - recognized, 2)
        if residual <= 0:
            continue
        # attribute the residual to future recognition months in order
        for mi, amt in recognition_schedule(c):
            if mi <= as_of or residual <= 0:
                continue
            take = min(amt, residual)
            unwind[(mi - as_of - 1) // 3] += take   # future quarter bucket
            residual -= take
    return dict(sorted(unwind.items()))


def rpo_split(contracts, as_of: int):
    """RPO split current (<=12mo) / non-current, per disclosure convention."""
    cur = noncur = 0.0
    for c in contracts:
        booked = c["tcv"] if MIDX[c["booked_month"]] <= as_of else 0.0
        if not booked:
            continue
        recognized = sum(a for mi, a in recognition_schedule(c) if mi <= as_of)
        for mi, amt in recognition_schedule(c):
            if mi <= as_of:
                continue
            if mi - as_of <= 12:
                cur += amt
            else:
                noncur += amt
    return cur, noncur


# ---------------------------------------------------------------------------
def m(x): return f"${x/1e6:,.2f}M"


def print_report(contracts) -> None:
    w = 100
    bookings, billings, revenue, deferred, rpo = build_series(contracts)
    print("=" * w)
    print(f"REVENUE RECOGNITION  |  {len(contracts):,} contracts  |  through {MONTHS[WINDOW_END]}")
    print("=" * w)
    print(f"  {'month':<9}{'bookings':>12}{'billings':>12}{'revenue':>12}"
          f"{'deferred':>12}{'RPO':>12}{'unbilled':>12}")
    print("-" * w)
    for mi in range(max(0, WINDOW_END - 11), WINDOW_END + 1):
        print(f"  {MONTHS[mi]:<9}{bookings[mi]/1e6:>11.2f}M{billings[mi]/1e6:>11.2f}M"
              f"{revenue[mi]/1e6:>11.2f}M{deferred[mi]/1e6:>11.2f}M"
              f"{rpo[mi]/1e6:>11.2f}M{(rpo[mi]-deferred[mi])/1e6:>11.2f}M")

    print(f"\nDEFERRED REVENUE UNWIND  (as of {MONTHS[WINDOW_END]}: when does the "
          f"{m(deferred[WINDOW_END])} liability convert to revenue?)")
    print("-" * w)
    for qk, amt in deferred_unwind(contracts, WINDOW_END).items():
        print(f"  Q+{qk+1:<3}{m(amt):>12}")

    cur, noncur = rpo_split(contracts, WINDOW_END)
    print(f"\nRPO DISCLOSURE  (as of {MONTHS[WINDOW_END]})")
    print("-" * w)
    print(f"  total RPO            {m(rpo[WINDOW_END]):>12}")
    print(f"  current (<=12mo)     {m(cur):>12}   {cur/rpo[WINDOW_END]:.0%}")
    print(f"  non-current          {m(noncur):>12}")
    print(f"  of which unbilled    {m(rpo[WINDOW_END]-deferred[WINDOW_END]):>12}")
    print()


def validate(contracts) -> None:
    bookings, billings, revenue, deferred, rpo = build_series(contracts)
    print("VALIDATION -- roll-forwards must tie to the cent, every month")
    print("-" * 86)
    ok = True

    # 1. deferred roll-forward
    d = 0.0
    worst_d = 0.0
    for mi in range(len(MONTHS)):
        d = d + billings[mi] - revenue[mi]
        worst_d = max(worst_d, abs(d - deferred[mi]))
    ok &= worst_d < 0.01
    print(f"  [{'ok ' if worst_d < 0.01 else 'MISS'}] deferred(end) = deferred(beg) + "
          f"billings - revenue   (max diff ${worst_d:.4f})")

    # 2. RPO roll-forward
    r = 0.0
    worst_r = 0.0
    for mi in range(len(MONTHS)):
        r = r + bookings[mi] - revenue[mi]
        worst_r = max(worst_r, abs(r - rpo[mi]))
    ok &= worst_r < 0.01
    print(f"  [{'ok ' if worst_r < 0.01 else 'MISS'}] RPO(end) = RPO(beg) + "
          f"bookings - revenue        (max diff ${worst_r:.4f})")

    # 3. per-contract: recognition schedule sums exactly to TCV
    worst_c = max(abs(sum(a for _, a in recognition_schedule(c)) - c["tcv"])
                  for c in contracts)
    ok &= worst_c < 0.01
    print(f"  [{'ok ' if worst_c < 0.01 else 'MISS'}] every contract's recognition "
          f"schedule sums to its TCV  (max diff ${worst_c:.4f})")

    # 4. per-contract: billing schedule sums exactly to TCV
    worst_b = max(abs(sum(a for _, a in billing_schedule(c)) - c["tcv"])
                  for c in contracts)
    ok &= worst_b < 0.02
    print(f"  [{'ok ' if worst_b < 0.02 else 'MISS'}] every contract's billing "
          f"schedule sums to its TCV      (max diff ${worst_b:.4f})")

    # 5. unwind of today's deferred equals today's deferred
    unw = sum(deferred_unwind(contracts, WINDOW_END).values())
    diff = abs(unw - deferred[WINDOW_END])
    ok &= diff < 1.0
    print(f"  [{'ok ' if diff < 1.0 else 'MISS'}] deferred unwind buckets sum to the "
          f"deferred balance   (diff ${diff:.2f})")

    print("-" * 86)
    print(f"  {'PASS' if ok else 'FAIL'}")


# ---------------------------------------------------------------------------
def write_html(contracts, path: Path) -> None:
    bookings, billings, revenue, deferred, rpo = build_series(contracts)
    n = WINDOW_END + 1

    W, H, PL, PT, PB = 880, 300, 80, 22, 40
    pw, ph = W - PL - 24, H - PT - PB
    series = {
        "bookings": ([bookings[i] for i in range(n)], "#8250df"),
        "billings": ([billings[i] for i in range(n)], "#d97706"),
        "revenue": ([revenue[i] for i in range(n)], "var(--line)"),
    }
    hi = max(max(v) for v, _ in series.values()) * 1.1

    def x(i): return PL + pw * i / (n - 1)
    def y(v): return PT + ph * (1 - v / hi)

    lines = "".join(
        f'<polyline points="{" ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))}" '
        f'fill="none" stroke="{c}" stroke-width="2.5" stroke-linejoin="round"/>'
        for vals, c in series.values())
    leg = "".join(f'<tspan fill="{c}">● {k}  </tspan>' for k, (_, c) in series.items())
    grid = ""
    for fr in (0, .5, 1.0):
        v = hi * fr
        grid += (f'<line x1="{PL}" y1="{y(v):.1f}" x2="{W-24}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{PL-10}" y="{y(v)+4:.1f}" text-anchor="end" class="tick">${v/1e6:.1f}M</text>')
    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{H-16}" text-anchor="middle" class="tick">{MONTHS[i]}</text>'
        for i in range(0, n, 4))

    # deferred + RPO balances
    hi2 = max(rpo[:n]) * 1.1
    def y2(v): return PT + ph * (1 - v / hi2)
    bal_lines = (
        f'<polyline points="{" ".join(f"{x(i):.1f},{y2(rpo[i]):.1f}" for i in range(n))}" '
        f'fill="none" stroke="var(--pos)" stroke-width="2.5"/>'
        f'<polyline points="{" ".join(f"{x(i):.1f},{y2(deferred[i]):.1f}" for i in range(n))}" '
        f'fill="none" stroke="var(--neg)" stroke-width="2.5"/>')
    grid2 = ""
    for fr in (0, .5, 1.0):
        v = hi2 * fr
        grid2 += (f'<line x1="{PL}" y1="{y2(v):.1f}" x2="{W-24}" y2="{y2(v):.1f}" class="grid"/>'
                  f'<text x="{PL-10}" y="{y2(v)+4:.1f}" text-anchor="end" class="tick">${v/1e6:.0f}M</text>')

    unwind = deferred_unwind(contracts, WINDOW_END)
    max_u = max(unwind.values())
    unwind_rows = "".join(
        f"<tr><td>Q+{qk+1}</td><td class='n'>${amt/1e6:,.2f}M</td>"
        f"<td><div class='bar' style='width:{amt/max_u*100:.0f}%'></div></td></tr>"
        for qk, amt in unwind.items())

    cur, noncur = rpo_split(contracts, WINDOW_END)
    last12 = range(max(0, n - 12), n)
    tbl_rows = "".join(
        f"<tr><td>{MONTHS[mi]}</td>"
        f"<td class='n'>${bookings[mi]/1e6:,.2f}</td>"
        f"<td class='n'>${billings[mi]/1e6:,.2f}</td>"
        f"<td class='n'>${revenue[mi]/1e6:,.2f}</td>"
        f"<td class='n'>${deferred[mi]/1e6:,.2f}</td>"
        f"<td class='n'>${rpo[mi]/1e6:,.2f}</td></tr>"
        for mi in last12)

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revenue Recognition · bookings → billings → revenue</title>
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
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(155px,1fr));
           gap:12px; margin-top:22px; }}
  .kpi {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
          padding:13px 15px; }}
  .kpi .k {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.06em;
             color:var(--mut); }}
  .kpi .v {{ font-size:19px; font-weight:600; margin-top:3px;
             font-variant-numeric:tabular-nums; }}
  .kpi .n2 {{ font-size:11px; color:var(--mut); margin-top:1px; }}
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
  .bar {{ background:var(--line); height:9px; border-radius:4px; min-width:2px; }}
  td:last-child {{ width:45%; }}
  .note {{ font-size:12.5px; color:var(--mut); margin:8px 2px 0; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:26px; }}
</style>
<div class="wrap">
  <h1>Revenue Recognition</h1>
  <div class="sub">Bookings → billings → revenue · {len(contracts):,} contracts ·
    ratable recognition · synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">TTM revenue</div>
      <div class="v">${sum(revenue[i] for i in last12)/1e6:,.1f}M</div></div>
    <div class="kpi"><div class="k">TTM billings</div>
      <div class="v">${sum(billings[i] for i in last12)/1e6:,.1f}M</div></div>
    <div class="kpi"><div class="k">Deferred revenue</div>
      <div class="v">${deferred[WINDOW_END]/1e6:,.1f}M</div>
      <div class="n2">billed, not yet earned</div></div>
    <div class="kpi"><div class="k">RPO</div>
      <div class="v">${rpo[WINDOW_END]/1e6:,.1f}M</div>
      <div class="n2">{cur/rpo[WINDOW_END]:.0%} current</div></div>
    <div class="kpi"><div class="k">Unbilled backlog</div>
      <div class="v">${(rpo[WINDOW_END]-deferred[WINDOW_END])/1e6:,.1f}M</div>
      <div class="n2">RPO − deferred</div></div>
  </div>

  <h2>Bookings vs billings vs revenue — monthly</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid}{lines}{ticks}
    <text x="{PL}" y="14" class="leg">{leg}</text></svg></div>
  <div class="note">The three series everyone conflates. Bookings is lumpy
    (sales), billings follows invoice schedules (cash), revenue is smooth
    (ratable). A quarter where bookings spikes and revenue doesn't move is
    working exactly as designed.</div>

  <h2>Deferred revenue and RPO — balances</h2>
  <div class="chart"><svg viewBox="0 0 {W} {H}">{grid2}{bal_lines}{ticks}
    <text x="{PL}" y="14" class="leg"><tspan fill="var(--pos)">● RPO (booked,
    unearned)  </tspan><tspan fill="var(--neg)">● Deferred (billed, unearned)
    </tspan></text></svg></div>

  <h2>Deferred unwind — when the {'{:.1f}'.format(deferred[WINDOW_END]/1e6)}M liability becomes revenue</h2>
  <div class="tbl"><table>
    <thead><tr><th>Quarter</th><th class="n">Converts</th><th></th></tr></thead>
    <tbody>{unwind_rows}</tbody></table></div>

  <h2>Monthly detail — trailing 12</h2>
  <div class="tbl"><table>
    <thead><tr><th>Month</th><th class="n">Bookings $M</th><th class="n">Billings $M</th>
      <th class="n">Revenue $M</th><th class="n">Deferred $M</th><th class="n">RPO $M</th></tr></thead>
    <tbody>{tbl_rows}</tbody></table></div>

  <footer>Generated by revrec.py · roll-forwards tie to the cent every month
    (run --validate) · all data synthetic</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Bookings/billings/revenue bridge")
    ap.add_argument("--html", type=Path, default=None)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    contracts = make_contracts()
    with (DATA / "contracts.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(contracts[0].keys()))
        w.writeheader(); w.writerows(contracts)

    print_report(contracts)
    if args.validate:
        validate(contracts)
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(contracts, args.html)


if __name__ == "__main__":
    main()
