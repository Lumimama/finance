# Board One-Pager

Thirty metrics in the five sections a board deck actually uses — **Growth** (ARR, net new ARR, YoY, bookings, billings, pipeline coverage), **Customer Health** (NRR, GRR, logo churn, count, ARPA, ACV), **Efficiency** (burn multiple, Rule of 40, magic number, CAC payback, LTV:CAC, ARR/FTE), **Financial** (cash, runway, GM, EBITDA, FCF, net burn), and **AI-Specific** (AI cost % of revenue, GM after AI costs, cost per inference, cost per 1K tokens) — every metric carrying its definition *on the page*. **No dependencies.**

```bash
python board.py --demo --validate          # offline: seeded series, no network
python fetch_sources.py                    # pull the Sheet + Doc exports
python board.py --input data/monthly_metrics.csv \
                --context data/board_context.txt \
                --validate \
                --html examples/board_dashboard.html \
                --manifest examples/board_manifest.json
```

## The monthly task this automates

The numbers live in a Google Sheet and the narrative lives in a Google Doc. Once
a month one row is added to the Sheet; a weekday GitHub Actions run fetches both,
revalidates every identity, and republishes the page.

| Source | Holds | Updated |
|---|---|---|
| Sheet → `Monthly_Metrics` | one row per month, raw components only | monthly, by hand |
| Doc → five fixed headings | reporting period, definitions, precedence, commentary, disclosure | as needed |

Totals in the Sheet (`arr`, `cogs`, `ebitda`, `fcf`, `cash`, `customers`, and both
beginning balances) are **formulas**, so the preparer types only the raw lines.
`--validate` then recomputes those same identities in Python from the raw
components — which is what catches the realistic failure, someone pasting a hard
number over a formula cell.

Both files are shared read-only by link, so `fetch_sources.py` is two HTTPS GETs:
no service account, no OAuth, no secret in the repository or in Actions. IDs are
in [`config/sources.json`](config/sources.json). If this were ever pointed at real
company data the export URLs would be replaced by a read-only service account with
its key in a repository secret — worth stating, because "shared by link" is the
right call for synthetic coursework data and the wrong one for anything else.

**Validation gates publication.** Any failure — a missing column, a duplicate
month, `not available` in a numeric field, an identity that stops footing, or an
unreachable Sheet — exits non-zero and writes nothing, so the last good dashboard
stays up rather than being replaced by a confident wrong number. The failure names
the field and the month. Verified against seven controlled cases:

| Input defect | Result |
|---|---|
| `ai_cost` column deleted | `missing required column(s): ai_cost` |
| latest month duplicated | `duplicate month(s): 2026-06` |
| `not available` in `revenue` | names the field and the month |
| `arr` overtyped +250,000 | ARR walk fails, names the month it breaks |
| one `ai_cost` in thousands | COGS build fails |
| Sheet un-shared | fetch fails with the sharing fix |
| fewer than 12 rows | `need at least 12 monthly rows` |

In all seven the published HTML is left byte-identical.

**The definition column is the deliverable.** NRR, magic number, and CAC payback each have several defensible definitions; a scorecard that doesn't state which it uses will quietly disagree with someone else's deck within two quarters. Two honesty devices worth noting:

- **LTV:CAC is flagged as formulaic on the page itself** (`ARPA × GM ÷ churn` — "treat with the suspicion it deserves"), pointing to the empirical cohort version in [revenue-cohorts](../revenue-cohorts). Printing a number *and* its epistemic status is rarer than it should be.
- **GM after AI costs is the honest gross margin** — inference fully loaded in COGS, not adjusted out. The AI section watches the *trend* of AI cost as % of revenue, because the direction of that line is the whole AI-native margin story.

Everything computes from one monthly series — no figure entered twice — and `--validate` recomputes seven identities (ARR walk and chain, EBITDA build, COGS build, cash roll-forward, FCF, customer walk, and that all 30 metrics carry a definition) from raw components. `--demo` keeps the seeded generator so a reviewer can run the whole thing offline. Built with Claude as a pair.

Two bugs the refactor surfaced, both invisible while the input was seeded:

- The COGS check compared `cogs` against *assumed* percentages of revenue (7.5% infra, 5.5% support) rather than the reported cost components. It could only ever validate the demo generator; against a real sheet it was checking nothing. The Sheet now carries `infra_cost` and `support_cost` as their own columns and the check foots them.
- The cash roll-forward accumulated a running balance from month one, so eighteen months of cent-rounding compounded into the final row and failed a sheet that was entirely correct — while hiding *which* month broke. It now checks each month against the reported prior balance.
