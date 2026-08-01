# Continuous Controls Monitor

Seven audit-style detectors over a fiscal year of AP invoices (~6,000, 270 vendors) and T&E expenses (~21,500, 380 employees): duplicate payments, split invoices, Benford's-law violations, round-dollar clustering, weekend entries, T&E policy violations, and expense-velocity anomalies. Risk-scored review queue, flagged spend by detector (spend flagged for review, never an estimated loss), self-contained dashboard.

**No dependencies.** Python 3.10+, runs in ~0.1 seconds.

```bash
python make_sample_data.py     # regenerate (seeded)
python monitor.py              # console report
python monitor.py --validate   # recall vs seeded ground truth
python monitor.py --html examples/controls_dashboard.html
```

## The contract: recall first, precision reported honestly

These are *flags for review, not verdicts*. A monitor tuned so that everything it flags is fraud has been tuned to miss things. So the contract here is explicit:

- **Recall must be 100%** against the seeded ground truth — `--validate` proves it.
- **Precision is reported, not hidden.** The queue carries ~143 findings against ~113 seeded; the extras (a real duplicate-amount coincidence, a legit vendor near the Benford line) are what a real monitor produces, and pretending otherwise would be tuning for the demo.

```
VALIDATION -- recall against seeded ground truth (must be 100%)
  [ok ] duplicates      14/14 seeded pairs flagged
  [ok ] round_dollar    Pinnacle Consulting flagged
  [ok ] split_invoices  6/6 seeded clusters flagged
  [ok ] benford         Northgate Logistics flagged
  [ok ] weekend_entry   31 flagged vs 31 seeded
  [ok ] policy          77 flagged vs 59 seeded (floor)
  [ok ] velocity        E077 flagged
  PASS -- 100% recall on seeded issues
```

## The Benford test took three tries, and the trail is the interesting part

**v1 — chi-squared.** Flagged three vendors where one was fabricated. Chi-squared power grows with n, so at a few hundred invoices it flags *legitimate* vendors for trivially small deviations.

**v2 — MAD with Nigrini's fixed 0.015 threshold.** Worse: nine flags. That threshold assumes thousands of records; at n≈100 the sampling-noise floor of a perfectly Benford-conforming vendor is already ~0.02, so small legitimate vendors get flagged for being small.

**v3 — MAD against its own noise floor.** Compare observed MAD to its expected value under Benford *for that vendor's n* — `E[MAD] ≈ √(2/π) · mean_d √(p_d(1−p_d)/n)` — and flag at 2.5× expected. Fabricated-uniform digits sit ~3× above the floor at any sample size; legitimate vendors sit near 1×. Two flags: the fabricated vendor at 2.9×, one borderline legit vendor — an honest false positive.

The general lesson is the one that matters for every anomaly detector in a finance stack: **a threshold that ignores sample size punishes small populations and excuses large ones.** It's also why the whole trail is documented in the detector's docstring rather than cleaned away.

## What the detectors encode

| detector | severity | the audit logic |
|---|---|---|
| duplicate_payment | critical | same vendor + amount, 1–14 days apart, different invoice IDs |
| split_invoices | critical | 2+ invoices, same vendor + approver, each 55–99% of the $10K approval threshold, within 10 days, jointly over it |
| benford_violation | high | leading-digit MAD vs n-adjusted noise floor |
| round_dollar | high | vendor with ≥50% of invoices at round-$500 multiples |
| expense_velocity | high | employee's monthly expense count ≥3× their own median |
| policy_violation | medium | meals over the $75 per-diem; business-class airfare without approval |
| weekend_entry | low | invoices entered on days AP doesn't work |

The split-invoice window (55–99% of threshold) is the load-bearing choice: without the lower bound, any two mid-sized invoices from a busy vendor trip the detector; with it, the flag means what an auditor means by "structuring."

## Data

Fully synthetic, seeded, reproducible. A 20-vendor head plus a 250-vendor long tail (which is where real AP volume lives), log-normal amounts, 380 employees at realistic expense rates. `seeded_findings.json` is committed as the ground truth that makes accuracy checkable rather than asserted.

## Notes

Built with Claude as a pair.
