# Usage-Based Revenue Engine

The finance layer of AI pricing: a contract register expanded into monthly revenue across three streams — **platform license** (ratable), **metered usage against committed minimums** (bill `max(actual, commit)`, overage at a 20% premium, volume-tiered unit rates), and **implementation** (recognized over launch).

**No dependencies.** Python 3.10+. All data synthetic.

```bash
python engine.py                # console report (also writes data/)
python engine.py --validate
python engine.py --html examples/usage_dashboard.html
```

## Why usage revenue needs its own engine

Subscription ARR is stepwise — it changes when contracts change. Usage revenue **moves every month without a signature**. That breaks three things a subscription model takes for granted:

1. **The walk needs lines a subscription walk doesn't have.** Usage expansion and usage contraction are frequently the largest movements on the page, and neither has a contract event to anchor it.
2. **Retention splits into contracted vs consumed.** A customer can be fully retained on paper and quietly halving their consumption.
3. **The commercial questions invert.** A customer at 60% of commit is not "safe revenue" — they're paying for capacity they don't use, and they are a **downgrade at renewal**. A customer at 140% is not "over-serviced" — they are the **upsell list**, and every month on overage rates past a commit step-up conversation is money left on the table.

## The commit-utilization panel is the deliverable

Everything else describes revenue; utilization tells you which contracts to act on:

```
under-committed (<65% for 3 months) -- downgrade risk at renewal:
  K031  enterprise   44% utilized   $XXX,XXX/yr of commit unused
over-committed (>130% for 3 months) -- the upsell list:
  K012  enterprise  173% utilized   $139,654/yr overage run-rate
```

Both lists are seeded into the data, and `--validate` proves the analysis surfaces them.

## The rate-compression story

```
blended rate 0.1461 -> 0.1272 $/task (-13%): growth with rate compression
usage GM 70% -> 76%: inference cost declines faster than realized rate
```

Blended realized rate per task **compresses** as mix shifts to larger tiers with lower unit pricing — invisible in revenue totals, visible only in the rate curve. Margin expands anyway because inference cost per task falls faster. Whether that second line keeps outrunning the first is the single most important assumption in any AI-native P&L, and this engine is built to watch it monthly.

## Invariants

```
[ok ] ARR walk (incl. usage expansion) reconciles and chains
[ok ] usage billing = max(actual, commit) + 20% overage premium, every contract-month
[ok ] utilization panel surfaces the seeded under/over-committed contracts
[ok ] blended realized rate compresses
```

ARR here is run-rate (license + annualized usage billing); implementation is one-time and excluded by definition. Stated because "what counts as ARR" is precisely the number that gets negotiated in a usage business.

## Notes

Synthetic, seeded, reproducible. Built with Claude as a pair.
