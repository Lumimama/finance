# AI Infrastructure Metrics

The unit-economics layer between the P&L and the GPU cluster — because "cloud compute" as one P&L line is where AI gross margin goes to hide. 90 days of daily ops data: cost per 1K tokens and per inference (by model and blended), GPU utilization, latency percentiles, revenue per token, consumption vs committed-drawdown revenue, DAU/MAU. **No dependencies.**

```bash
python ai_metrics.py            # console
python ai_metrics.py --validate
python ai_metrics.py --html examples/ai_dashboard.html
```

Three seeded findings, each proven surfaced by `--validate`:

- **F1 — model routing is the highest-leverage finance action in an AI company.** A mid-window router deploy sends simple requests to a small model: blended cost per call falls **41%** at identical customer pricing, and GM after AI cost jumps. The chart shows finance *participating* in an engineering decision, which is the job.
- **F2 — the reserved cluster bills 24/7; weekend demand halves.** Idle weekend capacity quantified in $/yr — a batch/training-backfill candidate, not a cost cut.
- **F3 — the cost-latency frontier, made visible.** Above ~80% utilization, p95 latency roughly doubles. Running hotter is cheaper per token and slower per user; the tradeoff should be priced, not discovered.

The first version of the generator oversized the GPU cluster — utilization never ran hot, and F2/F3 failed validation. Sizing the cluster to the workload was the fix, documented in the code. Built with Claude as a pair.
