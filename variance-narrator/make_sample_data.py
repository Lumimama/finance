"""
Generate the synthetic budget-vs-actuals dataset used by the demo.

Every number here is fabricated. The shape is realistic for a ~$40M ARR
B2B software company -- department structure, account taxonomy, and the
relative size of the variances -- but no figure comes from any real company.

Deterministic: seeded, so the committed CSV can always be reproduced.

Run:  python make_sample_data.py
"""

import csv
import random
from pathlib import Path

random.seed(20260214)

OUT = Path(__file__).parent / "data" / "budget_vs_actuals.csv"

PERIODS = ["2026-01", "2026-02", "2026-03"]

# (department, account, account_type, monthly_budget)
# account_type drives whether "over budget" is good or bad -- see
# variance_narrator.is_favorable().
PLAN = [
    ("Revenue",     "Subscription revenue",      "revenue", 3_050_000),
    ("Revenue",     "Services revenue",          "revenue",   240_000),
    ("Cost of revenue", "Hosting & infrastructure", "cogs",   410_000),
    ("Cost of revenue", "Support payroll",        "cogs",     265_000),
    ("Cost of revenue", "Third-party software",   "cogs",      88_000),
    ("Sales",       "Sales payroll",             "opex",      620_000),
    ("Sales",       "Commissions",               "opex",      215_000),
    ("Sales",       "Travel & entertainment",     "opex",      74_000),
    ("Marketing",   "Paid acquisition",          "opex",      330_000),
    ("Marketing",   "Events & field marketing",  "opex",      145_000),
    ("Marketing",   "Marketing payroll",         "opex",      210_000),
    ("Engineering", "Engineering payroll",       "opex",    1_180_000),
    ("Engineering", "Contractors",               "opex",      120_000),
    ("Engineering", "Tooling & dev infrastructure", "opex",    95_000),
    ("G&A",         "G&A payroll",               "opex",      340_000),
    ("G&A",         "Professional fees",         "opex",      110_000),
    ("G&A",         "Facilities",                "opex",       82_000),
    ("G&A",         "Insurance",                 "opex",       47_000),
]

# Accounts that carry a deliberate story, so the generated commentary has
# something real to explain. (account, period) -> multiplier on budget.
STORY = {
    ("Hosting & infrastructure", "2026-02"): 1.34,   # usage spike, no cost controls
    ("Hosting & infrastructure", "2026-03"): 1.41,
    ("Paid acquisition",         "2026-02"): 0.62,   # campaigns paused
    ("Paid acquisition",         "2026-03"): 0.58,
    ("Contractors",              "2026-03"): 1.85,   # backfilling open reqs
    ("Professional fees",        "2026-03"): 2.10,   # unbudgeted legal
    ("Subscription revenue",     "2026-03"): 1.06,   # upsell beat
    ("Commissions",              "2026-03"): 1.22,   # follows the revenue beat
    ("Engineering payroll",      "2026-01"): 0.91,   # slow hiring
    ("Engineering payroll",      "2026-02"): 0.89,
    ("Engineering payroll",      "2026-03"): 0.93,
    ("Events & field marketing", "2026-01"): 1.55,   # conference timing shift
}


def main() -> None:
    rows = []
    for period in PERIODS:
        for dept, account, acct_type, budget in PLAN:
            # Budgets grow modestly across the quarter for payroll-ish lines.
            growth = 1.0 + (0.01 * PERIODS.index(period)) if "payroll" in account.lower() else 1.0
            period_budget = round(budget * growth)

            multiplier = STORY.get((account, period), 1.0)
            # Everything else gets small, boring noise.
            noise = random.uniform(-0.04, 0.04)
            actual = round(period_budget * multiplier * (1 + noise))

            rows.append(
                {
                    "period": period,
                    "department": dept,
                    "account": account,
                    "account_type": acct_type,
                    "budget": period_budget,
                    "actual": actual,
                }
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["period", "department", "account", "account_type", "budget", "actual"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
