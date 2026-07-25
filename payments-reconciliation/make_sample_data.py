"""
Generate the two-sided transaction dataset for the reconciliation engine.

Two files, mirroring how this data actually arrives:

    processor_ledger.csv   what our platform believes happened (auth/capture)
    bank_settlement.csv    what the acquiring bank actually settled

~50,000 ledger transactions across 14 settlement days. The two files agree on
the overwhelming majority -- as they do in real life -- and disagree in seven
deliberate, realistic ways:

    B1 timing lag        settled T+2 instead of T+1 (weekend/holiday spill)
    B2 amount mismatch   settled amount differs (partial capture, tip adjust)
    B3 missing at bank   in the ledger, never settled (auth expired, batch cut)
    B4 missing in ledger bank settled something we have no record of
    B5 duplicate settle  bank settled the same transaction twice
    B6 fx variance       cross-border settled at a different FX rate
    B7 fee discrepancy   interchange + scheme fee off vs the published schedule

Everything is synthetic. Deterministic: seeded.

Run:  python make_sample_data.py     (takes ~5s)
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(20260724)

OUT = Path(__file__).parent / "data"

DAYS = [date(2026, 6, 1) + timedelta(days=i) for i in range(14)]  # Mon Jun 1 ..
N_TXN = 50_000

# (rail, weight, ticket range USD, interchange %, fixed fee, scheme fee %)
RAILS = [
    ("card_present_debit",   0.34, (4, 220),    0.0105, 0.21, 0.0013),
    ("card_present_credit",  0.26, (8, 480),    0.0165, 0.10, 0.0014),
    ("ecom_credit",          0.22, (12, 640),   0.0195, 0.10, 0.0014),
    ("ecom_debit",           0.10, (6, 300),    0.0140, 0.22, 0.0013),
    ("cross_border",         0.08, (18, 900),   0.0215, 0.10, 0.0110),  # incl. FX markup
]

MCCS = ["5411 Grocery", "5812 Restaurants", "5541 Fuel", "5999 Retail",
        "4121 Rideshare", "5732 Electronics", "5912 Pharmacy", "7011 Lodging",
        "5814 Fast Food", "4899 Streaming"]

CURRENCIES = {"cross_border": [("EUR", 1.082), ("GBP", 1.278), ("CAD", 0.731),
                               ("MXN", 0.0542), ("JPY", 0.00641)]}


def pick_rail() -> tuple:
    r, cum = random.random(), 0.0
    for rail in RAILS:
        cum += rail[1]
        if r <= cum:
            return rail
    return RAILS[0]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ledger: list[dict] = []
    settle: list[dict] = []

    # --- generate the clean population ------------------------------------
    for i in range(1, N_TXN + 1):
        rail, _, (lo, hi), ic_pct, ic_fix, scheme_pct = pick_rail()
        txn_day = random.choice(DAYS)
        amount = round(random.uniform(lo, hi), 2)

        if rail == "cross_border":
            ccy, fx = random.choice(CURRENCIES["cross_border"])
            local_amount = round(amount / fx, 2)
        else:
            ccy, fx, local_amount = "USD", 1.0, amount

        interchange = round(amount * ic_pct + ic_fix, 2)
        scheme_fee = round(amount * scheme_pct, 2)
        net = round(amount - interchange - scheme_fee, 2)

        led = {
            "txn_id": f"TXN{i:06d}",
            "txn_date": txn_day.isoformat(),
            "rail": rail,
            "mcc": random.choice(MCCS),
            "currency": ccy,
            "local_amount": local_amount,
            "fx_rate": fx,
            "gross_usd": amount,
            "expected_interchange": interchange,
            "expected_scheme_fee": scheme_fee,
            "expected_net": net,
        }
        ledger.append(led)

        # normal settlement: T+1, matching amounts and fees
        settle.append({
            "settlement_id": f"STL{i:06d}",
            "txn_ref": led["txn_id"],
            "settle_date": (txn_day + timedelta(days=1)).isoformat(),
            "gross_usd": amount,
            "interchange": interchange,
            "scheme_fee": scheme_fee,
            "net_usd": net,
        })

    # --- seed the breaks ---------------------------------------------------
    # One mutable pool; every draw removes what it took, so no transaction can
    # carry two different breaks. (An earlier version reset a cursor into a
    # shared list and silently double-seeded 203 transactions -- caught by
    # reconcile.py --validate, which is the whole point of shipping one.)
    pool = list(range(N_TXN))
    random.shuffle(pool)

    def take(n: int, pred=None) -> list[int]:
        chosen, kept = [], []
        for j in pool:
            if len(chosen) < n and (pred is None or pred(j)):
                chosen.append(j)
            else:
                kept.append(j)
        pool[:] = kept
        if len(chosen) < n:
            raise RuntimeError(f"pool exhausted: wanted {n}, got {len(chosen)}")
        return chosen

    breaks: dict[str, list[str]] = {}

    # B1 timing lag: settled T+2/T+3 instead of T+1 (492 txns)
    b1 = take(492)
    for j in b1:
        d = date.fromisoformat(settle[j]["settle_date"])
        settle[j]["settle_date"] = (d + timedelta(days=random.choice([1, 2]))).isoformat()
    breaks["B1_timing"] = [ledger[j]["txn_id"] for j in b1]

    # B2 amount mismatch: settled gross differs (tip adjustment, partial
    # capture). Constrained off cross_border -- a gross variance there IS an
    # FX variance, and seeding one as the other would make the labels wrong.
    b2 = take(163, pred=lambda j: ledger[j]["rail"] != "cross_border")
    for j in b2:
        delta = round(random.choice([1, -1]) * random.uniform(0.5, 40), 2)
        g = round(settle[j]["gross_usd"] + delta, 2)
        settle[j]["gross_usd"] = g
        settle[j]["net_usd"] = round(g - settle[j]["interchange"] - settle[j]["scheme_fee"], 2)
    breaks["B2_amount"] = [ledger[j]["txn_id"] for j in b2]

    # B3 missing at bank: ledger row never settles (auth expired / batch cut) (117)
    b3 = take(117)
    b3_ids = {f"STL{j+1:06d}" for j in b3}
    settle = [s for s in settle if s["settlement_id"] not in b3_ids]
    breaks["B3_missing_at_bank"] = [ledger[j]["txn_id"] for j in b3]

    # B4 missing in ledger: bank settles txns we have no record of (58)
    b4_ids = []
    for k in range(58):
        rail, _, (lo, hi), ic_pct, ic_fix, scheme_pct = pick_rail()
        amount = round(random.uniform(lo, hi), 2)
        ic = round(amount * ic_pct + ic_fix, 2)
        sf = round(amount * scheme_pct, 2)
        sid = f"STL9{k:05d}"
        settle.append({
            "settlement_id": sid,
            "txn_ref": f"TXN9{k:05d}",     # reference that exists nowhere
            "settle_date": (random.choice(DAYS) + timedelta(days=1)).isoformat(),
            "gross_usd": amount, "interchange": ic, "scheme_fee": sf,
            "net_usd": round(amount - ic - sf, 2),
        })
        b4_ids.append(f"TXN9{k:05d}")
    breaks["B4_missing_in_ledger"] = b4_ids

    # B5 duplicate settlement: same txn_ref settled twice (41)
    b5 = take(41)
    for j in b5:
        src = next(s for s in settle if s["txn_ref"] == ledger[j]["txn_id"])
        dup = dict(src)
        dup["settlement_id"] = src["settlement_id"].replace("STL", "STD")
        dup["settle_date"] = (date.fromisoformat(src["settle_date"])
                              + timedelta(days=1)).isoformat()
        settle.append(dup)
    breaks["B5_duplicate"] = [ledger[j]["txn_id"] for j in b5]

    # B6 FX variance: cross-border settled at a slightly different rate (74)
    xb = take(74, pred=lambda j: ledger[j]["rail"] == "cross_border")
    for j in xb:
        s = next(s for s in settle if s["txn_ref"] == ledger[j]["txn_id"])
        drift = random.uniform(-0.018, 0.018)
        g = round(ledger[j]["local_amount"] * ledger[j]["fx_rate"] * (1 + drift), 2)
        s["gross_usd"] = g
        s["net_usd"] = round(g - s["interchange"] - s["scheme_fee"], 2)
    breaks["B6_fx_variance"] = [ledger[j]["txn_id"] for j in xb]

    # B7 fee discrepancy: interchange charged off-schedule (203)
    b7 = take(203)
    for j in b7:
        s = next(s for s in settle if s["txn_ref"] == ledger[j]["txn_id"])
        s["interchange"] = round(s["interchange"] * random.uniform(1.06, 1.35), 2)
        s["net_usd"] = round(s["gross_usd"] - s["interchange"] - s["scheme_fee"], 2)
    breaks["B7_fee"] = [ledger[j]["txn_id"] for j in b7]

    # --- write -------------------------------------------------------------
    random.shuffle(settle)   # settlement files never arrive in ledger order
    with (OUT / "processor_ledger.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ledger[0].keys()))
        w.writeheader(); w.writerows(ledger)
    with (OUT / "bank_settlement.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(settle[0].keys()))
        w.writeheader(); w.writerows(settle)

    import json
    (OUT / "seeded_breaks.json").write_text(json.dumps(
        {k: {"count": len(v), "txn_ids": v[:10]} for k, v in breaks.items()},
        indent=2))

    total = sum(len(v) for v in breaks.values())
    print(f"ledger rows      {len(ledger):>7,}")
    print(f"settlement rows  {len(settle):>7,}")
    print(f"seeded breaks    {total:>7,}  ({total/len(ledger)*100:.2f}% of ledger)")
    for k, v in breaks.items():
        print(f"  {k:<22} {len(v):>5}")
    print(f"\nwrote {OUT}/")


if __name__ == "__main__":
    main()
