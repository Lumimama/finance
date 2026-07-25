# Pricing Waterfall — Discount Discipline

Where price leaks between list and contract, from ~1,100 closed deals: the classic pocket-price waterfall, realization by segment and deal size, and the two pathologies every pricing review looks for first.

**No dependencies.** Python 3.10+.

```bash
python pricing.py                # console report
python pricing.py --validate
python pricing.py --html examples/pricing_dashboard.html
```

## The two seeded pathologies

**Quarter-end capitulation.** Deals closed in the final two weeks of a quarter realize **5.9 points less** of list than deals closed earlier — sales spending price to make the date. On $13.8M of late-quarter list, that's **~$810K given to the calendar**. There is no cost to recovering it except saying no later in the quarter.

**Size creep.** Realization falls monotonically with deal size — 90% on sub-$20K deals down to 79% above $200K — faster than any cost-to-serve argument covers. Volume discounts are defensible; unmanaged depth drift is not, and the difference is only visible when you plot it.

Both patterns survive segmentation, which is what separates a pricing problem from a mix story. `--validate` proves the waterfall ties on every deal (list − standard − negotiated = realized, to the cent) and that both pathologies are surfaced.

## Why "pocket price"

A 2% average realization leak on a $40M bookings year is $800K of pure margin. The waterfall is how you show that to a sales leader without starting a fight about anyone's specific deal — the pattern is the argument, not the anecdote.

## Notes

Synthetic, seeded, reproducible. Built with Claude as a pair.
