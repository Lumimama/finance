"""
Generate the transaction-level dataset for the unit economics model.

One file: transactions.csv, ~120,000 rows over one quarter, for a mid-sized
payments platform. Each row carries everything needed to build per-transaction
contribution: rail, region, merchant segment, gross volume, and the cost
drivers (rewards share, fraud outcome, chargeback outcome).

The economics are modeled on how card networks and payment platforms actually
earn: interchange or take-rate revenue on volume, minus rewards funding, fraud
losses, chargeback losses and ops cost, processing cost, and customer
incentives. Numbers are synthetic but the *structure* -- which rails earn more,
which cost lines scale with volume vs count, where cross-border premium comes
from -- is faithful.

Deterministic: seeded.  Run:  python make_sample_data.py   (~10s)
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(20260430)

OUT = Path(__file__).parent / "data"
N = 120_000
Q_START = date(2026, 4, 1)
DAYS = 91

# rail: (weight, ticket_lognormal(mu, sigma), take_rate_pct, fixed_fee,
#        rewards_pct, fraud_bps, chargeback_bps, processing_cost, incentive_pct)
# take_rate here = the platform's revenue yield on volume (interchange share +
# scheme/assessment analog + FX markup where applicable).
RAILS = {
    "domestic_debit":  (0.33, (3.2, 0.85), 0.0052, 0.045, 0.0000, 2.1,  0.9, 0.028, 0.0004),
    "domestic_credit": (0.29, (3.7, 0.90), 0.0128, 0.020, 0.0071, 5.8,  3.1, 0.031, 0.0009),
    "ecom_credit":     (0.21, (3.9, 1.00), 0.0151, 0.020, 0.0074, 11.2, 6.4, 0.026, 0.0011),
    "cross_border":    (0.09, (4.3, 1.05), 0.0301, 0.020, 0.0069, 14.6, 7.2, 0.038, 0.0013),
    "tap_to_pay":      (0.08, (2.9, 0.70), 0.0088, 0.030, 0.0035, 1.4,  0.6, 0.024, 0.0006),
}

REGIONS = {           # weight, volume multiplier on ticket
    "north_america": (0.46, 1.00),
    "europe":        (0.24, 0.92),
    "latam":         (0.13, 0.71),
    "apac":          (0.17, 0.88),
}

SEGMENTS = {          # merchant segment: weight, ticket multiplier
    "enterprise_retail": (0.28, 1.35),
    "smb_retail":        (0.24, 0.72),
    "travel":            (0.11, 2.60),
    "grocery_fuel":      (0.17, 0.80),
    "digital_goods":     (0.12, 0.55),
    "restaurants":       (0.08, 0.60),
}


def weighted(d: dict) -> str:
    r, cum = random.random(), 0.0
    for k, v in d.items():
        cum += v[0]
        if r <= cum:
            return k
    return next(iter(d))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(1, N + 1):
        rail = weighted(RAILS)
        region = weighted(REGIONS)
        segment = weighted(SEGMENTS)
        (_, (mu, sig), take, fixed, rewards, fraud_bps, cb_bps,
         proc, incent) = RAILS[rail]

        ticket = round(min(random.lognormvariate(mu, sig)
                           * REGIONS[region][1] * SEGMENTS[segment][1], 25_000), 2)
        if ticket < 1:
            ticket = round(random.uniform(1, 4), 2)

        # Fraud and chargebacks are rare events carried per-row as outcomes,
        # so the model can compute realized (not just expected) loss rates.
        is_fraud = random.random() < fraud_bps / 10_000
        fraud_loss = round(ticket * random.uniform(0.6, 1.0), 2) if is_fraud else 0.0
        is_cb = (not is_fraud) and random.random() < cb_bps / 10_000
        cb_loss = round(ticket * random.uniform(0.3, 1.0) + 15, 2) if is_cb else 0.0

        rows.append({
            "txn_id": f"T{i:07d}",
            "txn_date": (Q_START + timedelta(days=random.randint(0, DAYS - 1))).isoformat(),
            "rail": rail,
            "region": region,
            "merchant_segment": segment,
            "gross_usd": ticket,
            "revenue_usd": round(ticket * take + fixed, 4),
            "rewards_cost_usd": round(ticket * rewards, 4),
            "fraud_loss_usd": fraud_loss,
            "chargeback_loss_usd": cb_loss,
            "processing_cost_usd": proc,
            "incentive_cost_usd": round(ticket * incent, 4),
        })

    with (OUT / "transactions.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    vol = sum(r["gross_usd"] for r in rows)
    rev = sum(r["revenue_usd"] for r in rows)
    print(f"transactions   {len(rows):>10,}")
    print(f"gross volume   ${vol:>14,.0f}")
    print(f"net revenue    ${rev:>14,.0f}   ({rev/vol*10_000:.1f} bps of volume)")
    print(f"wrote {OUT}/transactions.csv")


if __name__ == "__main__":
    main()
