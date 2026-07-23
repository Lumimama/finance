"""
Generate the synthetic inputs for the 13-week forecast.

Three files, matching how this data actually arrives in real life:

  ar_open.csv   -- open invoices, straight out of the AR aging
  ap_open.csv   -- open bills, straight out of the AP aging
  recurring.csv -- the things that hit whether or not anyone invoices anyone

Everything is fabricated. The shape is realistic for a ~$40M ARR B2B
software company: enterprise-weighted AR that pays late, semi-monthly
payroll as the dominant outflow, a quarterly tax payment sitting in the
middle of the window.

Deterministic: seeded, so the committed CSVs can always be reproduced.

Run:  python make_sample_data.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(20260406)

DATA = Path(__file__).parent / "data"
AS_OF = date(2026, 4, 6)  # a Monday

SEGMENTS = [
    # (segment, weight, invoice size range)
    ("enterprise", 0.30, (85_000, 340_000)),
    ("mid_market", 0.45, (18_000, 70_000)),
    ("smb", 0.25, (2_500, 14_000)),
]

CUSTOMERS = {
    "enterprise": ["Northwind Logistics", "Cascade Health", "Meridian Bank",
                   "Halcyon Energy", "Fairhaven Group", "Silverline Retail"],
    "mid_market": ["Orchard Labs", "Brightpath", "Kestrel Systems", "Lumen Freight",
                   "Tidewater Co", "Alder & Finch", "Junction Media", "Vantage Ops",
                   "Pinewood Analytics", "Redshift Partners"],
    "smb": ["Copperfield", "Blue Harbor", "Ninth Street", "Maple & Co",
            "Ridgeline", "Foxglove", "Bayard", "Quill", "Thistle", "Wren Studio"],
}

VENDORS = [
    ("Amazon Web Services", (95_000, 145_000)),
    ("Datadog", (18_000, 26_000)),
    ("Snowflake", (22_000, 38_000)),
    ("Salesforce", (14_000, 19_000)),
    ("Outside counsel", (25_000, 90_000)),
    ("Recruiting agency", (30_000, 75_000)),
    ("Contract engineering", (40_000, 85_000)),
    ("Marketing agency", (20_000, 45_000)),
    ("Facilities & office", (8_000, 16_000)),
    ("Insurance broker", (11_000, 15_000)),
]


def write(name: str, fieldnames: list[str], rows: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / name
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows):>3} rows to {path}")


def make_ar() -> None:
    # Sized so collections across the window land near $9.5M -- roughly a
    # quarter's worth of billings for a company at this ARR. The forecast is
    # only useful if inflows and payroll are on the same scale.
    rows = []
    for i in range(125):
        r = random.random()
        cum = 0.0
        for seg, weight, (lo, hi) in SEGMENTS:
            cum += weight
            if r <= cum:
                segment, amount_range = seg, (lo, hi)
                break
        customer = random.choice(CUSTOMERS[segment])
        amount = round(random.uniform(*amount_range), 2)
        # Due dates spread from three weeks past due to eleven weeks out.
        due = AS_OF + timedelta(days=random.randint(-21, 77))
        rows.append(
            {
                "invoice_id": f"INV-{4200 + i}",
                "customer": customer,
                "segment": segment,
                "amount": amount,
                "due_date": due.isoformat(),
            }
        )
    rows.sort(key=lambda r: r["due_date"])
    write("ar_open.csv", ["invoice_id", "customer", "segment", "amount", "due_date"], rows)


def make_ap() -> None:
    rows = []
    for i in range(46):
        vendor, (lo, hi) = random.choice(VENDORS)
        amount = round(random.uniform(lo, hi), 2)
        due = AS_OF + timedelta(days=random.randint(-7, 84))
        rows.append(
            {
                "bill_id": f"BILL-{9100 + i}",
                "vendor": vendor,
                "amount": amount,
                "due_date": due.isoformat(),
            }
        )
    rows.sort(key=lambda r: r["due_date"])
    write("ap_open.csv", ["bill_id", "vendor", "amount", "due_date"], rows)


def make_recurring() -> None:
    rows = [
        # Payroll is the single largest and least flexible outflow. Splitting
        # it out from AP is the whole point of a direct-method forecast --
        # it does not sit in the AP aging and it does not move.
        {"name": "US payroll", "category": "payroll", "amount": 1_180_000,
         "cadence": "semimonthly", "day": ""},
        {"name": "Payroll taxes & benefits", "category": "payroll", "amount": 310_000,
         "cadence": "semimonthly", "day": ""},
        {"name": "Contractor payments", "category": "payroll", "amount": 96_000,
         "cadence": "monthly", "day": "1"},
        {"name": "Office lease", "category": "fixed", "amount": 142_000,
         "cadence": "monthly", "day": "1"},
        {"name": "Debt service", "category": "financing", "amount": 88_000,
         "cadence": "monthly", "day": "5"},
        {"name": "Estimated tax payment", "category": "tax", "amount": 265_000,
         "cadence": "quarterly", "day": "15"},
    ]
    write("recurring.csv", ["name", "category", "amount", "cadence", "day"], rows)


if __name__ == "__main__":
    make_ar()
    make_ap()
    make_recurring()
    print(f"\nAs-of date: {AS_OF.isoformat()}")
