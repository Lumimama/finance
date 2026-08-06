# Multi-Entity Consolidation — ASC 830

**Live dashboard:** [consolidation_dashboard.html](https://lumimama.github.io/finance/consolidation-fx/examples/consolidation_dashboard.html)

A monthly consolidation of a US parent and three foreign subsidiaries,
built to demonstrate the two things ASC 830 actually tests: **the functional
currency judgment** (which decides whether rate changes land in OCI or in
P&L) and **the discipline that every number proves itself** (intercompany
pairs net to zero, the balance sheet ties, and CTA is computed two
independent ways).

## The group

| Entity | Books kept in | Functional currency | Method | FX lands in |
|---|---|---|---|---|
| US parent | USD | USD | — | — |
| UK Ltd | GBP | GBP | Translation (current-rate) | **OCI (CTA)** |
| Japan KK | JPY | JPY | Translation (current-rate) | **OCI (CTA)** |
| Singapore Pte | SGD | **USD** | Remeasurement | **P&L** |

The parent charges each sub a 3% management fee, invoiced in the sub's local
currency and settled two months in arrears — which makes the parent's
intercompany receivables foreign-currency monetary assets, remeasured
through parent P&L at every close (ASC 830-20). Those FX gains and losses do
*not* eliminate; they are real.

## Design decisions

**CTA is proven two ways, every month.** Once as the balance-sheet plug
(translated assets − translated liabilities − equity at historical −
translated retained earnings), and once as an analytical roll-forward
(opening net assets × spot movement + net income × (spot − average)).
Validation fails if they diverge by a cent. The reason is on the dashboard:
*a plug always balances* — it will silently absorb a translation coding
error. The roll-forward cannot.

**Singapore holds no nonmonetary assets — deliberately.** With an
all-monetary balance sheet, its remeasurement adjustment is arithmetically
identical to what CTA would have been. The only difference between
Singapore and the UK is *where the number lands*: P&L versus OCI. That
isolates the point ASC 830 turns on — functional currency, not geography,
decides the income-statement impact.

**One seeded intercompany break.** Japan accrues the November management fee
with two digits transposed — under by ¥27,000. A transposition difference is
always divisible by 9, and the intercompany matrix applies that test
automatically and labels the break "transposition suspect." The engine posts
a top-side correction in November and reverses it in December when Japan's
own catch-up entry lands. Validation requires the matrix to find **exactly**
this break and no other, and requires every pair to net to zero after the
top-side.

**The yen story.** JPY weakens ~9% across the year. Consolidated equity
falls through CTA with zero P&L impact — the dashboard states the answer to
the board question this generates: "why did equity fall when we made money?"
Translation, not performance.

## Validation (`--validate`)

1. Every local-currency trial balance balances (42 entity-months).
2. Consolidated A = L + E to the cent, all 12 months.
3. CTA plug == analytical roll-forward (UK and Japan, every month).
4. Remeasurement plug == analytical roll-forward (Singapore, every month).
5. The IC matrix finds the seeded ¥27,000 transposition — and only it.
6. Post-top-side, fee and balance eliminations net to zero (P&L at average,
   balances at spot).
7. Consolidated revenue is external revenue only.
8. FX paths stay within ±15% of opening (sanity bound on the seeded walk).

## Bugs the validation caught

- **First draft translated the subs' intercompany payables at the average
  rate** (copying the P&L treatment of the fee). The CTA plug still balanced
  — plugs always do — but the analytical roll disagreed by exactly
  (spot − avg) × the IC balance, and check 3 failed. This is the concrete
  case for computing CTA twice.
- **The top-side P&L correction was first derived from the balance gap
  rather than the month's fee difference.** December's balance gap is zero
  (Japan's catch-up fixes the payable), so the reversal never posted and fee
  eliminations left a $163 residual in December. Check 6 caught it; the P&L
  side now keys off booked-vs-true by month.
- **The parent's opening intercompany receivable started at zero** while the
  subs' opening payables carried two months of fees — a warm-up
  initialization mismatch of exactly one month's fees ($93.8K) that check 6
  refused to accept.

## Simplifications (stated, not hidden)

- Monthly average rate is the midpoint of the month's endpoint rates.
- Subsidiaries are wholly owned; no NCI, no goodwill (investment eliminates
  against capital at historical rates 1:1).
- No dividends or capital contributions during the year, which keeps the
  CTA roll-forward to its two-term form.
- IC balances are settlement-planned, so their FX stays in P&L rather than
  CTA (ASC 830-20-35; the long-term-investment-nature election is noted but
  not taken).

## Run it

```
python3 consolidation.py --validate
python3 consolidation.py --html examples/consolidation_dashboard.html --report examples/report.txt
```

Python 3.10+, standard library only. Seeded (`random.seed(830)`) —
re-running reproduces every figure exactly.
