# Pricing Architecture Comparison

Before a company can forecast revenue it has to decide **how it charges**. For an intelligence layer running on someone else's hardware, that's genuinely open — and it's a finance question as much as a product one, because four candidate architectures produce very different businesses from *identical* customer demand.

**No dependencies.** Python 3.10+, synthetic data.

```bash
python pricing_models.py            # console
python pricing_models.py --validate
python pricing_models.py --html examples/pricing_arch_dashboard.html
```

Same 60 accounts, same 4,558 robots, same 195M tasks — four different invoices:

| model | revenue (18mo) | gross margin | MoM volatility | top-3 concentration |
|---|---|---|---|---|
| Per-robot subscription | $48.98M | 95.7% | 0.1% | 32% |
| Per-task metering | $28.29M | 92.6% | 5.3% | 29% |
| **OEM royalty** | **$83.60M** | 97.3% | 0.1% | **61%** |
| Hybrid platform + usage | $34.80M | 94.0% | 3.4% | 30% |

## Revenue is not the tiebreak

**Royalty wins revenue and loses the business.** It produces $83.6M — and puts **61% of revenue with three counterparties** who own the customer relationship, the hardware roadmap, and therefore the renewal. A pricing decision made on the revenue line alone picks this one.

It also isn't really a pricing choice. Royalty wins here only because it reaches **2.4× the units** — it's a go-to-market bet trading customer ownership for reach. Comparing it to the direct models on revenue is a category error, and the model says so.

**Metering buys value alignment with forecast error** — 5.3% month-over-month volatility against 0.1% for subscription. At a company still proving its plan to a board, forecast error is expensive in ways the revenue line doesn't show.

## What this model cannot answer — stated on the page

Demand is exogenous and identical across all four architectures. That's what makes the comparison clean, and it's also the limitation: **it cannot value hybrid's expansion motion** (revenue growing with usage without a renegotiation) **or the churn avoided by not overcharging light users** — the two reasons companies actually converge on hybrid.

On the axes this model *can* measure, plain per-robot subscription wins among direct options. Reading that as "therefore price per robot" takes the model past what it supports. That caveat is in the dashboard, not a footnote.

## A modelling error worth keeping visible

The first version applied the royalty rate to the *same* robot base, which made royalty look strictly worse and missed the entire trade royalty offers. Validation caught it. Reach is the point of an embedded model — lower price per unit, many more units — and the fix was to model that rather than weaken the test.

Price points are illustrative assumptions for a generic robotics foundation-model company, not a claim about any real company's pricing.

Built with Claude as a pair.
