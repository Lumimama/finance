"""
Generate the synthetic 24-month operating dataset.

Everything is fabricated, but the ARR walk *ties* -- ending ARR each month
equals beginning plus new plus expansion less contraction less churn, exactly.
That matters: a metrics pack built on a walk that doesn't foot is worse than
no metrics pack, and it's the first thing a diligence team checks.

The trajectory is a B2B software company going from roughly $18M to roughly
$40M ARR over two years, with net retention around 110%, improving burn
efficiency, and a Series C landing in the middle.

Deterministic: seeded, so the committed CSV can always be reproduced.

Run:  python make_sample_data.py
"""

import csv
import random
from pathlib import Path

random.seed(20260630)

OUT = Path(__file__).parent / "data" / "monthly_metrics.csv"

START_ARR = 18_400_000.0
START_CASH = 18_000_000.0
START_CUSTOMERS = 341
START_HEADCOUNT = 143

MONTHS = [
    f"{y}-{m:02d}"
    for y in (2024, 2025, 2026)
    for m in range(1, 13)
][6:30]  # 2024-07 through 2026-06

FINANCING = {"2025-06": 30_000_000.0}  # Series C


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def main() -> None:
    rows = []
    arr = START_ARR
    cash = START_CASH
    customers = START_CUSTOMERS
    headcount = START_HEADCOUNT

    n = len(MONTHS)
    for i, month in enumerate(MONTHS):
        t = i / (n - 1)

        # --- ARR walk -----------------------------------------------------
        # New-business rate compresses as the base grows -- the same sales
        # team adding the same absolute dollars is a smaller percentage.
        new_rate = lerp(0.0325, 0.0240, t) * random.uniform(0.88, 1.12)
        expansion_rate = lerp(0.0150, 0.0172, t) * random.uniform(0.90, 1.10)
        contraction_rate = lerp(0.0034, 0.0028, t) * random.uniform(0.85, 1.15)
        churn_rate = lerp(0.0056, 0.0046, t) * random.uniform(0.80, 1.20)

        beginning_arr = arr
        new_arr = round(beginning_arr * new_rate)
        expansion_arr = round(beginning_arr * expansion_rate)
        contraction_arr = round(beginning_arr * contraction_rate)
        churned_arr = round(beginning_arr * churn_rate)
        ending_arr = beginning_arr + new_arr + expansion_arr - contraction_arr - churned_arr

        # --- Customers ----------------------------------------------------
        beginning_customers = customers
        new_customers = max(1, round(new_arr / random.uniform(58_000, 82_000)))
        churned_customers = max(0, round(beginning_customers * churn_rate * 0.75))
        ending_customers = beginning_customers + new_customers - churned_customers

        # --- P&L ----------------------------------------------------------
        # Revenue approximates recognized subscription revenue: roughly the
        # average of beginning and ending ARR, divided by twelve.
        revenue = round((beginning_arr + ending_arr) / 2 / 12)
        cogs = round(revenue * lerp(0.245, 0.215, t) * random.uniform(0.96, 1.04))
        sm_spend = round(revenue * lerp(0.63, 0.48, t) * random.uniform(0.93, 1.07))
        rd_spend = round(revenue * lerp(0.50, 0.36, t) * random.uniform(0.95, 1.05))
        ga_spend = round(revenue * lerp(0.213, 0.145, t) * random.uniform(0.94, 1.06))

        net_burn = revenue - (cogs + sm_spend + rd_spend + ga_spend)  # negative = burning
        financing = FINANCING.get(month, 0.0)
        beginning_cash = cash
        ending_cash = beginning_cash + net_burn + financing

        headcount = round(lerp(START_HEADCOUNT, 268, t) * random.uniform(0.985, 1.015))

        rows.append(
            {
                "month": month,
                "beginning_arr": round(beginning_arr),
                "new_arr": new_arr,
                "expansion_arr": expansion_arr,
                "contraction_arr": contraction_arr,
                "churned_arr": churned_arr,
                "ending_arr": round(ending_arr),
                "beginning_customers": beginning_customers,
                "new_customers": new_customers,
                "churned_customers": churned_customers,
                "ending_customers": ending_customers,
                "revenue": revenue,
                "cogs": cogs,
                "sm_spend": sm_spend,
                "rd_spend": rd_spend,
                "ga_spend": ga_spend,
                "financing_inflow": round(financing),
                "ending_cash": round(ending_cash),
                "headcount": headcount,
            }
        )

        arr = ending_arr
        cash = ending_cash
        customers = ending_customers

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} months to {OUT}")
    print(f"  ARR   {rows[0]['beginning_arr']:>12,} -> {rows[-1]['ending_arr']:>12,}")
    print(f"  Cash  {START_CASH:>12,.0f} -> {rows[-1]['ending_cash']:>12,}")
    print(f"  Custs {rows[0]['beginning_customers']:>12,} -> {rows[-1]['ending_customers']:>12,}")

    # The walk must foot. If this ever fails, the dataset is not usable.
    for r in rows:
        expected = (
            r["beginning_arr"] + r["new_arr"] + r["expansion_arr"]
            - r["contraction_arr"] - r["churned_arr"]
        )
        assert abs(expected - r["ending_arr"]) <= 1, f"ARR walk does not tie in {r['month']}"
    print("  ARR walk ties in all months.")


if __name__ == "__main__":
    main()
