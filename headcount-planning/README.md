# Headcount Plan & Capacity Model

The hiring plan *is* the budget. Headcount is 60–75% of opex at a growth-stage company, it's the largest thing a finance function actually controls, and it's the model that gets rebuilt every quarter and argued about in every board meeting.

**No dependencies.** Python 3.10+, synthetic data.

```bash
python headcount.py                    # console
python headcount.py --validate
python headcount.py --scenario slow    # plan | slow | fast
python headcount.py --html examples/headcount_dashboard.html
```

## Most headcount plans are wrong in three specific ways

**Salary isn't cost.** Employer tax and benefits add ~22.7% of base; equipment and software run $620/head/month; external hires carry a 20% recruiting fee on first-year base. This plan comes to **+34% over the salary-only budget — $7.9M** across 18 months. A hiring plan presented in base salary is not a budget.

**Approved ≠ on payroll ≠ productive.** A req approved in January produces a start in March or April, and that person isn't fully productive for another one to six months. **39 of 139 approved heads (28%) aren't productive capacity.** Budget cost from approval and you overstate cash; assume capacity from approval and you overstate output. Both errors get made in the same spreadsheet, in opposite directions, and they don't cancel.

**Attrition consumes reqs budgeted for growth.** 19 of 74 gross hires (26%) were replacements. A plan that treats gross hires as net adds under-staffs every quarter, then reports the shortfall as a recruiting problem.

## Ramp differs enormously by function

| dept | req→start | ramp | fully loaded / yr |
|---|---|---|---|
| Research | 4 mo | 3 mo | $336K |
| Engineering | 3 mo | 2 mo | $266K |
| Go-to-market | 2 mo | **6 mo** | $198K |

Go-to-market has the longest ramp *and* the highest attrition — so GTM hiring converts to capacity far more slowly than an engineering plan of the same size. Modelling both with one blended assumption is how sales capacity plans miss.

## A claim I had to narrow

I first wrote the capacity finding as *"the gap is widest while hiring is fastest."* Validation showed the effect is real but modest — 29% of approved headcount unproductive under fast hiring vs 27% under slow, because the already-ramped existing team dilutes it in both cases. The claim was narrowed to what actually holds: the gap is **structurally large (28%)**, from lag plus ramp, and it doesn't close by recruiting harder.

Built with Claude as a pair.
