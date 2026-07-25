# Integrated Three-Statement Model

Driver-based P&L → balance sheet → cash flow for a B2B software company, projected quarterly over three years with base / upside / downside scenarios — and the two checks that make a three-statement model a *model* rather than three tables.

**No dependencies.** Python 3.10+.

```bash
python model.py                    # base case + scenario comparison
python model.py --scenario downside
python model.py --check            # tie-out only, CI-style exit code
python model.py --html examples/three_statement.html
```

## The two checks

**Articulation.** Net income flows to retained earnings. SBC is added back in CFO and credited to APIC. Capex builds PP&E, which drives depreciation, which hits both the P&L and the CFO add-back. Deferred revenue drives billings, billings drive receivables, and the cash flow closes to the balance-sheet cash line. Nothing is entered twice; everything downstream is a consequence of the driver block at the top.

**The tie-out.** `assets = liabilities + equity`, every quarter, to the cent — and the model **exits nonzero rather than publishing** if it doesn't hold. A model that "mostly balances" is a model with a hidden plug somewhere.

```
  base       TIES
  upside     TIES
  downside   TIES
```

## The bug the check caught, kept on purpose

The first run failed with every quarter off by **exactly −$56,000,000**. A *constant* offset is a diagnostic gift: broken articulation drifts (the error compounds through retained earnings), while a bad **opening balance sheet** stays constant. The opening APIC figure was wrong by precisely $56M; the articulation was fine. The fix and the reasoning are documented at the driver where it happened — because "which of these two failure shapes am I looking at" is the first question to ask any model that doesn't balance, and the answer is usually visible in whether the error moves.

## Why deferred revenue is the spine

For a SaaS company billing annually up front, **cash collection leads revenue recognition**. That's why the model shows the classic pattern worth understanding before any board meeting:

```
SCENARIO COMPARISON  ($M)
                                base        upside      downside
FY29 ending ARR                 86.2         111.4          61.9
FY29 revenue                    79.0          97.7          59.6
FY29 net income                 -9.4          -7.2         -11.0
FY29 free cash flow              5.3          13.4          -1.7
FY29 ending cash                66.0          81.5          46.8
```

In the base case, **free cash flow turns positive while net income is still negative** — deferred revenue growth and the SBC add-back lead the P&L by several quarters. A reader who doesn't understand why those two lines cross in that order will misread every SaaS company's financials. The downside case shows the reverse trap: growth compression plus DSO stretching to 71 days turns FCF negative even as the P&L *loss narrows* — collections timing, not profitability, is what moves cash.

## Scenarios are driver deltas, not separate models

```python
SCENARIOS = {
    "base":     Drivers(),
    "upside":   Drivers(arr_growth_q=0.105, gross_margin=0.79, ...),
    "downside": Drivers(arr_growth_q=0.055, sm_pct_rev=0.50, dso_days=71.0, ...),
}
```

One `build()` function, three driver sets. Anything else — three tabs, three files, three formulas — guarantees the scenarios drift apart the first time someone edits one of them.

`--html` renders the **actual statements** — the income statement, the balance sheet, and the indirect-method cash flow, line by line across all twelve quarters, with scenario tabs. The tie-out rows are printed inside the statements themselves: `check: A − (L + E)` at the foot of the balance sheet and `check: = balance-sheet cash` at the foot of the cash flow, both 0.0 in every column. A model whose checks live in a separate summary is a model whose checks nobody reads.

## Notes

Synthetic company. Built with Claude as a pair.
