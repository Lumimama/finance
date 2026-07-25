# Cash Burn & Runway Monitor

The standing weekly artifact a CEO glances at: burn, runway, the direction runway is moving, and the date the fundraise clock starts. **No dependencies**, Python 3.10+, synthetic data.

```bash
python burn.py            # console
python burn.py --validate
python burn.py --html examples/burn_dashboard.html
```

Four things a KPI tile can't show:

- **Gross vs net burn.** In 2026-02 a one-time annual prepay makes single-month net burn go *negative* — and single-month runway infinite. The trailing 3-month line barely moves. That contrast, seeded deliberately, is why t3 is the quotable number and gross burn is the one that doesn't lie.
- **Runway trajectory, not level.** A company can grow revenue while runway shrinks; the slope is the signal.
- **The fundraise trigger.** Floor (12mo) + raise duration (6mo) = an 18-month threshold drawn on the chart. Where the runway line crosses it is the only date a board truly needs.
- **The burn bridge.** Why this month's net burn differs from last month's, by driver — and `--validate` proves the bridge ties to the actual change, every month, to the cent.

Built with Claude as a pair.
