# Training Run Capitalization & Amortization

The live accounting judgment at every foundation-model company: **is a training run research expense, or an internally-developed intangible asset?**

**No dependencies.** Python 3.10+, synthetic data.

```bash
python training_capex.py            # console
python training_capex.py --validate
python training_capex.py --html examples/training_dashboard.html
```

The question isn't academic. A company spending most of its capital on training runs reports a materially different EBITDA depending on the answer — and the answer is genuinely contested. So the defensible thing a finance function can do is model **both treatments**, state which one it uses, and bridge between them on demand.

## The identity that keeps both honest

> Over the full life of every run, expensing and capitalizing charge **exactly the same total** to the P&L. Capitalization does not reduce cost; it moves it later.

`--validate` proves this to the cent. It is the single most useful sentence to have ready in the room where someone proposes capitalizing to improve EBITDA.

## What the model shows

- **EBITDA under both treatments**, monthly, with impairment events marked
- **Intangible roll-forward**: opening + additions − amortization − impairment = closing, tying every month
- **Cost per run vs cost per unit of useful work** — both "training is getting more expensive" and "training is getting more efficient" are true, and quoting either alone is misleading

## The finding I got backwards

I built this expecting the EBITDA gap between treatments to **compress** as amortization caught up with spend. `--validate` disagreed: the gap **grows**, from $1.79M over the first eight months to $3.20M over the last eight — 1.8×.

The reason is structural. While training spend is still accelerating, amortization of older, smaller runs never catches up with capitalization of newer, larger ones. The flattering effect compounds instead of self-correcting, and reverses only when spend plateaus — which means the reversal lands in whichever year growth stops. That's a materially more alarming conclusion than the one I set out to demonstrate, and the check is why it's in here.

Two abandoned runs also impair in full ($1.74M), delivering lumpy charges that expensing would have spread smoothly — the risk capitalization actually carries.

**Not accounting advice.** The feasibility threshold (35% pre-feasibility) and 24-month useful life are modelling choices, stated on the page so they can be argued with.

Built with Claude as a pair.
