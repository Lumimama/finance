# Revenue Cohort Analysis

The cohort heatmap, the layer cake, and empirical CAC-payback curves — the three artifacts a diligence team asks for on day one — computed from a 1,450-customer, 54-month ARR panel.

**No dependencies.** Python 3.10+.

```bash
python make_sample_data.py       # regenerate the panel (seeded)
python cohorts.py                # console report
python cohorts.py --validate     # decomposition ties + pathology is visible
python cohorts.py --html examples/cohorts_dashboard.html
```

## Why cohorts and not blended metrics

Blended NRR answers *"how did the installed base do last period?"* It cannot answer *"is the business we sign today better or worse than the business we signed two years ago?"* — and valuation turns on the second question. A weak new cohort hides inside a healthy blended number for years, because older, larger cohorts dominate the base.

This dataset contains exactly that pathology, seeded on purpose: customers acquired during a discounted promo push in **2024-H2** die at their first renewal — a churn cliff at months 10–14, which is how discounted year-one business actually fails: not gradually, but at the renewal decision.

```
cohort     ARR@0     M0     M3     M6     M9    M12    M18
2024Q2      3.0M   100%    98%    98%    94%    87%    84%
2024Q3      6.4M   100%    99%    95%    93%    86%    66%   <- promo
2024Q4      5.9M   100%    96%    89%    83%    75%    69%   <- promo
2025Q1      3.1M   100%    99%   102%   100%    99%
```

Total ARR rose every quarter through the promo window — headline growth never noticed. The heatmap makes it unmissable. `--validate` proves both that the cohort decomposition ties to total ARR to the dollar, and that the pathology clears a 10-point visibility threshold.

## LTV is empirical here, deliberately

The formulaic LTV (`ARPA × margin ÷ churn`) assumes constant churn forever and is the most abused number in SaaS. The payback curves here are **cumulative observed gross profit over CAC**, per channel and per segment, truncated where the observation window ends. No extrapolation is drawn where no data exists.

```
channel      customers   CAC total   payback  GP/CAC to date
self_serve         242        2.0M       4mo            4.2x
inbound            501       13.3M      12mo            2.1x
partner            290       13.1M      25mo            1.2x
outbound           417       25.3M   not yet            0.8x
```

The finding that would reach a board: **outbound has consumed $25M of CAC and has not yet returned it** — it lands the biggest logos and still hasn't crossed 1.0×, while inbound pays back in 12 months. That's a resource-allocation argument, not a dashboard decoration.

## Validation caught the generator twice

The first seeded pathology flagged only small self-serve deals — the *dollar-weighted* heatmap barely moved (a 2-point gap), and `--validate` failed the build. The fix wasn't to weaken the test; it was to make the pathology dollar-material and concentrate it at the renewal cliff. The trail is in the generator's comments: a cohort finding that isn't dollar-weighted isn't a finding.

## Notes

All data synthetic, seeded, reproducible. Built with Claude as a pair.
