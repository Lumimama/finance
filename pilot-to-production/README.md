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

**Contract term is a financial lever.** At $191K average ACV, true CAC takes 36 months of first-year revenue to repay — 101% of three-year TCV. Pilot-heavy acquisition is only solvent on multi-year terms, and term is usually negotiated by people who've never seen this number.

## The counterfactual that makes it actionable

| | actual | qualified pilots only |
|---|---|---|
| Pilots run | 103 | 28 |
| True CAC | $580,489 | **$170,357** |
| CAC as % of 3-year TCV | 101% | **31%** |

Qualified = named executive sponsor **and** written success criteria. Those pilots convert at 54% vs 9% for unqualified ones.

The conclusion isn't "the pilot motion is broken." It's that the unqualified pilots aren't underperforming — **they are the entire reason the acquisition motion doesn't pay for itself**, and a qualification gate before a robot ever ships is the cheapest intervention available.

Built with Claude as a pair.
