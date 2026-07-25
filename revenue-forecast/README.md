# Forward Revenue Model — Capacity, Pipeline, Renewals

The next four quarters of revenue built the way FP&A actually builds it — from the three books that exist today, not from a growth rate: **sales capacity** (reps × ramp × quota: the ceiling), **pipeline** (stage-weighted opportunities: the evidence), and the **renewal book** (contracts expiring, risk-weighted per contract: what can be kept).

**No dependencies.** Python 3.10+.

```bash
python forecast.py                # console report
python forecast.py --validate
python forecast.py --html examples/forecast_dashboard.html
```

## Design decisions

**Near-in quarters believe the pipe; far-out quarters believe capacity.** New bookings for Q+1/Q+2 come from stage-weighted pipeline (where the pipe is real); Q+3/Q+4 from capacity × 82% historical attainment (the pipe that will exist hasn't been generated yet). Mixing the two *and saying so* beats pretending either is a forecast on its own — the `new sourced from` column makes the switch explicit.

**Coverage is a leading indicator, flagged before it bites.** Raw pipeline ÷ capacity against a 3.0× planning floor. The seeded finding: Q+2 coverage sits at 0.5× — a pipeline-generation problem visible **two quarters before** it becomes a bookings miss, which is the entire point of running this weekly.

**Renewals are per-contract, not a blended rate.** Renewal risk is lumpy. Health-scored contracts (green 95% / yellow 80% / red 45%) produce the risk-weighted retention forecast — and the report names the largest at-risk contracts, because that list is what a CRO actually works. Seeded: two of the ten largest renewals are red, and `--validate` proves they surface.

```
[ok ] ARR build reconciles and chains (max diff $0.0000)
[ok ] Q+2 coverage 0.5x sits below the 3.0x floor and is flagged
[ok ] 3 red contracts in the top-10 renewal book, all surfaced in the at-risk list
[ok ] renewal book ties to the contract file
```

## Notes

38 reps, ~500 opportunities, ~440 renewal contracts — synthetic, seeded, reproducible. Built with Claude as a pair.
