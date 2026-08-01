# Robot Fleet Unit Economics

A per-robot P&L for a deployed fleet — the analysis that separates physical AI from software AI, because **a deployed robot is a capital asset that has to earn back its own cost**.

**No dependencies.** Python 3.10+, synthetic data.

```bash
python fleet.py            # console
python fleet.py --validate
python fleet.py --html examples/fleet_dashboard.html
```

## The asymmetry that drives everything

Software has no equivalent of an idle robot. An unused SaaS seat costs the vendor nothing. An unused robot has already consumed $68K–$112K of capex, is depreciating on schedule, and destroys capital every month it sits below its payback utilization.

So the metrics are different in kind, not just in name:

- **Utilization vs uptime are different problems.** A robot that is *up* but *idle* looks healthy on a maintenance dashboard and is the most expensive failure mode on the page.
- **Payback is measured against the depreciation life.** If a unit's projected payback exceeds 60 months, it never pays for itself — that's capital destruction, not low margin.
- **Contribution is charted against the depreciation line** each unit must out-earn to be worth owning. A software P&L has no equivalent chart.

## Two distinct failure modes, and they need opposite fixes

24 of 152 units (16% of the fleet, **$2.04M of capital**) never repay their hardware inside the depreciation life — for two different reasons:

- **25 are low-utilization sites.** The volume was never there; no price change fixes them. The remedy is redeployment or recovery.
- **9 are reliability failures** whose field-service cost now exceeds their revenue outright — worse than idle, because every month they run they lose money.

Field service is also tail-concentrated: the median unit costs $658/month — **10.8% of its own capex per year**, inside the 5–15% band typical for industrial equipment — while the mean is $873 (13.2%) and the worst 10% of units carry ~30% of all service cost. A dollar figure alone can't be judged; the capex ratio is what makes it interpretable. Budgeting from the mean over-provisions the healthy fleet and still under-provisions the tail.

## The pricing constraint the model enforces

Hourly rates here sit **below fully-loaded human labor** (~$22/hr in these settings) — a robot priced above the labor it replaces has no business case. That constraint is what makes fixed service cost, not price, the lever that decides whether a low-utilization unit can be saved. It can't.

## Validation

```
[ok ] robot-level revenue rolls up to the fleet monthly total
[ok ] contribution = revenue − direct opex, every month
[ok ] sanity bounds: utilization/uptime in [0,1], hours used ≤ available
[ok ] F1: 33 units never clear capex, concentrated in low-utilization sites
[ok ] F2: field-service cost is tail-concentrated (mean/median 1.39x)
[ok ] F3: utilization ramps after install (M0 15% → M4 61%)
```

The first version priced robots at $30/hr against $42K capex — which made even a 22%-utilized unit pay back in 23 months, so no cohort ever failed and F1 didn't fire. Validation caught it. The fix was realistic robotics economics, not a weaker test.

Built with Claude as a pair.
