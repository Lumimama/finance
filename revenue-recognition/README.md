# Revenue Recognition — Bookings → Billings → Revenue

The controller-grade view of a subscription business: ~900 contracts expanded into billing schedules and ratable recognition, producing the three series everyone conflates — **bookings** (sales reality), **billings** (cash reality), **revenue** (GAAP reality) — plus the two balances they throw off: **deferred revenue** (billed, not yet earned) and **RPO** (booked, not yet earned; unbilled backlog = RPO − deferred).

**No dependencies.** Python 3.10+.

```bash
python revrec.py                # console report
python revrec.py --validate     # roll-forwards tie to the cent
python revrec.py --html examples/revrec_dashboard.html
```

## The invariant that makes this a model rather than three charts

```
deferred(end) = deferred(begin) + billings − revenue     … every month
RPO(end)      = RPO(begin)      + bookings − revenue     … every month
```

`--validate` checks both to the cent, every month, plus per-contract checks: every contract's billing schedule and recognition schedule must each sum exactly to its TCV. A rev-rec schedule whose roll-forwards don't tie is how audit adjustments happen.

```
[ok ] deferred(end) = deferred(beg) + billings - revenue   (max diff $0.0000)
[ok ] RPO(end) = RPO(beg) + bookings - revenue             (max diff $0.0000)
[ok ] every contract's recognition schedule sums to its TCV
[ok ] every contract's billing schedule sums to its TCV
[ok ] deferred unwind buckets sum to the deferred balance
```

The billing-schedule check failed on the first run — monthly invoices accumulated up to 18¢ of rounding drift per contract. Pennies, but a roll-forward that's allowed to drift by pennies is a roll-forward with no defined truth; the fix (a true-up on the final invoice) is standard billing-system behavior for exactly that reason.

## What the dashboard shows

- **Bookings vs billings vs revenue, monthly** — bookings lumpy, billings following invoice schedules, revenue smooth. A quarter where bookings spikes and revenue doesn't move is *working as designed*, and being able to say so is the job.
- **Deferred and RPO balances** over time.
- **Deferred unwind** — when today's $15.8M liability converts to revenue, by future quarter. This is the schedule that anchors next year's revenue floor.
- **RPO disclosure** split current / non-current, as filed.

## Notes

Contracts synthetic: 12–36 month terms, annual/quarterly/monthly billing mixes by segment (enterprise 80% annual-upfront). Built with Claude as a pair.
