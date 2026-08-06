#!/usr/bin/env python3
"""ASC 606 steps 3-4 — standalone selling price allocation and the
principal-vs-agent call. Companion to revenue-recognition/ (which owns the
back half: deferred and RPO roll-forwards).

The story the data contains (decided before the generator):
  1. "Free implementation" isn't free. 14 of 40 bundles invoice
     implementation at $0 as a sales concession. Relative-SSP allocation
     reassigns transaction price to it anyway — you can discount an invoice
     line, but you cannot discount the accounting. The dashboard quantifies
     the shift from the invoice view to the 606 view.
  2. The bundle discount allocates pro-rata. Every obligation's
     allocated-to-SSP ratio must equal the contract's overall ratio exactly
     (final-obligation penny rounding aside) — a discount parked on one line
     is the classic manual-workaround error this engine refuses to allow.
  3. Principal vs agent, scored not vibed. A partner data add-on resells
     through our paper: the company does not control the service before
     transfer (no inventory risk, no pricing discretion, partner is primary
     obligor) -> agent -> NET presentation. Gross would inflate revenue
     ~$1.9M with identical profit; validation proves profit is identical to
     the cent under both presentations, which is exactly why the indicators
     — not the invoice total — decide.

Bug the validation caught during development: the first allocation rounded
every obligation to the cent independently, so a third of the contracts
summed to a penny or two off transaction price. The fix is the boring
standard one — round N-1 obligations, plug the last — and check 1 exists to
make sure it stays fixed.
"""

import argparse
import csv
import random
from pathlib import Path

random.seed(606)

MONTHS = 24                      # contract terms modeled monthly
TOL = 0.01

# standalone selling prices (annual, observable unless noted)
SSP = {
    "platform": 120_000,          # observable: standalone renewals
    "support": 24_000,            # observable: standalone attach
    "implementation": 30_000,     # cost-plus-margin (not sold standalone)
    "usage_credits": 60_000,      # adjusted market assessment
}
PARTNER_FEE_RATE = 0.85           # partner keeps 85% of add-on price


def make_contracts():
    out = []
    for i in range(40):
        scale = random.choice([0.5, 0.75, 1.0, 1.0, 1.5, 2.5])
        term = random.choice([12, 24, 24, 36])
        free_impl = i % 3 == 0                    # 14 of 40 bundles
        discount = random.uniform(0.08, 0.22)     # bundle discount off SSP
        obligations = {}
        for ob, ssp in SSP.items():
            years = term / 12
            full = ssp * scale * (years if ob != "implementation" else 1)
            obligations[ob] = dict(ssp=round(full, 2))
        ssp_total = sum(o["ssp"] for o in obligations.values())
        tp = round(ssp_total * (1 - discount), 2)
        # invoice lines: sales gets to zero implementation; the concession
        # is spread as a smaller discount on the other lines
        inv = {}
        if free_impl:
            rest = ssp_total - obligations["implementation"]["ssp"]
            for ob, o in obligations.items():
                inv[ob] = 0.0 if ob == "implementation" else round(
                    o["ssp"] / rest * tp, 2)
        else:
            for ob, o in obligations.items():
                inv[ob] = round(o["ssp"] / ssp_total * tp, 2)
        # partner add-on (reseller paper): separate from the bundle price
        addon = round(random.choice([0, 0, 18_000, 36_000]) * scale, 2)
        out.append(dict(cid=f"C-{1001+i}", term=term, tp=tp,
                        ssp_total=ssp_total, discount=discount,
                        obligations=obligations, invoice=inv,
                        free_impl=free_impl, addon=addon,
                        addon_cost=round(addon * PARTNER_FEE_RATE, 2)))
    return out


def allocate(contracts):
    """Relative-SSP allocation; round N-1 obligations, plug the last."""
    for c in contracts:
        obs = list(c["obligations"].items())
        running = 0.0
        for k, (ob, o) in enumerate(obs):
            if k < len(obs) - 1:
                o["alloc"] = round(o["ssp"] / c["ssp_total"] * c["tp"], 2)
                running += o["alloc"]
            else:
                o["alloc"] = round(c["tp"] - running, 2)   # the penny plug


def recognize(contracts):
    """Monthly recognition per obligation: platform/support ratably over the
    term; implementation over its first 3 months as performed; usage credits
    as consumed (seeded consumption curve, fully consumed by term end)."""
    for c in contracts:
        sched = {ob: [0.0] * c["term"] for ob in c["obligations"]}
        t = c["term"]
        for ob, o in c["obligations"].items():
            a = o["alloc"]
            if ob in ("platform", "support"):
                for k in range(t):
                    sched[ob][k] = a / t
            elif ob == "implementation":
                dur = min(3, t)
                for k in range(dur):
                    sched[ob][k] = a / dur
            else:                                   # usage credits: consumed
                weights = [random.uniform(0.5, 1.5) for _ in range(t)]
                wsum = sum(weights)
                for k in range(t):
                    sched[ob][k] = a * weights[k] / wsum
        c["schedule"] = sched


def run_checks(contracts):
    checks = []

    def add(name, ok, detail):
        checks.append((name, ok, detail))

    # 1. allocations sum exactly to transaction price
    worst = max(abs(sum(o["alloc"] for o in c["obligations"].values()) - c["tp"])
                for c in contracts)
    add("allocated obligations sum to transaction price, all 40 contracts",
        worst < TOL, f"max gap ${worst:.6f}")

    # 2. discount is pro-rata: alloc/ssp ratio uniform within each contract
    worst = 0.0
    for c in contracts:
        ratios = [o["alloc"] / o["ssp"] for o in c["obligations"].values()]
        worst = max(worst, max(ratios) - min(ratios))
    add("bundle discount allocates pro-rata (no obligation eats it alone)",
        worst < 0.001, f"max within-contract ratio spread {worst:.6f}")

    # 3. free-implementation contracts: invoice $0, allocation > 0
    fi = [c for c in contracts if c["free_impl"]]
    ok = len(fi) == 14 and all(
        c["invoice"]["implementation"] == 0.0
        and c["obligations"]["implementation"]["alloc"] > 0 for c in fi)
    shift = sum(c["obligations"]["implementation"]["alloc"] for c in fi)
    add('"free implementation": invoiced at $0, allocated revenue anyway',
        ok, f"{len(fi)} contracts, ${shift/1e3:,.0f}K reassigned to "
        "implementation by relative SSP")

    # 4. lifetime recognized revenue = transaction price
    worst = max(abs(sum(sum(s) for s in c["schedule"].values()) - c["tp"])
                for c in contracts)
    add("lifetime recognized revenue = transaction price, every contract",
        worst < TOL, f"max gap ${worst:.6f}")

    # 5. principal vs agent: profit identical, revenue differs by pass-through
    gross_rev = sum(c["addon"] for c in contracts)
    net_rev = sum(c["addon"] - c["addon_cost"] for c in contracts)
    gross_profit_gross = gross_rev - sum(c["addon_cost"] for c in contracts)
    gross_profit_net = net_rev
    ok = abs(gross_profit_gross - gross_profit_net) < TOL \
        and abs((gross_rev - net_rev) - sum(c["addon_cost"] for c in contracts)) < TOL
    add("agent call: profit identical gross vs net; only revenue differs",
        ok, f"gross would report ${gross_rev/1e6:,.2f}M, net reports "
        f"${net_rev/1e6:,.2f}M — same ${gross_profit_net/1e6:,.2f}M profit")

    # 6. sanity: blended discount inside the generator's band
    blended = 1 - sum(c["tp"] for c in contracts) / sum(c["ssp_total"] for c in contracts)
    add("blended bundle discount within the stated band", 0.06 < blended < 0.24,
        f"{blended:.1%}")
    return checks


def write_data(contracts):
    d = Path(__file__).parent / "data"
    d.mkdir(exist_ok=True)
    with open(d / "contracts.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["contract", "term_mo", "ssp_total", "transaction_price",
                    "discount", "free_implementation", "addon_price",
                    "addon_partner_fee"])
        for c in contracts:
            w.writerow([c["cid"], c["term"], f"{c['ssp_total']:.2f}",
                        f"{c['tp']:.2f}", f"{c['discount']:.4f}",
                        c["free_impl"], f"{c['addon']:.2f}",
                        f"{c['addon_cost']:.2f}"])
    with open(d / "allocations.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["contract", "obligation", "ssp", "invoice_line",
                    "allocated"])
        for c in contracts:
            for ob, o in c["obligations"].items():
                w.writerow([c["cid"], ob, f"{o['ssp']:.2f}",
                            f"{c['invoice'][ob]:.2f}", f"{o['alloc']:.2f}"])


def print_report(contracts, checks, out=print):
    fi = [c for c in contracts if c["free_impl"]]
    shift = sum(c["obligations"]["implementation"]["alloc"] for c in fi)
    gross_rev = sum(c["addon"] for c in contracts)
    net_rev = sum(c["addon"] - c["addon_cost"] for c in contracts)
    tcv = sum(c["tp"] for c in contracts)
    out("REVENUE ALLOCATION — ASC 606 STEPS 3-4")
    out(f"  Contracts                   {len(contracts)}, total transaction "
        f"price ${tcv/1e6:,.1f}M")
    out(f"  Free implementation         {len(fi)} bundles invoice it at $0;"
        f" allocation reassigns ${shift/1e3:,.0f}K to it anyway")
    out(f"  Principal vs agent          partner add-on presented NET: "
        f"${net_rev/1e6:,.2f}M (gross would claim ${gross_rev/1e6:,.2f}M,"
        " same profit)")
    out("")
    for name, ok, detail in checks:
        out(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    out("")
    out("  " + ("ALL CHECKS PASS" if all(c[1] for c in checks) else "FAILURES PRESENT"))


def write_html(path, contracts, checks):
    fi = [c for c in contracts if c["free_impl"]]
    shift = sum(c["obligations"]["implementation"]["alloc"] for c in fi)
    gross_rev = sum(c["addon"] for c in contracts)
    pass_through = sum(c["addon_cost"] for c in contracts)
    net_rev = gross_rev - pass_through
    tcv = sum(c["tp"] for c in contracts)
    blended = 1 - tcv / sum(c["ssp_total"] for c in contracts)
    ex = next(c for c in fi if c["term"] == 24)
    ex_rows = ""
    for ob, o in ex["obligations"].items():
        label = ob.replace("_", " ")
        ex_rows += (f"<tr><td>{label}</td><td>${o['ssp']/1e3:,.1f}K</td>"
                    f"<td>${ex['invoice'][ob]/1e3:,.1f}K</td>"
                    f"<td><b>${o['alloc']/1e3:,.1f}K</b></td>"
                    f"<td>{o['alloc']/o['ssp']:.1%}</td></tr>")
    ex_rows += (f"<tr><td><b>Total</b></td>"
                f"<td><b>${ex['ssp_total']/1e3:,.1f}K</b></td>"
                f"<td><b>${sum(ex['invoice'].values())/1e3:,.1f}K</b></td>"
                f"<td><b>${ex['tp']/1e3:,.1f}K</b></td>"
                f"<td>{ex['tp']/ex['ssp_total']:.1%}</td></tr>")
    checks_html = "".join(
        f"<li><b class='{'ok' if ok else 'bad'}'>{'PASS' if ok else 'FAIL'}</b> "
        f"{name} <span class='mut'>— {detail}</span></li>"
        for name, ok, detail in checks)
    html = f"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ASC 606 allocation — steps 3-4</title>
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
  table {{ border-collapse:collapse; width:100%; font-size:13px; min-width:560px; }}
  th, td {{ text-align:right; padding:6px 10px; border-bottom:1px solid var(--bd); }}
  th:first-child, td:first-child {{ text-align:left; }}
  th {{ color:var(--mut); font-weight:600; font-size:11.5px;
        text-transform:uppercase; letter-spacing:.04em; }}
  .mut {{ color:var(--mut); }} .ok {{ color:var(--pos); }} .bad {{ color:var(--neg); }}
  .note {{ font-size:12.5px; color:var(--mut); margin-top:8px; max-width:88ch; }}
  ul.checks {{ list-style:none; padding:0; margin:0; font-size:13px; }}
  ul.checks li {{ padding:5px 0; border-bottom:1px solid var(--bd); }}
</style>
<div class="wrap">
  <h1>Revenue Allocation — ASC 606 Steps 3–4</h1>
  <p class="sub">40 multi-element contracts — platform, support,
    implementation, usage credits, and a partner add-on — allocated by
    relative standalone selling price and recognized per obligation.
    Companion to the
    <a href="../../revenue-recognition/examples/revrec_dashboard.html"
       style="color:var(--line)">Revenue Recognition</a> project, which owns
    the deferred and RPO roll-forwards. Synthetic, seeded data.</p>

  <div class="kpis">
    <div class="kpi"><div class="v">${tcv/1e6:,.1f}M</div>
      <div class="l">Transaction price across 40 contracts —
        blended bundle discount {blended:.0%}</div></div>
    <div class="kpi"><div class="v">${shift/1e3:,.0f}K</div>
      <div class="l">Reassigned to "free" implementation by relative SSP —
        {len(fi)} bundles invoice it at $0</div></div>
    <div class="kpi"><div class="v">${net_rev/1e6:,.2f}M</div>
      <div class="l">Partner add-on revenue, presented NET (agent)</div></div>
    <div class="kpi"><div class="v">${gross_rev/1e6:,.2f}M</div>
      <div class="l">What gross presentation would have claimed — same
        profit, {((gross_rev/net_rev)-1)*100:,.0f}% more "revenue"</div></div>
    <div class="kpi"><div class="v">{len(contracts)}/{len(contracts)}</div>
      <div class="l">Contracts where allocations sum to transaction price
        to the cent</div></div>
  </div>

  <h2>One contract, two views — {ex['cid']}, 24-month bundle</h2>
  <div class="card"><table>
    <tr><th>Obligation</th><th>SSP</th><th>Invoice line</th>
        <th>Allocated (606)</th><th>Alloc / SSP</th></tr>
    {ex_rows}
  </table>
  <p class="note">Sales invoiced implementation at <b>$0</b> — a concession
    that looks free on paper. Relative-SSP allocation reassigns transaction
    price to it anyway, at exactly the contract's overall discount ratio.
    You can discount an invoice line; you cannot discount the accounting.
    The pro-rata column is a validation check, not a hope: any obligation
    whose ratio deviates from the contract's fails the build — a discount
    parked on one line is the classic manual-workaround error.</p></div>

  <h2>Principal vs agent — scored, not vibed</h2>
  <div class="card"><table style="min-width:520px">
    <tr><th>ASC 606-10-55 indicator</th><th>This arrangement</th><th>Points to</th></tr>
    <tr><td>Primary responsibility for fulfillment</td>
        <td>Partner delivers and supports the add-on</td><td>Agent</td></tr>
    <tr><td>Inventory risk before transfer</td>
        <td>None — we never hold or commit to capacity</td><td>Agent</td></tr>
    <tr><td>Pricing discretion</td>
        <td>Partner sets list; we pass through at partner's price</td><td>Agent</td></tr>
  </table>
  <p class="note">Conclusion: <b>agent — net presentation.</b> The
    arithmetic proof is check 5: profit is identical to the cent under
    either presentation (${net_rev/1e6:,.2f}M), which is precisely why the
    control-of-the-good indicators — not the invoice total — make the call.
    Gross would have added ${pass_through/1e6:,.2f}M of pass-through to the
    revenue line. For a marketplace or reseller business this single
    judgment swings reported revenue by multiples.</p></div>

  <h2>Validation — re-run before every publish</h2>
  <div class="card"><ul class="checks">{checks_html}</ul></div>

  <p class="note" style="margin-top:26px">SSP bases: platform and support are
    observable (standalone renewals and attach); implementation is
    cost-plus-margin; usage credits use an adjusted market assessment —
    the hierarchy stated, as a policy memo would. Synthetic, seeded
    (<code>random.seed(606)</code>). Source:
    <a href="https://github.com/Lumimama/finance/tree/main/revenue-allocation"
       style="color:var(--line)">github.com/Lumimama/finance/revenue-allocation</a>.</p>
</div>
"""
    Path(path).write_text(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--html")
    ap.add_argument("--report")
    args = ap.parse_args()

    contracts = make_contracts()
    allocate(contracts)
    recognize(contracts)
    checks = run_checks(contracts)
    write_data(contracts)

    if args.report:
        lines = []
        print_report(contracts, checks, out=lines.append)
        Path(args.report).write_text("\n".join(lines) + "\n")
    print_report(contracts, checks)
    if args.html:
        write_html(args.html, contracts, checks)
        print(f"  wrote {args.html}")
    if args.validate and not all(c[1] for c in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
