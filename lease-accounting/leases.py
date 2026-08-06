#!/usr/bin/env python3
"""ASC 842 lease accounting — a lease register whose every schedule must
amortize to exactly zero, and whose most important lease never used the word.

The story the data contains (decided before the generator):
  1. A "GPU capacity services agreement" — 48 months, dedicated racks — is
     never called a lease by its contract. The identified-asset and control
     tests say it is one, and the specialized-asset criterion makes it a
     finance lease. Embedded leases in compute contracts are the live ASC 842
     question for AI companies.
  2. One office lease prices out at PV/fair-value = 89% — just under the 90%
     "substantially all" threshold. Classification: operating, with the
     judgment documented instead of buried. Bright lines were removed from
     ASC 842 on purpose; the register says which side of the line it stands
     on and why.
  3. Two sub-12-month leases take the short-term exemption: expensed, no ROU,
     no liability — and validation asserts they stay off the balance sheet.

Identities enforced by --validate (the quality bar):
  - opening liability = PV of remaining payments at the IBR, to the cent
  - liability roll-forward (beg + interest - payment = end) lands at exactly
    zero in the final month of every lease
  - ROU amortizes to exactly zero; for operating leases the single lease
    cost is straight-line (amortization is the plug: cost - interest)
  - undiscounted remaining payments - imputed interest = carrying amount
    (the disclosure maturity table must tie to the liability)
  - operating lease lifetime expense = lifetime payments

Bug the validation caught during development: escalating office leases were
first straight-lined from the *initial* monthly rent, not total payments over
the term. Every escalating lease failed the lifetime-expense identity by the
sum of its escalations. The identity existed precisely to catch that.
"""

import argparse
import csv
import random
from pathlib import Path

random.seed(842)

AS_OF = (2025, 12)          # balance-sheet date: Dec 31, 2025
TOL = 0.01

# IBR by commencement year, plus asset-class spread (bps)
IBR_BASE = {2022: 0.045, 2023: 0.055, 2024: 0.060, 2025: 0.058}
IBR_SPREAD = {"office": 0.0, "vehicle": 0.008, "equipment": 0.005,
              "datacenter": 0.010}


def months_between(a, b):
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


def add_months(ym, n):
    y, m = ym
    t = (y * 12 + m - 1) + n
    return (t // 12, t % 12 + 1)


def pv(payments, rate_m):
    return sum(p / (1 + rate_m) ** (i + 1) for i, p in enumerate(payments))


def make_register():
    """~30 leases. Fixed 3% annual escalators on offices; flat elsewhere."""
    reg = []

    def lease(name, cls, start, term, pay0, esc, fv=None, note="",
              short=False, embedded=False):
        year = start[0]
        rate = IBR_BASE[year] + IBR_SPREAD[cls]
        pays = []
        for k in range(term):
            step = 1 + esc if esc else 1
            pays.append(round(pay0 * step ** (k // 12), 2))
        reg.append(dict(name=name, cls=cls, start=start, term=term,
                        payments=pays, rate=rate, fv=fv, note=note,
                        short=short, embedded=embedded))

    # offices — operating, 3% escalators
    lease("HQ — Mission St, SF", "office", (2023, 4), 84, 92_000, 0.03,
          fv=9_800_000)
    lease("NYC office — Hudson Yards", "office", (2024, 2), 60, 61_000, 0.03,
          fv=5_400_000)
    lease("Austin office", "office", (2024, 9), 48, 24_000, 0.03,
          fv=2_300_000)
    # the 89% judgment case: fair value derived so PV/FV lands at 88.9% —
    # deliberately just under the 90% "substantially all" practice threshold
    _pays = [round(48_500 * (1.03) ** (k // 12), 2) for k in range(72)]
    _pv = pv(_pays, (IBR_BASE[2025] + IBR_SPREAD["office"]) / 12)
    lease("London office — Shoreditch", "office", (2025, 1), 72, 48_500, 0.03,
          fv=round(_pv / 0.889), note="PV/FV just under the 90% line")
    # the embedded lease
    lease("GPU capacity services agreement", "datacenter", (2025, 3), 48,
          240_000, 0.0, fv=11_600_000, embedded=True,
          note="contract says 'services'; the asset says otherwise")
    # vehicles & equipment — finance (ownership transfer / specialized)
    for i in range(9):
        y = random.choice([2023, 2024, 2025])
        start = (y, random.randint(1, 12))
        term = random.choice([36, 48])
        pay = random.randint(1_400, 3_800)
        lease(f"Fleet vehicle #{101+i}", "vehicle", start, term, pay, 0.0,
              fv=round(pay * term * 0.86))
    for i in range(12):
        y = random.choice([2022, 2023, 2024, 2025])
        start = (y, random.randint(1, 12))
        term = random.choice([24, 36, 60])
        pay = random.randint(2_500, 11_000)
        lease(f"Lab equipment #{201+i}", "equipment", start, term, pay, 0.0,
              fv=round(pay * term * random.uniform(0.80, 0.93)))
    # short-term exemption
    lease("Swing space — 6 mo sublet", "office", (2025, 7), 6, 18_000, 0.0,
          short=True)
    lease("Event equipment — 9 mo", "equipment", (2025, 2), 9, 4_200, 0.0,
          short=True)
    return reg


def classify(l):
    """ASC 842-10-25-2. Practice thresholds: 75% of life, 90% of FV."""
    if l["short"]:
        return "short-term"
    if l["embedded"]:
        return "finance"      # specialized asset, major part of economic life
    if l["cls"] == "vehicle":
        return "finance"      # ownership transfers at term end
    if l["fv"]:
        ratio = pv(l["payments"], l["rate"] / 12) / l["fv"]
        l["pv_fv"] = ratio
        if ratio >= 0.90:
            return "finance"
    return "operating"


def build_schedule(l):
    """Monthly liability + ROU schedule from commencement to term end."""
    rate_m = l["rate"] / 12
    liab = pv(l["payments"], rate_m)
    l["liab0"] = liab
    rou = liab                      # no initial directs / incentives modeled
    sl_cost = sum(l["payments"]) / l["term"]
    rows = []
    for k, pay in enumerate(l["payments"]):
        interest = liab * rate_m
        liab_end = liab + interest - pay
        if l["kind"] == "finance":
            amort = l["liab0"] / l["term"]
        else:
            amort = sl_cost - interest      # plug: level single lease cost
        rou_end = rou - amort
        rows.append(dict(m=add_months(l["start"], k), pay=pay,
                         interest=interest, liab_beg=liab, liab_end=liab_end,
                         amort=amort, rou_end=rou_end,
                         cost=(amort + interest)))
        liab, rou = liab_end, rou_end
    # force the terminal residue of float arithmetic onto the last row's
    # display only if it is genuinely zero-sized; identities check raw floats
    l["schedule"] = rows
    return rows


def state_at(l, ym):
    """(liability, rou) carrying amounts at end of month ym, or None."""
    if l["kind"] == "short-term":
        return None
    end = add_months(l["start"], l["term"] - 1)
    if months_between(l["start"], ym) < 0 or months_between(ym, end) < 0:
        return None
    k = months_between(l["start"], ym)
    r = l["schedule"][k]
    return dict(liab=r["liab_end"], rou=r["rou_end"], row=k)


def run_checks(reg):
    checks = []

    def add(name, ok, detail):
        checks.append((name, ok, detail))

    live = [l for l in reg if l["kind"] != "short-term"]

    worst = max(abs(l["liab0"] - pv(l["payments"], l["rate"] / 12)) for l in live)
    add("opening liability = PV of payments at IBR", worst < TOL,
        f"max gap ${worst:.6f} across {len(live)} leases")

    worst = max(abs(l["schedule"][-1]["liab_end"]) for l in live)
    add("liability roll-forward ends at exactly zero", worst < TOL,
        f"max terminal residue ${worst:.6f}")

    worst = max(abs(l["schedule"][-1]["rou_end"]) for l in live)
    add("ROU amortizes to exactly zero", worst < TOL,
        f"max terminal residue ${worst:.6f}")

    worst = 0.0
    for l in live:
        if l["kind"] != "operating":
            continue
        total_cost = sum(r["cost"] for r in l["schedule"])
        worst = max(worst, abs(total_cost - sum(l["payments"])))
        costs = [r["cost"] for r in l["schedule"]]
        worst = max(worst, max(costs) - min(costs))
    add("operating: lifetime cost = lifetime payments, and level", worst < TOL,
        f"max deviation ${worst:.6f}")

    # disclosure tie at the balance-sheet date
    tot_liab, tot_undisc, tot_interest = 0.0, 0.0, 0.0
    for l in live:
        st = state_at(l, AS_OF)
        if not st:
            continue
        rem = l["schedule"][st["row"] + 1:]
        undisc = sum(r["pay"] for r in rem)
        imputed = sum(r["interest"] for r in rem)
        tot_liab += st["liab"]
        tot_undisc += undisc
        tot_interest += imputed
    gap = abs(tot_undisc - tot_interest - tot_liab)
    add("maturity disclosure ties: undiscounted - imputed = carrying",
        gap < TOL, f"${tot_undisc:,.0f} - ${tot_interest:,.0f} vs "
        f"${tot_liab:,.0f}, gap ${gap:.6f}")

    emb = [l for l in reg if l["embedded"]]
    ok = len(emb) == 1 and emb[0]["kind"] == "finance" \
        and state_at(emb[0], AS_OF) is not None
    add("embedded lease capitalized as finance lease", ok,
        emb[0]["name"] if emb else "MISSING")

    j = [l for l in reg if 0.85 < l.get("pv_fv", 0) < 0.90]
    ok = len(j) == 1 and j[0]["kind"] == "operating"
    add("the 89% judgment case exists and is operating", ok,
        f"{j[0]['name']} at {j[0]['pv_fv']:.1%}" if j else "MISSING")

    st = [l for l in reg if l["kind"] == "short-term"]
    add("short-term exemption: expensed, no ROU/liability",
        len(st) == 2 and all("schedule" not in l for l in st),
        f"{len(st)} leases, {sum(sum(l['payments']) for l in st)/1e3:,.0f}K expensed")

    active = [l for l in live if state_at(l, AS_OF)]
    wavg_rate = sum(state_at(l, AS_OF)["liab"] * l["rate"] for l in active) \
        / sum(state_at(l, AS_OF)["liab"] for l in active)
    add("weighted-average discount rate within sanity band",
        0.04 < wavg_rate < 0.08, f"{wavg_rate:.2%}")
    return checks, wavg_rate


def fmt_ym(ym):
    return f"{ym[0]}-{ym[1]:02d}"


def write_data(reg):
    d = Path(__file__).parent / "data"
    d.mkdir(exist_ok=True)
    with open(d / "lease_register.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["lease", "class", "classification", "start", "term_mo",
                    "monthly_pay_initial", "ibr", "pv_fv", "embedded", "short_term"])
        for l in reg:
            w.writerow([l["name"], l["cls"], l["kind"], fmt_ym(l["start"]),
                        l["term"], f"{l['payments'][0]:.2f}", f"{l['rate']:.4f}",
                        f"{l.get('pv_fv', ''):.4f}" if l.get("pv_fv") else "",
                        l["embedded"], l["short"]])
    with open(d / "schedules.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["lease", "month", "payment", "interest", "liab_end",
                    "rou_amort", "rou_end", "single_cost"])
        for l in reg:
            for r in l.get("schedule", []):
                w.writerow([l["name"], fmt_ym(r["m"]), f"{r['pay']:.2f}",
                            f"{r['interest']:.2f}", f"{r['liab_end']:.2f}",
                            f"{r['amort']:.2f}", f"{r['rou_end']:.2f}",
                            f"{r['cost']:.2f}"])


def totals_at(reg, ym):
    t = dict(liab=0.0, rou=0.0, op_liab=0.0, fin_liab=0.0)
    for l in reg:
        st = state_at(l, ym) if l["kind"] != "short-term" else None
        if not st:
            continue
        t["liab"] += st["liab"]
        t["rou"] += st["rou"]
        t["op_liab" if l["kind"] == "operating" else "fin_liab"] += st["liab"]
    return t


def maturity_table(reg):
    """Undiscounted payments by calendar year after the balance-sheet date."""
    buckets = {}
    for l in reg:
        if l["kind"] == "short-term" or not state_at(l, AS_OF):
            continue
        k = state_at(l, AS_OF)["row"]
        for r in l["schedule"][k + 1:]:
            y = r["m"][0]
            key = str(y) if y <= 2030 else "thereafter"
            buckets[key] = buckets.get(key, 0.0) + r["pay"]
    return buckets


def print_report(reg, checks, wavg_rate, out=print):
    t = totals_at(reg, AS_OF)
    emb = next(l for l in reg if l["embedded"])
    j = next(l for l in reg if 0.85 < l.get("pv_fv", 0) < 0.90)
    out("LEASE ACCOUNTING — ASC 842, as of 2025-12-31")
    out(f"  ROU assets                  ${t['rou']/1e6:,.2f}M")
    out(f"  Lease liabilities           ${t['liab']/1e6:,.2f}M"
        f"  (operating ${t['op_liab']/1e6:,.2f}M / finance ${t['fin_liab']/1e6:,.2f}M)")
    out(f"  Weighted-average IBR        {wavg_rate:.2%}")
    out(f"  EMBEDDED LEASE  {emb['name']} — ${emb['liab0']/1e6:,.1f}M capitalized;"
        " the contract never says 'lease'")
    out(f"  JUDGMENT CALL   {j['name']} — PV/FV {j['pv_fv']:.1%}, operating;"
        " decided at the line, documented at the line")
    out("")
    for name, ok, detail in checks:
        out(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    out("")
    out("  " + ("ALL CHECKS PASS" if all(c[1] for c in checks) else "FAILURES PRESENT"))


def svg_liab_curve(reg, w=940, h=210, pad=36):
    """Total liability carrying amount by month, 2026-2032."""
    months = []
    ym = AS_OF
    for _ in range(80):
        ym = add_months(ym, 1)
        months.append(ym)
    vals = []
    for ym in months:
        vals.append(sum(state_at(l, ym)["liab"] for l in reg
                        if l["kind"] != "short-term" and state_at(l, ym)))
    hi = max(vals) or 1
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = pad + i * (w - 2 * pad) / (n - 1)
        y = h - pad - v / hi * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    out = [f'<svg viewBox="0 0 {w} {h}" role="img">']
    for gy in range(4):
        yv = hi * (1 - gy / 3)
        y = pad + gy * (h - 2 * pad) / 3
        out.append(f'<line x1="{pad}" y1="{y:.0f}" x2="{w-pad}" y2="{y:.0f}" '
                   'stroke="var(--grid)"/>')
        out.append(f'<text x="{pad-6}" y="{y+4:.0f}" text-anchor="end" '
                   f'font-size="10" fill="var(--mut)">${yv/1e6:.0f}M</text>')
    out.append(f'<polyline points="{" ".join(pts)}" fill="none" '
               'stroke="var(--line)" stroke-width="2.2"/>')
    for yr in (2026, 2028, 2030, 2032):
        i = next((i for i, m in enumerate(months) if m == (yr, 1)), None)
        if i is not None:
            x = pad + i * (w - 2 * pad) / (n - 1)
            out.append(f'<text x="{x:.0f}" y="{h-8}" text-anchor="middle" '
                       f'font-size="10" fill="var(--mut)">{yr}</text>')
    out.append("</svg>")
    return "".join(out)


def write_html(path, reg, checks, wavg_rate):
    t = totals_at(reg, AS_OF)
    emb = next(l for l in reg if l["embedded"])
    j = next(l for l in reg if 0.85 < l.get("pv_fv", 0) < 0.90)
    mat = maturity_table(reg)
    mat_keys = ["2026", "2027", "2028", "2029", "2030", "thereafter"]
    undisc = sum(mat.values())
    imputed = undisc - t["liab"]
    active = sorted((l for l in reg if l["kind"] != "short-term"
                     and state_at(l, AS_OF)),
                    key=lambda l: -state_at(l, AS_OF)["liab"])

    reg_rows = ""
    for l in active[:10]:
        st = state_at(l, AS_OF)
        flag = ' class="flag"' if l["embedded"] or l is j else ""
        pvfv = f"{l['pv_fv']:.0%}" if l.get("pv_fv") else "—"
        reg_rows += (f"<tr{flag}><td>{l['name']}</td><td>{l['kind']}</td>"
                     f"<td>{fmt_ym(l['start'])}</td><td>{l['term']} mo</td>"
                     f"<td>{l['rate']:.2%}</td><td>{pvfv}</td>"
                     f"<td>${st['liab']/1e3:,.0f}K</td>"
                     f"<td>${st['rou']/1e3:,.0f}K</td></tr>")

    mat_rows = "".join(
        f"<tr><td>{k}</td><td>${mat.get(k, 0)/1e6:,.2f}M</td></tr>"
        for k in mat_keys)
    checks_html = "".join(
        f"<li><b class='{'ok' if ok else 'bad'}'>{'PASS' if ok else 'FAIL'}</b> "
        f"{name} <span class='mut'>— {detail}</span></li>"
        for name, ok, detail in checks)

    html = f"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ASC 842 leases — Dec 2025</title>
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
  <h1>Lease Accounting — ASC 842</h1>
  <p class="sub">A {len([l for l in reg if not l['short']])}-lease register as
    of Dec 31, 2025 — offices, vehicles, lab equipment, and one GPU capacity
    agreement that never uses the word "lease." Every schedule must amortize
    to exactly zero and the disclosure table must tie to the liability, or
    this page does not publish. Synthetic, seeded data.</p>

  <div class="kpis">
    <div class="kpi"><div class="v">${t['rou']/1e6:,.1f}M</div>
      <div class="l">Right-of-use assets</div></div>
    <div class="kpi"><div class="v">${t['liab']/1e6:,.1f}M</div>
      <div class="l">Lease liabilities — operating ${t['op_liab']/1e6:,.1f}M ·
        finance ${t['fin_liab']/1e6:,.1f}M</div></div>
    <div class="kpi"><div class="v">{wavg_rate:.2%}</div>
      <div class="l">Weighted-average discount rate (IBR)</div></div>
    <div class="kpi"><div class="v">${emb['liab0']/1e6:,.1f}M</div>
      <div class="l">Embedded lease capitalized — found in a "services" contract</div></div>
    <div class="kpi"><div class="v">{j['pv_fv']:.0%}</div>
      <div class="l">The judgment case — PV/FV vs the 90% line, documented</div></div>
    <div class="kpi"><div class="v">0.00</div>
      <div class="l">Terminal residue on every schedule — liability and ROU</div></div>
  </div>

  <h2>The embedded lease — the one that matters</h2>
  <div class="card">
    <p style="font-size:13.5px;margin:0">"{emb['name']}" — 48 months,
      $240K/month, dedicated racks. The contract calls itself a services
      agreement. ASC 842's tests disagree: there is an <b>identified asset</b>
      (specific, physically distinct hardware, no substitution right that
      benefits the supplier) and the customer <b>controls its use</b> (decides
      what runs on it, when, and gets substantially all its output). Dedicated
      capacity in a compute contract is a lease whatever the title page says
      — and at ${emb['liab0']/1e6:,.1f}M it moves the balance sheet more than
      every office combined. Specialized-asset criterion → finance
      classification.</p>
    <p class="note">This is the live ASC 842 question for AI companies: GPU
      and data-center agreements signed as "services" that contain
      identified, dedicated hardware. The register exists to catch them at
      signing, not at audit.</p></div>

  <h2>Lease liability run-off — carrying amount by month</h2>
  <div class="card">{svg_liab_curve(reg)}
    <p class="note">Total liability from Jan 2026 forward as schedules
      amortize. Every lease's roll-forward (beginning + interest − payment)
      must land at exactly zero in its final month — the terminal-residue
      check treats a stray cent as a modeling error, because that is what a
      stray cent is.</p></div>

  <h2>Register — ten largest by liability</h2>
  <div class="card"><table>
    <tr><th>Lease</th><th>Class</th><th>Start</th><th>Term</th><th>IBR</th>
        <th>PV / FV</th><th>Liability</th><th>ROU</th></tr>
    {reg_rows}
  </table>
  <p class="note">Highlighted rows: the embedded lease, and
    "{j['name']}" at PV/FV = {j['pv_fv']:.1%} — just under the 90%
    "substantially all" threshold, so operating. ASC 842 removed the bright
    lines on purpose; the register keeps the judgment <em>visible</em> instead
    of burying it: decided at the line, documented at the line.</p></div>

  <h2>Maturity of lease liabilities (undiscounted)</h2>
  <div class="card"><table style="min-width:380px">
    <tr><th>Year</th><th>Payments</th></tr>
    {mat_rows}
    <tr><td><b>Total undiscounted</b></td><td><b>${undisc/1e6:,.2f}M</b></td></tr>
    <tr><td class="mut">Less imputed interest</td><td class="mut">(${imputed/1e6:,.2f}M)</td></tr>
    <tr><td><b>Carrying amount</b></td><td><b>${t['liab']/1e6:,.2f}M</b></td></tr>
  </table>
  <p class="note">The footnote table is not decoration — undiscounted
    payments less imputed interest must equal the balance-sheet liability to
    the cent, and validation recomputes it from the raw schedules every
    run.</p></div>

  <h2>Short-term exemption</h2>
  <div class="card"><p style="font-size:13.5px;margin:0">Two leases under 12
    months (swing space, event equipment) take the ASC 842-20-25-2 exemption:
    straight-line expense, no ROU, no liability. Validation asserts they stay
    off the balance sheet — an exemption applied is also a control to test.</p></div>

  <h2>Validation — re-run before every publish</h2>
  <div class="card"><ul class="checks">{checks_html}</ul></div>

  <p class="note" style="margin-top:26px">Synthetic, seeded data
    (<code>random.seed(842)</code>). Generator, schedules, and checks:
    <a href="https://github.com/Lumimama/finance/tree/main/lease-accounting"
       style="color:var(--line)">github.com/Lumimama/finance/lease-accounting</a>.</p>
</div>
"""
    Path(path).write_text(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--html")
    ap.add_argument("--report")
    args = ap.parse_args()

    reg = make_register()
    for l in reg:
        l["kind"] = classify(l)
        if l["kind"] != "short-term":
            build_schedule(l)
    checks, wavg = run_checks(reg)
    write_data(reg)

    if args.report:
        lines = []
        print_report(reg, checks, wavg, out=lines.append)
        Path(args.report).write_text("\n".join(lines) + "\n")
    print_report(reg, checks, wavg)
    if args.html:
        write_html(args.html, reg, checks, wavg)
        print(f"  wrote {args.html}")
    if args.validate and not all(c[1] for c in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
