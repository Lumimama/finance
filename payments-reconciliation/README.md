# Payments Reconciliation Engine

Match a 50,000-transaction processor ledger against a bank settlement file, classify every break, age the open items by dollar exposure, and produce the exception report a settlement-operations team would actually work from.

**No dependencies.** Python 3.10+, runs in under half a second.

```bash
python make_sample_data.py       # regenerate the two-sided dataset (seeded)
python reconcile.py              # console report
python reconcile.py --validate   # score the engine against seeded ground truth
python reconcile.py --html examples/recon_dashboard.html
```

## The point

At transaction scale, reconciliation is not a matching problem — a VLOOKUP finds the unmatched rows. It's a **classification** problem, because the classification decides who works the item:

| break type | severity | routed to |
|---|---|---|
| missing in ledger | critical | finance + engineering — we're being paid for unknowns |
| missing at bank | high | settlement ops — our money in limbo |
| duplicate settlement | high | bank relations — recovery of double-settled funds |
| fee discrepancy | high | network relations — interchange charged off schedule |
| fx variance | medium | treasury — rate-source disagreement |
| amount mismatch | medium | merchant ops — tips, partial captures |
| timing lag | low | nobody — self-heals, but aged and watched |

A reconciliation that says *"1,148 unmatched"* is noise. One that says *"$24.7K stuck in unsettled transactions, $8.8K of duplicate settlements to recover, and fee overcharges concentrated in card-present credit"* is a work queue.

## Output

```
SETTLEMENT RECONCILIATION  |  as of 2026-06-16  |  T+1 contractual
  ledger transactions            50,000
  settlement rows                49,982
  matched clean                  48,951   (97.90%)
  exceptions                      1,148
  gross exposure              $159,298.88
  net position                 -$5,268.35   (bank owes us)

BREAKS BY TYPE
  type                    sev         count       exposure   owner
  timing_lag              low           492    $105,656.31   monitor only
  missing_at_bank         high          117     $24,714.16   settlement ops
  missing_in_ledger       critical       58     $13,547.35   finance + engineering
  duplicate_settlement    high           41      $8,844.02   bank relations
  amount_mismatch         medium        163      $3,189.44   merchant ops
  fx_variance             medium         74      $3,182.15   treasury
  fee_discrepancy         high          203        $165.45   network relations
```

Plus an aging table (0-1d / 2-3d / 4-7d / 8d+ bands, timing watchlist excluded), exposure by rail, and a top-open-items queue. `--html` renders all of it as a self-contained dashboard — no CDN, theme-aware, opens from disk.

## Design decisions worth reading

**Classification is ordered, and the order is the logic.** Within matched keys the engine checks fees first (net differs, gross agrees), then FX (cross-border gross drift with the implied rate computed), then generic amount, then timing. Get the order wrong and a cross-border amount difference reads as a generic mismatch, which routes it to the wrong team.

**Sign convention is stated and enforced.** Positive exposure = funds we hold that we may not be entitled to; negative = the bank owes us. A missing settlement is *negative*. The first version of this engine got that wrong — it summed "money the bank owes us" and "money we double-received" as if they pointed the same way, and the net position was meaningless. The convention is now documented at the point of use.

**The engine is validated against ground truth, and the validation caught real bugs.** The generator seeds exactly 1,148 breaks of known types; `--validate` scores the classifier against them. First run failed: the generator had double-seeded 203 transactions (a cursor bug), and 12 amount-mismatches had landed on cross-border rails where a gross variance *is* an FX variance. Both were generator bugs the validation surfaced. Current state:

```
  [ok ] B1_timing                seeded   492   classified   492
  [ok ] B2_amount                seeded   163   classified   163
  [ok ] B3_missing_at_bank       seeded   117   classified   117
  [ok ] B4_missing_in_ledger     seeded    58   classified    58
  [ok ] B5_duplicate             seeded    41   classified    41
  [ok ] B6_fx_variance           seeded    74   classified    74
  [ok ] B7_fee                   seeded   203   classified   203

  PASS -- every seeded break found and correctly classified
```

**Timing lags are excluded from aging.** They self-heal; aging them alongside genuine open items would drown the queue in noise. They're counted, exposed, and watched separately.

## Data

Fully synthetic, seeded, reproducible: 50,000 transactions across 14 settlement days and five rails (card-present debit/credit, e-com debit/credit, cross-border in five currencies), with realistic interchange and scheme-fee schedules per rail and a 2.3% seeded break rate. `seeded_breaks.json` is committed deliberately — it's the ground truth that makes the engine's accuracy checkable rather than asserted.

## Notes

Built with Claude as a pair.
