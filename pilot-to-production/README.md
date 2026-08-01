# Pilot-to-Production Funnel

Robotics doesn't have a sales funnel; it has a **pilot** funnel — and that difference is why so many robotics companies with good technology have bad financials.

**No dependencies.** Python 3.10+, synthetic data.

```bash
python pilots.py            # console
python pilots.py --validate
python pilots.py --html examples/pilots_dashboard.html
```

A SaaS trial costs the vendor a seat. A robotics pilot costs hardware on loan, a solutions engineer on site, integration into someone else's safety and workflow systems, and months of calendar time — real money spent before any revenue, on an uncertain outcome.

## The three numbers

**True CAC.** Naive CAC counts only the pilots you won: **$109,630**. True CAC divides *all* pilot cost by the wins: **$580,489**, or 5.3×. The lost and stalled pilots aren't overhead — they're the cost of acquiring the customers you did win.

**Pilot purgatory is datable.** Conversion collapses past 9 months (52% at 4–6 months → 0% at 10–12). That turns "we should probably close some of these" into a defensible kill rule with a number attached.

**As run, this motion does not pay back — on any realistic term.** At $191K average ACV and 68% gross margin, a customer produces ~$130K of gross profit a year; three years recovers ~$391K against $580K of CAC, leaving ~$190K unrecovered. The minimum term that clears the hurdle is ~4.5 years, which customers won't sign. (An earlier version called the three-year term "workable" off a revenue-basis ratio — an external review correctly caught the contradiction: gross profit, not revenue, repays CAC.)

## The counterfactual that makes it actionable

| | actual | qualified pilots only |
|---|---|---|
| Pilots run | 103 | 28 |
| True CAC | $580,489 | **$170,357** |
| CAC as % of 3-year TCV | 101% | **31%** |

Qualified = named executive sponsor **and** written success criteria. Those pilots convert at 54% vs 9% for unqualified ones.

The qualified motion pays back in ~16 months of gross profit — comfortably inside a three-year term. So the conclusion isn't "pilots don't work"; it's that **the unqualified pilots are the entire reason the blended motion doesn't pay for itself**, and a qualification gate before a robot ever ships is the difference between a broken funnel and a working one.

Built with Claude as a pair.
