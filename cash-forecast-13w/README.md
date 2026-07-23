# 13-Week Cash Forecast

A direct-method 13-week cash forecast built from the AR aging, the AP aging, and the recurring commitments that appear in neither.

The 13-week is the one report that tells you whether the company survives the quarter. It is also, in most finance orgs, a spreadsheet that one person maintains by hand and nobody else can safely open. This is that spreadsheet as code — versioned, testable, and re-runnable under a different set of assumptions in about a second.

**No dependencies.** Python 3.10+, standard library only.

```bash
python cash_forecast.py --min-cash-floor 6000000
```

## Why direct method

An indirect forecast starts from net income and adjusts for non-cash items. That's the right tool for a twelve-month plan and the wrong one for a thirteen-week window, because what puts a company in trouble over thirteen weeks is *timing*, not profitability. Payroll clears on the 15th whether or not the enterprise invoice cleared on the 12th.

So this forecasts actual cash movements: which invoice lands in which week, which bill gets paid, and when payroll hits.

## Output

```
 Wk Week ending        Opening  Collections          AP     Payroll      Other          Net       Closing
--------------------------------------------------------------------------------------------------------
  1 2026-04-12     $14,850,000   $1,052,175   -$246,147          $0         $0     $806,028   $15,656,028
  2 2026-04-19     $15,656,028     $895,868   -$156,728 -$1,490,000         $0    -$750,860   $14,905,168
  ...
 13 2026-07-05     $12,383,132     $721,125          $0 -$1,586,000  -$230,000  -$1,094,875   $11,288,257 <

SUMMARY
  Opening cash                     $14,850,000
  Ending cash (week 13)            $11,288,257
  Net change                       -$3,561,743
  Low point                        $11,288,257   week 13 (ending 2026-07-05)
  Average weekly burn                 $273,980
  Runway at current burn               41.2 wks   (9.5 months)
  AR collecting after week 13         $680,313   (not in this forecast)

COVENANT / BOARD FLOOR: $6,000,000
  PASS - low point clears the floor by $5,288,257
```

`--html forecast.html` writes a self-contained page — chart, KPIs, and the weekly table, with no CDN and no build step. It opens straight from disk and follows the reader's light/dark theme. See [`examples/forecast.html`](examples/forecast.html), or [`examples/base-case.txt`](examples/base-case.txt) for the console version.

## The four questions it answers

1. **What is the low point, and which week?** The ending balance is rarely the number that matters. A forecast that ends at $11M having dipped to $4M in week 7 is a very different company from one that walks down smoothly.
2. **Does the low point breach the floor?** `--min-cash-floor` tests the trough against a covenant or a board commitment and reports the first breach week and the shortfall.
3. **How much runway is left?** Ending cash over average weekly burn, stated in weeks and months.
4. **What if collections slip?** See below.

## Scenarios

Collections timing is the largest single source of error in a 13-week, so it's the thing you stress first:

```bash
python cash_forecast.py --collections-slip 14 --revenue-haircut 0.10
```

| | Base | Collections +14 days, −10% |
|---|---|---|
| Ending cash | $11,288,257 | $9,361,615 |
| Net change | −$3,561,743 | −$5,488,385 |
| Runway | 41.2 wks | 22.2 wks |

Two weeks of collections slippage and a ten percent haircut cuts runway roughly in half. That sensitivity is the argument for tightening collections, and it's much more persuasive as a number than as an assertion.

`--ap-stretch 15` models the other lever — delaying payables — so you can see how much of the gap you can close from your own side of the ledger.

## Assumptions that drive everything

These live in one visible block at the top of `cash_forecast.py` rather than buried in the logic, because they *are* the forecast:

```python
COLLECTION_LAG_DAYS   = {"enterprise": 21, "mid_market": 9, "smb": 3}
PAST_DUE_CATCHUP_DAYS = {"enterprise": 12, "mid_market": 8, "smb": 5}
COLLECTION_RESERVE    = 0.015
```

Enterprise customers pay late and pay large; SMB pays close to terms. Segmenting the lag rather than applying one blended DSO is what makes the weekly shape right instead of just the quarterly total. In practice you'd derive these from your own trailing-twelve-month collection history and revisit them quarterly.

Two details worth calling out:

- **Past-due invoices don't collect retroactively.** An invoice 20 days past due can't land on `due + lag`, because that date has already happened. It gets pushed to a catch-up window measured from today. Miss this and the model books phantom cash in week 1.
- **Payroll is modeled separately from AP.** It isn't in the AP aging, it's the largest outflow, and it's the least flexible. Semi-monthly payroll lands on the 15th and the last day of the month, which is why some weeks show zero payroll and others carry two events.

## Data

Fully synthetic, generated by [`make_sample_data.py`](make_sample_data.py), seeded and reproducible. Three files matching how the data actually arrives:

| file | source in real life |
|---|---|
| `data/ar_open.csv` | AR aging export — invoice, customer, segment, amount, due date |
| `data/ap_open.csv` | AP aging export — bill, vendor, amount, due date |
| `data/recurring.csv` | the commitments in neither aging — payroll, lease, debt service, estimated taxes |

The shape is a roughly $40M ARR B2B software company: enterprise-weighted AR that pays late, semi-monthly payroll as the dominant outflow, a quarterly estimated tax payment sitting in the middle of the window. No figure comes from any real company.

## Notes

Built with Claude as a pair.
