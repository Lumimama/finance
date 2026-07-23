"""
13-Week Direct-Method Cash Forecast
==================================

A 13-week cash forecast is the one report that tells you whether the company
survives the quarter. It is also, in most finance orgs, a spreadsheet that
one person maintains by hand and nobody else can safely open.

This is that spreadsheet as code. It builds the forecast from the three
sources the data actually lives in -- the AR aging, the AP aging, and the
recurring commitments that never appear in either -- and it answers the four
questions the report exists to answer:

  1. What is the low point, and which week does it land in?
  2. Does that low point breach the floor we've told the board about?
  3. How many weeks of runway are left at the current burn?
  4. What happens to all three answers if collections slip?

The direct method matters here. An indirect forecast starts from net income
and adjusts; it's the right tool for a 12-month plan and the wrong one for a
13-week window, because the thing that puts a company in trouble over 13
weeks is timing, not profitability. Payroll clears on the 15th whether or
not the enterprise invoice cleared on the 12th.

Usage
-----
    python cash_forecast.py
    python cash_forecast.py --collections-slip 14 --min-cash-floor 5000000
    python cash_forecast.py --revenue-haircut 0.10 --ap-stretch 15
    python cash_forecast.py --html forecast.html --csv forecast.csv
"""

from __future__ import annotations

import argparse
import calendar
import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).parent / "data"
AS_OF = date(2026, 4, 6)
OPENING_CASH = 14_850_000.0
HORIZON_WEEKS = 13

# Days after the due date that each segment actually pays. These are the
# assumptions that drive the entire forecast, which is why they live here in
# one visible block rather than buried in the collection logic. In practice
# you derive them from your own trailing-twelve-month collection history and
# revisit them quarterly.
COLLECTION_LAG_DAYS = {"enterprise": 21, "mid_market": 9, "smb": 3}

# An invoice that is already past due does not collect on due+lag (a date in
# the past). Assume it lands this many days out from the as-of date instead.
PAST_DUE_CATCHUP_DAYS = {"enterprise": 12, "mid_market": 8, "smb": 5}

# Reserve against forecast collections. Not a bad-debt provision for GAAP --
# a haircut so the forecast doesn't assume every dollar invoiced arrives.
COLLECTION_RESERVE = 0.015


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
@dataclass
class Assumptions:
    as_of: date = AS_OF
    opening_cash: float = OPENING_CASH
    weeks: int = HORIZON_WEEKS
    collections_slip_days: int = 0
    revenue_haircut: float = 0.0
    ap_stretch_days: int = 0
    reserve: float = COLLECTION_RESERVE
    min_cash_floor: float | None = None


@dataclass
class Week:
    index: int
    start: date
    end: date
    collections: float = 0.0
    ap_payments: float = 0.0
    payroll: float = 0.0
    other: float = 0.0
    opening: float = 0.0
    closing: float = 0.0
    detail: list[tuple[str, float]] = field(default_factory=list)

    @property
    def outflows(self) -> float:
        return self.ap_payments + self.payroll + self.other

    @property
    def net(self) -> float:
        return self.collections - self.outflows


def read_csv(name: str) -> list[dict]:
    with (DATA / name).open() as f:
        return list(csv.DictReader(f))


def build_weeks(a: Assumptions) -> list[Week]:
    return [
        Week(
            index=i + 1,
            start=a.as_of + timedelta(days=7 * i),
            end=a.as_of + timedelta(days=7 * i + 6),
        )
        for i in range(a.weeks)
    ]


def week_for(weeks: list[Week], d: date) -> Week | None:
    """The week bucket a date falls into, or None if outside the horizon."""
    for w in weeks:
        if w.start <= d <= w.end:
            return w
    return None


# ---------------------------------------------------------------------------
# Cash movements
# ---------------------------------------------------------------------------
def expected_collection_date(due: date, segment: str, a: Assumptions) -> date:
    lag = COLLECTION_LAG_DAYS.get(segment, 14) + a.collections_slip_days
    expected = due + timedelta(days=lag)
    if expected < a.as_of:
        # Already past due as of today: assume a catch-up window instead of
        # booking the cash in a week that has already happened.
        catchup = PAST_DUE_CATCHUP_DAYS.get(segment, 10) + a.collections_slip_days
        expected = a.as_of + timedelta(days=catchup)
    return expected


def apply_collections(weeks: list[Week], a: Assumptions) -> float:
    """Returns total collections falling outside the horizon (informational)."""
    beyond = 0.0
    for row in read_csv("ar_open.csv"):
        amount = float(row["amount"])
        amount *= 1 - a.reserve
        amount *= 1 - a.revenue_haircut
        d = expected_collection_date(date.fromisoformat(row["due_date"]), row["segment"], a)
        w = week_for(weeks, d)
        if w is None:
            beyond += amount
        else:
            w.collections += amount
    return beyond


def apply_ap(weeks: list[Week], a: Assumptions) -> None:
    for row in read_csv("ap_open.csv"):
        amount = float(row["amount"])
        due = date.fromisoformat(row["due_date"]) + timedelta(days=a.ap_stretch_days)
        # Past-due bills get paid in the current week, not retroactively.
        pay_date = max(due, a.as_of)
        w = week_for(weeks, pay_date)
        if w is not None:
            w.ap_payments += amount
            w.detail.append((f"AP: {row['vendor']}", -amount))


def month_days(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def recurring_dates(cadence: str, day: str, a: Assumptions) -> list[date]:
    """Expand a recurring commitment into concrete dates inside the horizon."""
    start, end = a.as_of, a.as_of + timedelta(days=7 * a.weeks - 1)
    out: list[date] = []

    y, m = start.year, start.month
    # Walk one month before through one month after the window to catch edges.
    for _ in range(a.weeks // 4 + 3):
        if cadence == "semimonthly":
            candidates = [date(y, m, 15), date(y, m, month_days(y, m))]
        elif cadence == "monthly":
            dom = min(int(day or 1), month_days(y, m))
            candidates = [date(y, m, dom)]
        elif cadence == "quarterly":
            candidates = (
                [date(y, m, min(int(day or 15), month_days(y, m)))] if m % 3 == 0 else []
            )
        else:
            raise ValueError(f"unknown cadence: {cadence}")

        out.extend(c for c in candidates if start <= c <= end)
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return sorted(set(out))


def apply_recurring(weeks: list[Week], a: Assumptions) -> None:
    for row in read_csv("recurring.csv"):
        amount = float(row["amount"])
        for d in recurring_dates(row["cadence"], row["day"], a):
            w = week_for(weeks, d)
            if w is None:
                continue
            if row["category"] == "payroll":
                w.payroll += amount
            else:
                w.other += amount
            w.detail.append((row["name"], -amount))


def roll_forward(weeks: list[Week], a: Assumptions) -> None:
    cash = a.opening_cash
    for w in weeks:
        w.opening = cash
        cash += w.net
        w.closing = cash


def build_forecast(a: Assumptions) -> tuple[list[Week], float]:
    weeks = build_weeks(a)
    beyond = apply_collections(weeks, a)
    apply_ap(weeks, a)
    apply_recurring(weeks, a)
    roll_forward(weeks, a)
    return weeks, beyond


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def summarize(weeks: list[Week], a: Assumptions) -> dict:
    trough = min(weeks, key=lambda w: w.closing)
    ending = weeks[-1].closing
    total_net = ending - a.opening_cash
    avg_weekly_burn = -total_net / len(weeks)  # positive number means burning

    if avg_weekly_burn > 0:
        runway_weeks = ending / avg_weekly_burn
    else:
        runway_weeks = float("inf")

    breaches = []
    if a.min_cash_floor is not None:
        breaches = [w for w in weeks if w.closing < a.min_cash_floor]

    return {
        "opening": a.opening_cash,
        "ending": ending,
        "total_net": total_net,
        "trough_week": trough.index,
        "trough_date": trough.end,
        "trough_cash": trough.closing,
        "avg_weekly_burn": avg_weekly_burn,
        "runway_weeks": runway_weeks,
        "breaches": breaches,
        "total_collections": sum(w.collections for w in weeks),
        "total_outflows": sum(w.outflows for w in weeks),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def usd(x: float) -> str:
    sign = "-" if round(x) < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def print_forecast(weeks: list[Week], s: dict, a: Assumptions, beyond: float) -> None:
    width = 104
    print("=" * width)
    print(f"13-WEEK CASH FORECAST  |  as of {a.as_of.isoformat()}  |  direct method")
    if a.collections_slip_days or a.revenue_haircut or a.ap_stretch_days:
        parts = []
        if a.collections_slip_days:
            parts.append(f"collections slip +{a.collections_slip_days}d")
        if a.revenue_haircut:
            parts.append(f"collections haircut -{a.revenue_haircut:.0%}")
        if a.ap_stretch_days:
            parts.append(f"AP stretched +{a.ap_stretch_days}d")
        print(f"SCENARIO: {', '.join(parts)}")
    print("=" * width)
    hdr = (
        f"{'Wk':>3} {'Week ending':<13}{'Opening':>13}{'Collections':>13}"
        f"{'AP':>12}{'Payroll':>12}{'Other':>11}{'Net':>13}{'Closing':>14}"
    )
    print(hdr)
    print("-" * width)
    for w in weeks:
        marker = " <" if w.index == s["trough_week"] else ""
        print(
            f"{w.index:>3} {w.end.isoformat():<13}{usd(w.opening):>13}"
            f"{usd(w.collections):>13}{usd(-w.ap_payments):>12}"
            f"{usd(-w.payroll):>12}{usd(-w.other):>11}{usd(w.net):>13}"
            f"{usd(w.closing):>14}{marker}"
        )
    print("-" * width)
    print(
        f"{'':>3} {'Total':<13}{'':>13}{usd(s['total_collections']):>13}"
        f"{usd(-sum(w.ap_payments for w in weeks)):>12}"
        f"{usd(-sum(w.payroll for w in weeks)):>12}"
        f"{usd(-sum(w.other for w in weeks)):>11}{usd(s['total_net']):>13}"
    )
    print()

    print("SUMMARY")
    print("-" * width)
    print(f"  Opening cash                {usd(s['opening']):>16}")
    print(f"  Ending cash (week 13)       {usd(s['ending']):>16}")
    print(f"  Net change                  {usd(s['total_net']):>16}")
    print(
        f"  Low point                   {usd(s['trough_cash']):>16}"
        f"   week {s['trough_week']} (ending {s['trough_date'].isoformat()})"
    )
    print(f"  Average weekly burn         {usd(s['avg_weekly_burn']):>16}")
    if s["runway_weeks"] == float("inf"):
        print("  Runway                          cash-flow positive")
    else:
        print(
            f"  Runway at current burn      {s['runway_weeks']:>13.1f} wks"
            f"   ({s['runway_weeks'] / 4.33:.1f} months)"
        )
    if beyond > 0:
        print(f"  AR collecting after week 13 {usd(beyond):>16}   (not in this forecast)")
    print()

    if a.min_cash_floor is not None:
        print(f"COVENANT / BOARD FLOOR: {usd(a.min_cash_floor)}")
        print("-" * width)
        if not s["breaches"]:
            headroom = s["trough_cash"] - a.min_cash_floor
            print(f"  PASS - low point clears the floor by {usd(headroom)}")
        else:
            first = s["breaches"][0]
            print(f"  BREACH - {len(s['breaches'])} week(s) below the floor")
            print(f"  First breach: week {first.index} (ending {first.end.isoformat()}), "
                  f"{usd(first.closing)}, short by {usd(a.min_cash_floor - first.closing)}")
        print()


def write_csv(weeks: list[Week], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["week", "week_ending", "opening", "collections", "ap_payments",
                    "payroll", "other", "net", "closing"])
        for k in weeks:
            w.writerow([k.index, k.end.isoformat(), round(k.opening, 2),
                        round(k.collections, 2), round(k.ap_payments, 2),
                        round(k.payroll, 2), round(k.other, 2), round(k.net, 2),
                        round(k.closing, 2)])
    print(f"Wrote {path}")


def write_html(weeks: list[Week], s: dict, a: Assumptions, path: Path) -> None:
    """Self-contained HTML. No CDN, no build step, opens from disk."""
    cash = [w.closing for w in weeks]
    lo, hi = min(cash + [a.min_cash_floor or min(cash)]), max(cash + [a.opening_cash])
    pad = (hi - lo) * 0.15 or 1
    lo, hi = lo - pad, hi + pad

    W, H, PADL, PADR, PADT, PADB = 900, 340, 80, 30, 24, 44
    plot_w, plot_h = W - PADL - PADR, H - PADT - PADB

    def x(i: int) -> float:
        return PADL + plot_w * i / (len(weeks) - 1)

    def y(v: float) -> float:
        return PADT + plot_h * (1 - (v - lo) / (hi - lo))

    line = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(cash))
    area = f"{PADL},{y(lo)} " + line + f" {x(len(weeks) - 1):.1f},{y(lo)}"

    floor_svg = ""
    if a.min_cash_floor is not None:
        fy = y(a.min_cash_floor)
        floor_svg = (
            f'<line x1="{PADL}" y1="{fy:.1f}" x2="{W - PADR}" y2="{fy:.1f}" '
            f'class="floor"/>'
            f'<text x="{W - PADR}" y="{fy - 7:.1f}" text-anchor="end" class="lbl-floor">'
            f'floor ${a.min_cash_floor:,.0f}</text>'
        )

    ticks = "".join(
        f'<text x="{x(i):.1f}" y="{H - 16}" text-anchor="middle" class="tick">W{w.index}</text>'
        for i, w in enumerate(weeks)
    )
    gridlines = ""
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        v = lo + (hi - lo) * frac
        gy = y(v)
        gridlines += (
            f'<line x1="{PADL}" y1="{gy:.1f}" x2="{W - PADR}" y2="{gy:.1f}" class="grid"/>'
            f'<text x="{PADL - 10}" y="{gy + 4:.1f}" text-anchor="end" class="tick">'
            f'${v / 1e6:.1f}M</text>'
        )

    # Anchor the trough label inward when the low point sits at either edge,
    # or the text runs off the viewBox.
    ti = s["trough_week"] - 1
    if ti >= len(weeks) - 2:
        anchor, lx = "end", x(ti) - 8
    elif ti <= 1:
        anchor, lx = "start", x(ti) + 8
    else:
        anchor, lx = "middle", x(ti)
    trough_svg = (
        f'<circle cx="{x(ti):.1f}" cy="{y(cash[ti]):.1f}" r="5" class="trough"/>'
        f'<text x="{lx:.1f}" y="{y(cash[ti]) + 22:.1f}" text-anchor="{anchor}" '
        f'class="lbl-trough">low ${cash[ti]:,.0f}</text>'
    )

    rows = "".join(
        f"<tr><td>{w.index}</td><td>{w.end.isoformat()}</td>"
        f"<td class='n'>{usd(w.collections)}</td>"
        f"<td class='n'>{usd(-w.ap_payments)}</td>"
        f"<td class='n'>{usd(-w.payroll)}</td>"
        f"<td class='n'>{usd(-w.other)}</td>"
        f"<td class='n {'neg' if w.net < 0 else 'pos'}'>{usd(w.net)}</td>"
        f"<td class='n b'>{usd(w.closing)}</td></tr>"
        for w in weeks
    )

    runway = (
        "cash-flow positive"
        if s["runway_weeks"] == float("inf")
        else f"{s['runway_weeks']:.1f} wks"
    )

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>13-Week Cash Forecast &middot; {a.as_of.isoformat()}</title>
<style>
  :root {{ color-scheme: light dark; --fg:#12151a; --mut:#5d6673; --bg:#fff;
           --line:#1f6feb; --fill:#1f6feb18; --grid:#e6e9ee; --neg:#b3261e;
           --pos:#0f7b3f; --card:#fbfcfd; --bd:#e6e9ee; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg:#e8ebf0; --mut:#98a2b3; --bg:#0d1117; --line:#58a6ff;
             --fill:#58a6ff22; --grid:#232a33; --neg:#ff7b72; --pos:#3fb950;
             --card:#141a22; --bd:#232a33; }}
  }}
  body {{ margin:0; padding:32px; background:var(--bg); color:var(--fg);
          font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:960px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }}
  .sub {{ color:var(--mut); font-size:13px; margin-bottom:28px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
           gap:12px; margin-bottom:28px; }}
  .kpi {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
          padding:14px 16px; }}
  .kpi .k {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em;
             color:var(--mut); }}
  .kpi .v {{ font-size:19px; font-weight:600; margin-top:4px;
             font-variant-numeric:tabular-nums; }}
  .chart {{ background:var(--card); border:1px solid var(--bd); border-radius:10px;
            padding:8px; margin-bottom:28px; overflow-x:auto; }}
  svg {{ display:block; max-width:100%; height:auto; }}
  .grid {{ stroke:var(--grid); stroke-width:1; }}
  .floor {{ stroke:var(--neg); stroke-width:1.5; stroke-dasharray:5 4; }}
  .area {{ fill:var(--fill); }}
  .cash {{ fill:none; stroke:var(--line); stroke-width:2.5;
           stroke-linejoin:round; stroke-linecap:round; }}
  .trough {{ fill:var(--neg); }}
  .tick {{ fill:var(--mut); font-size:11px; }}
  .lbl-floor {{ fill:var(--neg); font-size:11px; }}
  .lbl-trough {{ fill:var(--neg); font-size:11px; font-weight:600; }}
  .tbl {{ overflow-x:auto; border:1px solid var(--bd); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th,td {{ padding:8px 12px; text-align:left; border-bottom:1px solid var(--bd);
           white-space:nowrap; }}
  th {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em;
        color:var(--mut); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .b {{ font-weight:600; }} .neg {{ color:var(--neg); }} .pos {{ color:var(--pos); }}
  footer {{ color:var(--mut); font-size:12px; margin-top:24px; }}
</style>
<div class="wrap">
  <h1>13-Week Cash Forecast</h1>
  <div class="sub">Direct method &middot; as of {a.as_of.isoformat()} &middot;
    synthetic data</div>

  <div class="kpis">
    <div class="kpi"><div class="k">Opening</div><div class="v">{usd(s['opening'])}</div></div>
    <div class="kpi"><div class="k">Week 13</div><div class="v">{usd(s['ending'])}</div></div>
    <div class="kpi"><div class="k">Low point</div><div class="v">{usd(s['trough_cash'])}</div></div>
    <div class="kpi"><div class="k">Avg weekly burn</div><div class="v">{usd(s['avg_weekly_burn'])}</div></div>
    <div class="kpi"><div class="k">Runway</div><div class="v">{runway}</div></div>
  </div>

  <div class="chart">
    <svg viewBox="0 0 {W} {H}" role="img" aria-label="Projected cash balance by week">
      {gridlines}
      <polygon class="area" points="{area}"/>
      <polyline class="cash" points="{line}"/>
      {floor_svg}
      {trough_svg}
      {ticks}
    </svg>
  </div>

  <div class="tbl"><table>
    <thead><tr><th>Wk</th><th>Ending</th><th class="n">Collections</th>
      <th class="n">AP</th><th class="n">Payroll</th><th class="n">Other</th>
      <th class="n">Net</th><th class="n">Closing</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>

  <footer>Generated by cash_forecast.py. All figures synthetic.</footer>
</div>
"""
    path.write_text(html)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="13-week direct-method cash forecast")
    ap.add_argument("--opening-cash", type=float, default=OPENING_CASH)
    ap.add_argument("--weeks", type=int, default=HORIZON_WEEKS)
    ap.add_argument("--collections-slip", type=int, default=0, metavar="DAYS",
                    help="Push every collection out by N days")
    ap.add_argument("--revenue-haircut", type=float, default=0.0, metavar="PCT",
                    help="Reduce all collections by this fraction, e.g. 0.10")
    ap.add_argument("--ap-stretch", type=int, default=0, metavar="DAYS",
                    help="Delay AP payments by N days")
    ap.add_argument("--min-cash-floor", type=float, default=None,
                    help="Board or covenant minimum; reports breaches")
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--html", type=Path, default=None)
    args = ap.parse_args()

    a = Assumptions(
        opening_cash=args.opening_cash,
        weeks=args.weeks,
        collections_slip_days=args.collections_slip,
        revenue_haircut=args.revenue_haircut,
        ap_stretch_days=args.ap_stretch,
        min_cash_floor=args.min_cash_floor,
    )

    weeks, beyond = build_forecast(a)
    s = summarize(weeks, a)
    print_forecast(weeks, s, a, beyond)

    if args.csv:
        write_csv(weeks, args.csv)
    if args.html:
        write_html(weeks, s, a, args.html)


if __name__ == "__main__":
    main()
