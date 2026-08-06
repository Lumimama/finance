# Stock-Based Compensation — ASC 718

**Live dashboard:** [sbc_dashboard.html](https://lumimama.github.io/finance/stock-compensation/examples/sbc_dashboard.html)

A grant ledger (RSUs and options, 4-year vest with 1-year cliff, 2022–2025)
where the expense engine must reprove itself every month: an incremental
engine books accruals, cliff true-ups, and forfeiture reversals, and a
**separate closed-form recomputation** walks every tranche's state at each
month-end and states what cumulative expense *must* be. The two must agree
to the cent — 48 month-ends × two attribution methods — or the dashboard
does not publish.

## The three findings the data was designed to contain

**1. Straight-line vs graded, same ledger.** The company's policy is
straight-line (typical for service-only awards); FIN 28 graded attribution
runs beside it. Graded treats each vesting tranche as its own award and
front-loads. Both must land on grant-date fair value at full vesting for
every stayer award — check 2 proves it award by award. The delta between
methods is a real policy conversation, and here it's quantified instead of
asserted.

**2. Forfeitures at actuals — the RIF true-up.** Under the ASU 2016-09
election, forfeitures are recognized when they happen, not estimated.
An August 2025 reduction-in-force hits 7 employees who are still **inside
the cliff** — so their entire accrued expense reverses in one month ($73K),
and the expense line visibly dips. That's the design point: post-cliff
monthly vesting leaves almost no unvested overhang, so a RIF of tenured
staff barely moves SBC — but a RIF of recent hires claws a quarter's
expense back. The chart shows which kind this was.

**3. The repricing.** 60,000 options struck at $8.40 in March 2022 went
underwater in the June 2023 down round. Repriced March 2025 at $5.45.
ASC 718 is unforgiving in a specific way: the original grant-date fair
value is **never reversed** — an underwater option still cost what it cost
— and the modification adds only *incremental* fair value (new award minus
old award, both valued at the modification date): $41K, recognized over
the remaining vesting period. When the board asks "what did the repricing
cost," the answer is $41K, not the headline value of the new options.

## Validation (`--validate`)

1. Engine == closed-form recomputation at all 48 month-ends, both methods,
   to the cent.
2. At full vesting, straight-line and graded both land on grant-date FV
   (every stayer award, evaluated at its 48-month horizon).
3. Cumulative expense never exceeds grant-date FV + incremental FV.
4. Unrecognized + recognized = total FV for every active award.
5. The RIF reversal is recomputed independently and the expense line dips.
6. Repricing incremental FV > 0; the modified award's lifetime expense is
   ceilinged at original + incremental.
7. Every option's Black-Scholes fair value sits between intrinsic value
   and the share price — the smell test for mis-wired pricing inputs.
8. FY2025 expense positive under both methods.

## Bugs the validation caught

- **The graded engine double-accrued one increment per tranche** by also
  posting in the vest month itself; check 1 flagged a $96K cumulative gap
  and check 3 caught awards exceeding their own grant-date FV. Tranches now
  accrue over [grant, vest) only.
- **The first RIF cohort was drawn from all 2024 grants** — most were past
  the cliff, where monthly vesting leaves nothing to reverse, and the
  "reversal" computed to $0. The cohort is now drawn from in-cliff
  grantees, which is also the economically interesting case.
- **The first share-price path recovered too fast**, leaving the $8.40
  option barely underwater at the repricing date and the incremental FV at
  a meaningless $9K. The down round is now deeper and the recovery slower —
  and the story survives contact with its own arithmetic.

## Simplifications (stated, not hidden)

- Black-Scholes with a single expected term (6 years) and year-level vol/rf
  assumptions; no early-exercise model.
- One grant per employee; no performance or market conditions (those change
  attribution and would be the natural extension).
- No tax accounting (windfalls/shortfalls under ASU 2016-09 would be the
  other natural extension).

## Run it

```
python3 sbc.py --validate
python3 sbc.py --html examples/sbc_dashboard.html --report examples/report.txt
```

Python 3.10+, standard library only. Seeded (`random.seed(718)`) —
re-running reproduces every figure exactly.
