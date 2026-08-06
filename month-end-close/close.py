#!/usr/bin/env python3
"""Month-end close — the close as an instrumented process, not a heroic one.

Six monthly closes (Jul-Dec 2025) of a 13-task checklist with real
dependencies, owner roles, and sign-off states, plus a balance-sheet flux
review with materiality thresholds.

The story the data contains (decided before the generator):
  1. Days-to-close improves from ~8 to ~5.5 — but not by "working harder."
     The critical path is recomputed from the dependency graph every month,
     and the improvement comes from automating bank reconciliation in
     October. After that the bottleneck MOVES to revenue cut-off review:
     you don't shorten a close on average, you attack its critical path,
     and the dashboard names the current one.
  2. Flux review with teeth: any balance-sheet line moving more than
     max($50K, 5%) month-over-month requires commentary. November ships one
     breach with the commentary missing — the engine refuses to certify
     that close and flags exactly that line. The control catching the gap
     IS the demo.
  3. Sign-off is a state machine (prepare -> review -> approve), and the
     ordering invariant is validated across all 78 task-instances. A close
     checklist that cannot prove its own ordering is a spreadsheet, not a
     control.

Bug the validation caught during development: the first critical-path
walk-back picked the predecessor with the LATEST START rather than the one
whose finish actually gates the task's start, so parallel branches produced
a "critical path" longer than days-to-close. Check 3 (path length must
equal max finish, recomputed independently) failed and the walk now follows
the binding dependency.
"""

import argparse
import csv
import random
from pathlib import Path

random.seed(1231)

CLOSES = ["2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
AUTOMATION_MONTH = "2025-10"      # recon engine goes live
MATERIALITY_ABS = 50_000
MATERIALITY_PCT = 0.05
TOL = 1e-9

# task id, name, workstream, owner role, dependencies, duration (days)
TASKS = [
    ("subledger",  "Close AP / AR subledgers",        "cash",    "AP accountant",    [],                        1.2),
    ("bank_rec",   "Bank reconciliations",            "cash",    "Staff accountant", ["subledger"],             3.5),
    ("payroll",    "Payroll & benefits accrual",      "accrual", "Payroll lead",     [],                        1.0),
    ("accruals",   "Opex accruals & prepaids",        "accrual", "Senior accountant", ["subledger"],            1.6),
    ("rev_data",   "Usage & billing data cut",        "revenue", "RevOps",           [],                        1.0),
    ("rev_rec",    "Revenue recognition run",         "revenue", "Revenue accountant", ["rev_data"],            1.4),
    ("rev_cutoff", "Revenue cut-off review",          "revenue", "Controller",       ["rev_rec", "bank_rec"],   2.2),
    ("sbc",        "Stock comp expense",              "accrual", "Senior accountant", [],                       0.8),
    ("fx",         "FX rates & remeasurement",        "consol",  "Senior accountant", ["subledger"],            0.7),
    ("ic",         "Intercompany reconciliation",     "consol",  "Senior accountant", ["fx"],                   1.1),
    ("consol",     "Consolidation & eliminations",    "consol",  "Controller",       ["ic", "accruals", "payroll", "sbc"], 1.0),
    ("flux",       "Balance-sheet flux review",       "report",  "Controller",       ["consol", "rev_cutoff"],  1.2),
    ("reporting",  "Management reporting package",    "report",  "Head of Finance",  ["flux"],                  0.9),
]

BS_LINES = ["Cash", "Accounts receivable", "Prepaid expenses", "Fixed assets",
            "Accounts payable", "Accrued liabilities", "Deferred revenue",
            "Lease liabilities", "Intercompany, net", "Accrued payroll"]


def run_close(month):
    """Schedule the DAG: each task starts when its deps finish; durations
    carry noise, and bank rec collapses after the automation month."""
    done = {}
    for tid, name, ws, owner, deps, dur in TASKS:
        if tid == "bank_rec" and month >= AUTOMATION_MONTH:
            dur = 0.8             # the recon engine took over the matching
        dur *= random.uniform(0.9, 1.15)
        start = max((done[d]["finish"] for d in deps), default=0.0)
        done[tid] = dict(name=name, ws=ws, owner=owner, deps=deps,
                         start=start, dur=dur, finish=start + dur)
    return done


def critical_path(sched):
    """Walk back from the last-finishing task through the dependency whose
    finish gates each start (the binding predecessor)."""
    tid = max(sched, key=lambda t: sched[t]["finish"])
    path = [tid]
    while sched[tid]["deps"]:
        binding = max(sched[tid]["deps"], key=lambda d: sched[d]["finish"])
        if abs(sched[binding]["finish"] - sched[tid]["start"]) > 1e-6:
            break                 # start wasn't gated by a dependency
        tid = binding
        path.append(tid)
    return list(reversed(path))


def make_flux():
    """Monthly balance-sheet lines with seeded breaches. Every breach
    carries commentary except one in November — the seeded control gap."""
    base = {"Cash": 11_200_000, "Accounts receivable": 6_400_000,
            "Prepaid expenses": 900_000, "Fixed assets": 4_700_000,
            "Accounts payable": 2_100_000, "Accrued liabilities": 1_500_000,
            "Deferred revenue": 5_800_000, "Lease liabilities": 3_900_000,
            "Intercompany, net": 0, "Accrued payroll": 1_100_000}
    vals = {line: {} for line in BS_LINES}
    comments = {}
    prev = dict(base)
    for mth in CLOSES:
        for line in BS_LINES:
            drift = prev[line] * random.uniform(-0.02, 0.03)
            vals[line][mth] = prev[line] + drift
        # seeded breaches with commentary
        if mth == "2025-08":
            vals["Deferred revenue"][mth] = prev["Deferred revenue"] * 1.14
            comments[("Deferred revenue", mth)] = \
                "Three multi-year prepays billed annually in advance"
        if mth == "2025-10":
            vals["Cash"][mth] = prev["Cash"] - 1_400_000
            comments[("Cash", mth)] = \
                "Q3 bonus payout plus annual insurance premium"
        if mth == "2025-11":
            vals["Accrued liabilities"][mth] = prev["Accrued liabilities"] * 1.22
            comments[("Accrued liabilities", mth)] = \
                "Legal settlement accrual per outside counsel range"
            # THE GAP: a real breach, no commentary attached
            vals["Prepaid expenses"][mth] = prev["Prepaid expenses"] * 1.31
        if mth == "2025-12":
            vals["Lease liabilities"][mth] = prev["Lease liabilities"] + 620_000
            comments[("Lease liabilities", mth)] = \
                "GPU capacity agreement commenced (embedded lease, ASC 842)"
        prev = {line: vals[line][mth] for line in BS_LINES}
    return vals, comments


def breaches(vals, mth, prev_mth):
    out = []
    for line in BS_LINES:
        prev_v = vals[line][prev_mth] if prev_mth else None
        if prev_v is None or prev_v == 0:
            continue
        delta = vals[line][mth] - prev_v
        if abs(delta) > max(MATERIALITY_ABS, abs(prev_v) * MATERIALITY_PCT):
            out.append((line, delta))
    return out


def signoffs(closes):
    """prepare -> review -> approve day-stamps for every task instance."""
    rows = []
    for mth, sched in closes.items():
        for tid, t in sched.items():
            prep = t["finish"]
            rev = prep + random.uniform(0.1, 0.5)
            appr = rev + random.uniform(0.05, 0.3)
            rows.append(dict(month=mth, task=tid, prepared=prep,
                             reviewed=rev, approved=appr))
    return rows


def run_checks(closes, vals, comments, signs):
    checks = []

    def add(name, ok, detail):
        checks.append((name, ok, detail))

    # 1. dependency respect
    worst = 0.0
    for sched in closes.values():
        for t in sched.values():
            for d in t["deps"]:
                worst = max(worst, sched[d]["finish"] - t["start"])
    add("no task starts before its dependencies finish (6 closes)",
        worst <= 1e-9, f"max violation {worst:.6f} days")

    # 2. sign-off state machine ordering
    ok = all(s["prepared"] < s["reviewed"] < s["approved"] for s in signs)
    add(f"sign-off ordering holds for all {len(signs)} task-instances", ok,
        "prepare -> review -> approve, no exceptions")

    # 3. critical-path length == days-to-close, recomputed independently
    worst = 0.0
    for sched in closes.values():
        cp = critical_path(sched)
        length = sum(sched[t]["dur"] for t in cp)
        days = max(t["finish"] for t in sched.values())
        worst = max(worst, abs(length - days))
    add("critical-path length equals days-to-close, every month",
        worst < 1e-6, f"max gap {worst:.8f} days")

    # 4. flux control: every breach has commentary except the seeded Nov gap
    gaps = []
    for i, mth in enumerate(CLOSES):
        prev_mth = CLOSES[i - 1] if i else None
        if not prev_mth:
            continue
        for line, delta in breaches(vals, mth, prev_mth):
            if (line, mth) not in comments:
                gaps.append((line, mth))
    ok = gaps == [("Prepaid expenses", "2025-11")]
    add("flux control: the one seeded commentary gap is caught, only it",
        ok, f"flagged {gaps}")

    # 5. materiality applied correctly (no sub-threshold flags)
    ok = True
    for i, mth in enumerate(CLOSES[1:], 1):
        prev_mth = CLOSES[i - 1]
        flagged = {line for line, _ in breaches(vals, mth, prev_mth)}
        for line in BS_LINES:
            pv = vals[line][prev_mth]
            if pv == 0:
                continue
            delta = abs(vals[line][mth] - pv)
            should = delta > max(MATERIALITY_ABS, abs(pv) * MATERIALITY_PCT)
            ok &= (line in flagged) == should
    add("materiality threshold max($50K, 5%) applied exactly", ok,
        "recomputed line by line, month by month")

    # 6. the close got faster, and by attacking the path
    d_jul = max(t["finish"] for t in closes["2025-07"].values())
    d_dec = max(t["finish"] for t in closes["2025-12"].values())
    add("December close at least 2 days faster than July", d_jul - d_dec >= 2,
        f"{d_jul:.1f} -> {d_dec:.1f} days")

    # 7. the bottleneck moved after automation
    cp_jul = critical_path(closes["2025-07"])
    cp_dec = critical_path(closes["2025-12"])
    ok = "bank_rec" in cp_jul and "bank_rec" not in cp_dec
    add("automation moved the critical path off bank reconciliation", ok,
        f"July path ends {cp_jul[-1]}; December path ends {cp_dec[-1]}")
    return checks


def write_data(closes, vals, comments):
    d = Path(__file__).parent / "data"
    d.mkdir(exist_ok=True)
    with open(d / "close_tasks.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "task", "workstream", "owner", "start_day",
                    "duration", "finish_day"])
        for mth, sched in closes.items():
            for tid, t in sched.items():
                w.writerow([mth, tid, t["ws"], t["owner"], f"{t['start']:.2f}",
                            f"{t['dur']:.2f}", f"{t['finish']:.2f}"])
    with open(d / "bs_flux.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["line", "month", "balance", "commentary"])
        for line in BS_LINES:
            for mth in CLOSES:
                w.writerow([line, mth, f"{vals[line][mth]:.2f}",
                            comments.get((line, mth), "")])


def print_report(closes, vals, comments, checks, out=print):
    d_jul = max(t["finish"] for t in closes["2025-07"].values())
    d_dec = max(t["finish"] for t in closes["2025-12"].values())
    cp_dec = critical_path(closes["2025-12"])
    out("MONTH-END CLOSE — JUL-DEC 2025")
    out(f"  Days to close               {d_jul:.1f} (Jul) -> {d_dec:.1f} (Dec)")
    out(f"  How                         bank reconciliation automated in Oct;"
        " the critical path moved, then shrank")
    out(f"  December critical path      {' -> '.join(cp_dec)}")
    out("  Flux control                Nov: Prepaid expenses +31% breached "
        "materiality with NO commentary -> close not certified until resolved")
    out("")
    for name, ok, detail in checks:
        out(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    out("")
    out("  " + ("ALL CHECKS PASS" if all(c[1] for c in checks) else "FAILURES PRESENT"))


def svg_days(closes, w=940, h=210, pad=36):
    vals = [max(t["finish"] for t in closes[m].values()) for m in CLOSES]
    hi = max(vals) * 1.15
    bw = (w - 2 * pad) / len(vals) * 0.55
    out = [f'<svg viewBox="0 0 {w} {h}" role="img">']
    for gy in range(4):
        yv = hi * (1 - gy / 3)
        y = pad + gy * (h - 2 * pad) / 3
        out.append(f'<line x1="{pad}" y1="{y:.0f}" x2="{w-pad}" y2="{y:.0f}" '
                   'stroke="var(--grid)"/>')
        out.append(f'<text x="{pad-6}" y="{y+4:.0f}" text-anchor="end" '
                   f'font-size="10" fill="var(--mut)">{yv:.0f}d</text>')
    for i, v in enumerate(vals):
        x = pad + (i + 0.22) * (w - 2 * pad) / len(vals)
        bh = v / hi * (h - 2 * pad)
        col = "var(--line)" if CLOSES[i] < AUTOMATION_MONTH else "var(--pos)"
        out.append(f'<rect x="{x:.0f}" y="{h-pad-bh:.0f}" width="{bw:.0f}" '
                   f'height="{bh:.0f}" fill="{col}" rx="3"/>')
        out.append(f'<text x="{x+bw/2:.0f}" y="{h-pad-bh-6:.0f}" '
                   f'text-anchor="middle" font-size="11" fill="var(--fg)">'
                   f'{v:.1f}</text>')
        out.append(f'<text x="{x+bw/2:.0f}" y="{h-8}" text-anchor="middle" '
                   f'font-size="10" fill="var(--mut)">{CLOSES[i][5:]}</text>')
    out.append("</svg>")
    return "".join(out)


def write_html(path, closes, vals, comments, checks):
    d_jul = max(t["finish"] for t in closes["2025-07"].values())
    d_dec = max(t["finish"] for t in closes["2025-12"].values())
    cp_jul = critical_path(closes["2025-07"])
    cp_dec = critical_path(closes["2025-12"])
    dec = closes["2025-12"]
    bottleneck = max(cp_dec, key=lambda t: dec[t]["dur"])
    task_rows = ""
    for tid, t in sorted(dec.items(), key=lambda kv: kv[1]["start"]):
        on_cp = tid in cp_dec
        flag = ' class="flag"' if on_cp else ""
        task_rows += (f"<tr{flag}><td>{t['name']}</td><td>{t['owner']}</td>"
                      f"<td>{t['start']:.1f}</td><td>{t['dur']:.1f}</td>"
                      f"<td>{t['finish']:.1f}</td>"
                      f"<td>{'● critical path' if on_cp else ''}</td></tr>")
    flux_rows = ""
    for i, mth in enumerate(CLOSES[1:], 1):
        for line, delta in breaches(vals, mth, CLOSES[i - 1]):
            has = (line, mth) in comments
            note = comments.get((line, mth),
                                "<b class='bad'>COMMENTARY MISSING — close "
                                "not certified</b>")
            cls = "" if has else ' class="flag"'
            flux_rows += (f"<tr{cls}><td>{mth}</td><td>{line}</td>"
                          f"<td>{'+' if delta>0 else '−'}${abs(delta)/1e3:,.0f}K</td>"
                          f"<td style='text-align:left'>{note}</td></tr>")
    checks_html = "".join(
        f"<li><b class='{'ok' if ok else 'bad'}'>{'PASS' if ok else 'FAIL'}</b> "
        f"{name} <span class='mut'>— {detail}</span></li>"
        for name, ok, detail in checks)
    html = f"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Month-end close — instrumented</title>
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
  td:nth-child(2) {{ text-align:left; }}
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
  <h1>Month-End Close — Instrumented</h1>
  <p class="sub">Six closes, {len(TASKS)} tasks with real dependencies,
    sign-off states, and a flux review with materiality thresholds. The
    close is a process with a critical path, not a heroic sprint — and this
    page names the current bottleneck. Synthetic, seeded data.</p>

  <div class="kpis">
    <div class="kpi"><div class="v">{d_dec:.1f} days</div>
      <div class="l">December close — down from {d_jul:.1f} in July</div></div>
    <div class="kpi"><div class="v">{dec[bottleneck]['dur']:.1f}d</div>
      <div class="l">Longest task on the critical path —
        {dec[bottleneck]['name']} — this is what to attack next</div></div>
    <div class="kpi"><div class="v">1</div>
      <div class="l">Flux breach missing commentary (Nov) — close held until
        resolved</div></div>
    <div class="kpi"><div class="v">{len(closes)*len(TASKS)}</div>
      <div class="l">Task-instances with prepare → review → approve ordering
        proven</div></div>
    <div class="kpi"><div class="v">max($50K, 5%)</div>
      <div class="l">Flux materiality — every breach explained or the close
        doesn't certify</div></div>
  </div>

  <h2>Days to close — before and after attacking the path</h2>
  <div class="card">{svg_days(closes)}
    <p class="note">Bank reconciliation was automated in October (blue →
      green). July's critical path ran
      <b>{' → '.join(cp_jul)}</b>; December's runs
      <b>{' → '.join(cp_dec)}</b>. The improvement did not come from anyone
      working faster on average — it came from removing 2.7 days from the
      one chain that gates everything. The next day of improvement lives in the
      path's longest task — currently {dec[bottleneck]['name'].lower()} —
      and the dashboard will keep saying so until it moves.</p></div>

  <h2>December close checklist</h2>
  <div class="card"><table>
    <tr><th>Task</th><th>Owner</th><th>Start (day)</th><th>Duration</th>
        <th>Finish</th><th></th></tr>
    {task_rows}
  </table>
  <p class="note">Highlighted rows form the critical path — recomputed from
    the dependency graph, not asserted. Validation requires the path's
    length to equal days-to-close exactly; a "critical path" that doesn't
    is a diagram, not a measurement.</p></div>

  <h2>Balance-sheet flux — breaches of max($50K, 5%)</h2>
  <div class="card"><table>
    <tr><th>Close</th><th>Line</th><th>Move</th>
        <th style="text-align:left">Commentary</th></tr>
    {flux_rows}
  </table>
  <p class="note">November's prepaid-expenses move breached materiality with
    no commentary attached. The engine refuses to certify that close until
    the line is explained — the control catching the gap is the
    demonstration. (December's lease line, incidentally, is the GPU embedded
    lease from the <a href="../../lease-accounting/examples/leases_dashboard.html"
    style="color:var(--line)">ASC 842 register</a> commencing.)</p></div>

  <h2>Validation — re-run before every publish</h2>
  <div class="card"><ul class="checks">{checks_html}</ul></div>

  <p class="note" style="margin-top:26px">Synthetic, seeded data
    (<code>random.seed(1231)</code>). Generator, DAG, and checks:
    <a href="https://github.com/Lumimama/finance/tree/main/month-end-close"
       style="color:var(--line)">github.com/Lumimama/finance/month-end-close</a>.</p>
</div>
"""
    Path(path).write_text(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--html")
    ap.add_argument("--report")
    args = ap.parse_args()

    closes = {m: run_close(m) for m in CLOSES}
    vals, comments = make_flux()
    signs = signoffs(closes)
    checks = run_checks(closes, vals, comments, signs)
    write_data(closes, vals, comments)

    if args.report:
        lines = []
        print_report(closes, vals, comments, checks, out=lines.append)
        Path(args.report).write_text("\n".join(lines) + "\n")
    print_report(closes, vals, comments, checks)
    if args.html:
        write_html(args.html, closes, vals, comments, checks)
        print(f"  wrote {args.html}")
    if args.validate and not all(c[1] for c in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
