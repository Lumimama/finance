# finance

Finance tooling I built for work that's already part of the job — payments reconciliation and unit economics, controls monitoring, a three-statement model, Monte Carlo scenario planning, variance commentary, a 13-week cash forecast, and a board metrics pack.

**Live dashboards:** [lumimama.github.io/finance](https://lumimama.github.io/finance/)

| project | what it does |
|---|---|
| [consolidation-fx](consolidation-fx) | ASC 830 consolidation: translation vs remeasurement, CTA proven two ways monthly, IC matrix catches a seeded transposition |
| [lease-accounting](lease-accounting) | ASC 842: 26-lease register, schedules amortize to exactly zero, disclosure ties to the cent, embedded lease found in a GPU 'services' contract |
| [payments-reconciliation](payments-reconciliation) | 50K transactions vs bank settlement; every break classified, aged, routed; validated against seeded ground truth |
| [payments-unit-economics](payments-unit-economics) | Contribution per transaction by rail/region/segment across 120K transactions; waterfall + mix-shift sensitivity |
| [controls-monitoring](controls-monitoring) | Seven audit detectors over a year of AP + T&E; 100% recall vs seeded issues, precision reported honestly |
| [three-statement-model](three-statement-model) | Driver-based P&L → BS → CF, three scenarios; ties to the cent or exits nonzero |
| [scenario-planner](scenario-planner) | 10K-run Monte Carlo; P10/P50/P90 fans, floor-breach probability, tornado of what drives the outcome |
| [headcount-planning](headcount-planning) | Fully-loaded cost, req-to-start lag, ramp, attrition — approved vs productive headcount |
| [pricing-architecture](pricing-architecture) | Four monetization models on identical demand: revenue, margin, forecastability, concentration |
| [robot-fleet-economics](robot-fleet-economics) | Per-robot P&L: utilization vs uptime, contribution vs depreciation, payback per unit |
| [training-capitalization](training-capitalization) | Training runs as R&D expense vs capitalized intangible — both treatments, same lifetime cost |
| [pilot-to-production](pilot-to-production) | True CAC including lost pilots, datable pilot purgatory, qualification counterfactual |
| [board-one-pager](board-one-pager) | 30 board metrics in five sections, every definition on the page, incl. AI-specific |
| [burn-runway](burn-runway) | Gross/net burn, runway trajectory, fundraise trigger, burn bridge that ties |
| [ai-infra-metrics](ai-infra-metrics) | Cost per token/inference, GPU utilization, cost-latency frontier, revenue per token |
| [usage-revenue-engine](usage-revenue-engine) | AI pricing: license + metered usage vs commits; utilization action list; rate compression vs inference cost |
| [revenue-cohorts](revenue-cohorts) | Cohort heatmap, layer cake, empirical CAC-payback curves by channel; dollar-weighted pathology detection |
| [revenue-recognition](revenue-recognition) | Bookings → billings → revenue; deferred and RPO roll-forwards tie to the cent every month |
| [revenue-forecast](revenue-forecast) | Capacity × ramp, pipeline coverage flags, per-contract risk-weighted renewal book |
| [pricing-waterfall](pricing-waterfall) | List → pocket price; quarter-end capitulation and size creep, quantified |
| [variance-narrator](variance-narrator) | Budget-vs-actuals → board commentary; Python computes, Claude drafts |
| [cash-forecast-13w](cash-forecast-13w) | Direct-method 13-week forecast with covenant testing and collections stress |
| [board-metrics](board-metrics) | NRR, GRR, burn multiple, CAC payback, Rule of 40 — definitions in the code |

Three ideas run through all of them:

**The spreadsheet is the model, and the model should be readable.** Most finance logic isn't complicated, it's just undocumented. Assumptions live in one visible block at the top of the file, not buried six columns into a hidden tab.

**Definitions are the deliverable.** Net retention has four defensible definitions, and a company using two of them across two decks has a credibility problem rather than a spreadsheet problem. Writing the definition next to the arithmetic fixes it permanently.

**AI belongs on the writing, not the arithmetic.** What's material, and the math that gets you there, should be deterministic and auditable. The thousand words explaining it to a board is pattern work — that's where a model earns its place.

All data is synthetic. Python 3.10+.

---

## [variance-narrator](variance-narrator) · budget-vs-actuals → board commentary

Python computes every figure — variance, direction, materiality, rollups — and Claude drafts the narrative from that computed evidence pack. The model never does arithmetic and never sees a number it wasn't handed, which is the only reliable way to stop a variance report from hallucinating one.

```bash
cd variance-narrator && pip install -r requirements.txt
python variance_narrator.py --dry-run
```

`--dry-run` prints the full analysis and the exact prompt, and makes no API call. That's the intended way to read it — the analysis is the part worth auditing, and you shouldn't need a key to audit it.

Two decisions worth calling out: materiality is a **dual test** (a line surfaces only if it clears both a dollar and a percentage threshold — either alone is useless), and favorability is derived from account type, because over budget is good news on revenue and bad news on spend.

## [cash-forecast-13w](cash-forecast-13w) · direct-method 13-week forecast

Built from the AR aging, the AP aging, and the recurring commitments that appear in neither. Reports the low point and the week it lands in, tests it against a covenant floor, and stress-tests runway.

```bash
cd cash-forecast-13w
python cash_forecast.py --min-cash-floor 6000000
python cash_forecast.py --collections-slip 14 --revenue-haircut 0.10
```

| | Base | Collections +14 days, −10% |
|---|---|---|
| Ending cash | $11,288,257 | $9,361,615 |
| Runway | 41.2 wks | 22.2 wks |

Two weeks of collections slippage and a ten percent haircut cuts runway roughly in half. That's a far better argument for tightening collections than an assertion is.

No dependencies.

## [board-metrics](board-metrics) · the twelve numbers a SaaS board asks for

NRR, GRR, burn multiple, CAC payback, magic number, Rule of 40 — each computed by a function whose docstring states which definition it uses. The ARR walk has to tie, and the report says whether it did.

```bash
cd board-metrics
python board_metrics.py
python board_metrics.py --html dashboard.html
```

Magic number here has no ×4, on purpose: the textbook form annualizes a change in quarterly *recognized revenue*, and net new ARR is already annual. Annualizing twice is how a company ends up reporting a magic number near 3.0 next to a 26-month CAC payback.

No dependencies.

---

## Dashboards

`cash-forecast-13w` and `board-metrics` both write a self-contained HTML page — no CDN, no build step, theme-aware, opens straight from disk.

GitHub renders `.html` as source rather than as a page, so to view one, download it and open it locally:

```bash
python board_metrics.py --html dashboard.html && open dashboard.html
```

## A note on the data

Every figure in this repository is fabricated. Each project ships a seeded `make_sample_data.py` that regenerates its dataset exactly, so the numbers are reproducible without being anyone's.

The shapes are realistic — enterprise-weighted AR that pays late, semi-monthly payroll as the dominant outflow, net retention around 111% — because logic tested against unrealistic data isn't tested.

<sub>Built with Claude as a pair, which is the workflow rather than a disclaimer.</sub>
