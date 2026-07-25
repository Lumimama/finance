# Cash Burn & Runway Monitor

The standing weekly artifact a CEO glances at: burn, runway, the direction runway is moving, and the date the fundraise clock starts. **No dependencies**, Python 3.10+, synthetic data.

```bash
python burn.py            # console
python burn.py --validate
python burn.py --html examples/burn_dashboard.html
```

Four things a KPI tile can't show:

- **Gross vs net burn.** In 2026-02 a $2.4M one-time prepay makes single-month net burn go *negative*. It's a real cash movement so it sits in the burn bars — but it's excluded from the runway basis, because even a trailing-3-month average can't absorb a one-time item that large without distorting the trend. Gross burn is the number that doesn't lie.
- **Runway trajectory, not level.** A company can grow revenue while runway shrinks; the slope is the signal.
- **Runway measured on *operating* burn.** One-time items (a $2.4M prepay, one-time legal) are shown but excluded from the runway basis — a trailing-3-month average is too coarse to absorb a one-time item that large, and including it prints a runway cliff that isn't real. Validation proves operating-basis runway stays stable through the prepay while a naive net-burn runway would misread it by ~40 months.
- **The fundraise trigger.** Floor (12mo) + raise duration (6mo) = an 18-month threshold drawn on the chart. Where the runway line crosses it is the only date a board truly needs.
- **The burn bridge.** Why this month's net burn differs from last month's, by driver — and `--validate` proves the bridge ties to the actual change, every month, to the cent.

Built with Claude as a pair.
