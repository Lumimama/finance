"""
Seeded demo series for the Board One-Pager.

This was `make_series()` inside board.py, and it was the whole input layer until
the dashboard moved to a Google Sheet. It stays for two reasons: a reviewer can
run `board.py --demo` with no credentials and no network, and its output is what
seeded the Sheet in the first place (`--demo --export-csv`), which makes it the
frozen baseline the live pipeline is checked against.

Standard library only. Seeded, so re-running is byte-identical.
"""
from __future__ import annotations

import random

MONTHS = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13)][:18]
OPENING_CASH = 34_000_000
INFRA_PCT, SUPPORT_PCT = 0.075, 0.055


def make_series() -> list[dict]:
    random.seed(20260815)                 # seeded here, not at import time
    rows = []
    arr = 21_500_000
    customers = 205
    cash = OPENING_CASH
    pipe_mult = 3.4
    for mi, month in enumerate(MONTHS):
        beg_arr, beg_cust = arr, customers
        new_arr = beg_arr * random.uniform(0.022, 0.034)
        expansion = beg_arr * random.uniform(0.012, 0.020)
        contraction = beg_arr * random.uniform(0.002, 0.005)
        churn_arr = beg_arr * random.uniform(0.005, 0.009)
        arr = beg_arr + new_arr + expansion - contraction - churn_arr

        new_cust = max(1, round(new_arr / random.uniform(75_000, 110_000)))
        churn_cust = max(0, round(beg_cust * random.uniform(0.004, 0.008)))
        customers = beg_cust + new_cust - churn_cust

        revenue = (beg_arr + arr) / 2 / 12
        # COGS built bottom-up; AI inference is its own line and stays IN COGS.
        # AI cost as % of revenue declines across the window -- the margin story.
        prog = mi / (len(MONTHS) - 1)
        ai_pct = 0.110 - 0.025 * prog                  # 11.0% -> 8.5% of revenue
        ai_cost = revenue * ai_pct * random.uniform(0.98, 1.02)
        # cost per 1k tokens declines too; tokens are derived so the unit
        # metrics stay internally consistent with the AI-cost line.
        cost_per_1k = 0.016 - 0.005 * prog             # $0.016 -> $0.011 / 1k tok
        tokens = ai_cost / cost_per_1k * 1000
        infra_cost = revenue * INFRA_PCT
        support_cost = revenue * SUPPORT_PCT
        cogs = ai_cost + infra_cost + support_cost     # GM ~ 76-78%
        inference_calls = tokens / 3_400

        sm = revenue * random.uniform(0.44, 0.50)
        rd = revenue * random.uniform(0.30, 0.34)
        ga = revenue * random.uniform(0.12, 0.15)
        ebitda = revenue - cogs - sm - rd - ga
        capex = revenue * 0.03
        fcf = ebitda - capex
        cash += fcf

        bookings = (new_arr + expansion) * random.uniform(1.0, 1.25)
        billings = revenue + (new_arr * 0.62) / 12 * 6   # crude deferred build
        pipe_mult *= random.uniform(0.985, 1.01)
        pipeline = (new_arr * 12 / 12 * 3) * pipe_mult   # next-Q new-ARR pipe

        rows.append({
            "month": month, "beg_arr": beg_arr, "new_arr": new_arr,
            "expansion": expansion, "contraction": contraction,
            "churn_arr": churn_arr, "arr": arr,
            "beg_cust": beg_cust, "new_cust": new_cust,
            "churn_cust": churn_cust, "customers": customers,
            "revenue": revenue, "cogs": cogs, "ai_cost": ai_cost,
            "infra_cost": infra_cost, "support_cost": support_cost,
            "tokens": tokens, "inference_calls": inference_calls,
            "sm": sm, "rd": rd, "ga": ga, "ebitda": ebitda,
            "capex": capex, "fcf": fcf, "cash": cash,
            "bookings": bookings, "billings": billings, "pipeline": pipeline,
            "headcount": round(118 + mi * 2.6),
        })
    return rows
