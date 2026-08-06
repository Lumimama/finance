# Revenue Allocation — ASC 606 Steps 3–4

**Live dashboard:** [allocation_dashboard.html](https://lumimama.github.io/finance/revenue-allocation/examples/allocation_dashboard.html)

Standalone-selling-price allocation and the principal-vs-agent call, on 40
multi-element contracts (platform + support + implementation + usage
credits, plus a partner add-on). Companion to
[revenue-recognition](../revenue-recognition), which owns the back half of
the standard — deferred and RPO roll-forwards.

## The three findings the data was designed to contain

**1. "Free implementation" isn't free.** 14 of 40 bundles invoice
implementation at $0 as a sales concession. Relative-SSP allocation
reassigns $493K of transaction price to it anyway, at exactly each
contract's overall discount ratio. You can discount an invoice line; you
cannot discount the accounting. The dashboard shows one contract in both
views — invoice lines vs 606 allocation — side by side.

**2. The discount allocates pro-rata, enforced.** Every obligation's
allocated-to-SSP ratio must equal the contract's overall ratio (check 2) —
parking the whole discount on one line is the classic manual-workaround
error, and here it fails the build.

**3. Principal vs agent, scored not vibed.** The partner add-on scores
agent on all three ASC 606-10-55 indicators (fulfillment responsibility,
inventory risk, pricing discretion) → net presentation. The arithmetic
proof is the point: profit is identical to the cent under either
presentation, which is exactly why the control indicators — not the
invoice total — make the call. Gross would have multiplied the add-on
revenue line ~6× with zero profit difference. For a marketplace or
revenue-share business (parking operators, resellers, app stores), this
single judgment swings reported revenue by multiples.

## Validation (`--validate`)

1. Allocations sum to transaction price, all 40 contracts, to the cent
   (round N−1 obligations, plug the last — the boring standard fix).
2. Bundle discount allocates pro-rata within every contract.
3. The 14 free-implementation contracts invoice $0 and allocate > $0.
4. Lifetime recognized revenue = transaction price, every contract.
5. Gross vs net: profit identical to the cent; revenue differs by exactly
   the partner pass-through.
6. Blended discount stays inside the generator's stated band.

## Bug the validation caught

The first allocation rounded every obligation to the cent independently, so
a third of the contracts summed a penny or two off transaction price.
Check 1 exists to keep the fix (last-obligation plug) honest.

## SSP hierarchy (stated, as a policy memo would)

Platform and support: observable, from standalone renewals and attach.
Implementation: expected-cost-plus-margin (never sold standalone).
Usage credits: adjusted market assessment.

## Run it

```
python3 allocation.py --validate
python3 allocation.py --html examples/allocation_dashboard.html --report examples/report.txt
```

Python 3.10+, standard library only. Seeded (`random.seed(606)`).
