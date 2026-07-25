# Board One-Pager

Thirty metrics in the five sections a board deck actually uses — **Growth** (ARR, net new ARR, YoY, bookings, billings, pipeline coverage), **Customer Health** (NRR, GRR, logo churn, count, ARPA, ACV), **Efficiency** (burn multiple, Rule of 40, magic number, CAC payback, LTV:CAC, ARR/FTE), **Financial** (cash, runway, GM, EBITDA, FCF, net burn), and **AI-Specific** (AI cost % of revenue, GM after AI costs, cost per inference, cost per 1K tokens) — every metric carrying its definition *on the page*. **No dependencies.**

```bash
python board.py            # console
python board.py --validate
python board.py --html examples/board_dashboard.html
```

**The definition column is the deliverable.** NRR, magic number, and CAC payback each have several defensible definitions; a scorecard that doesn't state which it uses will quietly disagree with someone else's deck within two quarters. Two honesty devices worth noting:

- **LTV:CAC is flagged as formulaic on the page itself** (`ARPA × GM ÷ churn` — "treat with the suspicion it deserves"), pointing to the empirical cohort version in [revenue-cohorts](../revenue-cohorts). Printing a number *and* its epistemic status is rarer than it should be.
- **GM after AI costs is the honest gross margin** — inference fully loaded in COGS, not adjusted out. The AI section watches the *trend* of AI cost as % of revenue, because the direction of that line is the whole AI-native margin story.

Everything computes from one seeded monthly series — no figure entered twice — and `--validate` recomputes the identities (ARR walk, EBITDA build, COGS build, cash roll-forward) from raw components. Built with Claude as a pair.
