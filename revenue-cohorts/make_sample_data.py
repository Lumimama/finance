"""
Generate the customer-month ARR panel for cohort analysis.

Two files:

    customers.csv     ~1,300 customers: segment, channel, cohort month, CAC
    arr_monthly.csv   customer x month ARR snapshots, 2022-01 .. 2026-06

The retention dynamics are deliberately structured, because a cohort analysis
of structureless data teaches nothing:

    - enterprise cohorts EXPAND over time (NDR > 100%: land-and-expand)
    - SMB cohorts decay steadily (logo churn dominates)
    - mid-market sits between
    - channels differ: outbound lands bigger but churns harder than inbound;
      self-serve is small, cheap, and leaky; partner in between
    - SEEDED FINDING: customers acquired 2024-07 .. 2024-12 via a paid-
      promo push ("promo24" flag) retain dramatically worse. Blended NRR
      barely moves; the cohort heatmap makes it unmissable. That contrast
      is the whole argument for cohort-level analysis.

Deterministic: seeded.  Run:  python make_sample_data.py
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

random.seed(20260601)

OUT = Path(__file__).parent / "data"

MONTHS = [f"{y}-{m:02d}" for y in range(2022, 2027) for m in range(1, 13)][:54]

SEGMENTS = {   # weight, initial ARR range, monthly churn, monthly expansion
    "enterprise": (0.14, (60_000, 240_000), 0.004, 0.016),
    "mid_market": (0.38, (12_000, 60_000), 0.011, 0.009),
    "smb":        (0.48, (1_800, 12_000), 0.027, 0.004),
}
CHANNELS = {   # weight, CAC as multiple of initial monthly ARR... simpler: CAC $ range by segment tier
    "inbound":   0.34,
    "outbound":  0.28,
    "partner":   0.20,
    "self_serve": 0.18,
}
# channel modifiers: (churn multiplier, expansion multiplier, CAC multiplier)
CHANNEL_MOD = {
    "inbound":    (0.85, 1.10, 0.70),
    "outbound":   (1.20, 1.05, 1.60),
    "partner":    (1.00, 0.95, 1.00),
    "self_serve": (1.45, 0.80, 0.25),
}
# CAC base: months of initial ARR by segment (payback-ish)
CAC_MONTHS = {"enterprise": 14.0, "mid_market": 10.0, "smb": 7.0}

PROMO_START, PROMO_END = "2024-07", "2024-12"


def weighted(d: dict) -> str:
    r, cum = random.random(), 0.0
    for k, v in d.items():
        w = v[0] if isinstance(v, tuple) else v
        cum += w
        if r <= cum:
            return k
    return next(iter(d))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    customers, panel = [], []
    cid = 0

    for mi, month in enumerate(MONTHS[:-1]):   # acquire through 2026-05
        # company scales: acquisition volume grows over time
        n_new = round(10 + mi * 0.55 * random.uniform(0.7, 1.3))
        # promo push: acquisition spikes during the promo window
        promo = PROMO_START <= month <= PROMO_END
        if promo:
            n_new = round(n_new * 1.8)

        for _ in range(n_new):
            cid += 1
            seg = weighted(SEGMENTS)
            ch = weighted(CHANNELS)
            _, (lo, hi), churn_m, expand_m = SEGMENTS[seg]
            ch_churn, ch_exp, ch_cac = CHANNEL_MOD[ch]
            arr = round(random.uniform(lo, hi), 2)

            # The promo push discounted first-year deals across every channel;
            # most of that business fails to renew. Applied broadly (65% of
            # window acquisitions) so it is DOLLAR-material at the cohort
            # level -- a first version flagged only small self-serve deals and
            # the dollar-weighted heatmap barely moved (2pt gap, caught by
            # --validate).
            is_promo = promo and random.random() < 0.65
            churn_mult = ch_churn * (3.4 if is_promo else 1.0)
            expand_mult = ch_exp * (0.35 if is_promo else 1.0)

            cac = round(arr / 12 * CAC_MONTHS[seg] * ch_cac
                        * random.uniform(0.8, 1.25), 2)
            customers.append({
                "customer_id": f"C{cid:05d}", "segment": seg, "channel": ch,
                "cohort_month": month, "initial_arr": arr, "cac": cac,
                "promo24": int(is_promo),
            })

            # simulate the ARR path from cohort month to end of window
            cur = arr
            for k, m2 in enumerate(MONTHS[mi:]):
                if cur <= 0:
                    break
                panel.append({"customer_id": f"C{cid:05d}", "month": m2,
                              "arr": round(cur, 2)})
                # Promo deals die at the first renewal: a churn cliff over
                # months 10-14. This is how discounted-year-one business
                # actually fails -- not gradually, but at the renewal decision.
                cliff = 3.5 if (is_promo and 9 <= k <= 14) else 1.0
                if random.random() < churn_m * churn_mult * cliff:
                    cur = 0.0
                elif random.random() < expand_m * 12 / 12:
                    cur *= random.uniform(1.05, 1.35) if random.random() < expand_mult else 1.0
                elif random.random() < 0.006:
                    cur *= random.uniform(0.7, 0.92)

    with (OUT / "customers.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(customers[0].keys()))
        w.writeheader(); w.writerows(customers)
    with (OUT / "arr_monthly.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["customer_id", "month", "arr"])
        w.writeheader(); w.writerows(panel)

    last = MONTHS[-1]
    ending = sum(r["arr"] for r in panel if r["month"] == last)
    print(f"customers        {len(customers):>8,}")
    print(f"panel rows       {len(panel):>8,}")
    print(f"ending ARR       ${ending:>12,.0f}   ({last})")
    print(f"promo24 flagged  {sum(c['promo24'] for c in customers):>8,}")
    print(f"wrote {OUT}/")


if __name__ == "__main__":
    main()
