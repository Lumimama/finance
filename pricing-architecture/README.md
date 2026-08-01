# Pricing Architecture Comparison

Before a company can forecast revenue it has to decide **how it charges**. For an intelligence layer running on someone else's hardware, that's genuinely open — and it's a finance question as much as a product one, because the candidate architectures produce very different businesses — and because two of the choices on the table are not the same kind of decision at all.

**No dependencies.** Python 3.10+, synthetic data.

```bash
python pricing_models.py            # console
python pricing_models.py --validate
python pricing_models.py --html examples/pricing_arch_dashboard.html
```

**Two separate questions, deliberately kept apart.**

### Question 1 — Pricing: demand held identical

Same 60 accounts, same 4,558 robots, same 195M tasks — four different invoices:

| model | revenue (18mo) | gross margin | MoM volatility | top-3 concentration |
|---|---|---|---|---|
| Per-robot subscription | $48.98M | 95.7% | 0.1% | 32% |
| Royalty rate, billed direct | $34.83M | 96.5% | 0.1% | 32% |
| Hybrid platform + usage | $34.80M | 94.0% | 3.4% | 30% |
| Per-task metering | $28.29M | 92.6% | 5.3% | 29% |

On identical units subscription earns most, because it charges most per robot. **As a price, royalty is simply worse** — the rate is lower.

**Metering buys value alignment with forecast error** — 5.3% month-over-month volatility against 0.1% for subscription. At a company still proving its plan to a board, that error is expensive in ways the revenue line doesn't show.

### Question 2 — Distribution: royalty + OEM reach

Embedding in OEM production reaches **2.4× the units** you could sell direct, so demand here is deliberately *not* constant:

| | revenue | top-3 concentration |
|---|---|---|
| Royalty + OEM reach | **$83.60M** | **61%** |

Royalty wins revenue **on reach, not on rate**. And the risk lands here, not in the pricing decision: the *same royalty rate* carries 32% concentration billed direct and **61%** through OEM partners who own the customer relationship, the hardware roadmap, and therefore the renewal.

**Concentration is a consequence of the distribution choice, not the pricing one** — which is exactly why the two questions have to be answered separately.

## A contradiction an audit caught

The first version of this page ran both questions together: it claimed demand was identical across all four models *and* that royalty reached 2.4× the units. Both cannot be true, and an external re-audit called it correctly. The fix wasn't cosmetic — separating the questions produced a better finding than the original had, because it isolates where the concentration risk actually comes from.

## What this model cannot answer — stated on the page

Demand is exogenous and identical across all four architectures. That's what makes the comparison clean, and it's also the limitation: **it cannot value hybrid's expansion motion** (revenue growing with usage without a renegotiation) **or the churn avoided by not overcharging light users** — the two reasons companies actually converge on hybrid.

On the axes this model *can* measure, plain per-robot subscription wins among direct options. Reading that as "therefore price per robot" takes the model past what it supports. That caveat is in the dashboard, not a footnote.

## A modelling error worth keeping visible

The first version applied the royalty rate to the *same* robot base, which made royalty look strictly worse and missed the entire trade royalty offers. Validation caught it. Reach is the point of an embedded model — lower price per unit, many more units — and the fix was to model that rather than weaken the test.

Price points are illustrative assumptions for a generic robotics foundation-model company, not a claim about any real company's pricing.

Built with Claude as a pair.
