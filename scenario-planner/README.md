# Monte Carlo Scenario Planner

A single-point forecast answers *"what do we expect?"* This answers the questions a board actually asks: **how bad can it get, with what probability, and which assumption should we be arguing about?**

10,000 simulations of 12 quarters, drivers drawn from distributions, stdlib only. Seeded and reproducible.

```bash
python simulate.py
python simulate.py --sims 20000
python simulate.py --html examples/scenario_dashboard.html
```

## Output

```
                               P10         P50         P90
Ending ARR                  $88.6M     $116.4M     $154.9M
Ending cash                 $38.3M      $73.7M     $118.3M

P(min cash < $20.0M board floor)      1.9%
P(cash goes negative)                 0.1%

TORNADO -- what actually drives ending cash
  New-business growth rate         +0.79
  Net revenue retention            +0.39
  S&M spend level                  -0.25
  Growth persistence               +0.23
  R&D + G&A level                  -0.12
  Gross margin                     +0.11
  Collections timing (DSO)         -0.07
```

The **tornado is the deliverable** — rank correlation of each input draw with ending cash across all 10,000 runs. Everything else says "there is risk"; the tornado says which lever to work. Here: argue about growth delivery and retention; gross margin and DSO are noise management.

The P50 also lands within ~10% of the deterministic [three-statement model](../three-statement-model)'s base case — the two models share drivers deliberately, and that agreement is a sanity check, not a coincidence.

## Two modeling decisions that changed the answer

Both are documented in the code where they happened, because the *trail* is the demonstration.

**1. The cash engine has to match the deterministic model.** The first version omitted deferred-revenue prepayments and the SBC add-back. Result: 73% floor-breach probability and growth rank-correlated **−0.45** with ending cash — the model said growth *destroys* cash. For a SaaS company collecting 62% of bookings annually up front, that's backwards: prepayments make growth cash-generative. One inconsistent cash engine and the simulation confidently recommends the wrong strategy.

**2. Opex is sticky.** Scaling opex as a % of *actual* revenue silently assumes instant cost discipline in a downside — which is exactly the scenario the planner exists to interrogate. Teams are hired against the *plan*. Modeling spend against planned revenue (only the ratios are drawn) flipped the tornado: S&M spend level dropped from the #1 driver to #3, and **growth delivery versus plan became dominant (+0.79)** — because when growth disappoints, committed spend doesn't shrink with it. That flip is the single most decision-relevant output of the model.

## Other choices worth noting

**DSO is right-skewed on purpose.** Collections slip further than they ever improve; a symmetric DSO distribution is a fantasy. The normal draw is passed through an exponential transform that stretches the right tail.

**Execution noise is per-quarter, not per-run.** Each quarter's growth gets independent noise on top of the drawn rate — so paths wobble realistically instead of being smooth curves at different slopes.

**Percentile fans, not means.** The dashboard shows P10/P50/P90 bands for cash and ARR by quarter. A mean path is a path nobody will actually experience.

## Notes

Synthetic company, consistent with the [three-statement model](../three-statement-model). Built with Claude as a pair.
