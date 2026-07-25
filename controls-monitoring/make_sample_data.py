"""
Generate the AP + T&E dataset for the controls monitor.

Two files:

    ap_invoices.csv   ~18,000 vendor invoices over a fiscal year
    te_expenses.csv   ~22,000 employee expense lines over the same year

Clean in the overwhelming majority, with seven seeded control failures of the
kinds a continuous-controls-monitoring program actually catches:

    C1 duplicate payments      same vendor+amount+date-window, different invoice
    C2 round-dollar clustering a vendor billing suspiciously round amounts
    C3 split transactions      one purchase broken into n invoices under the
                               approval threshold, same vendor, days apart
    C4 benford violation       one vendor's invoice amounts fabricated (leading
                               digits uniform instead of Benford-distributed)
    C5 weekend/holiday entry   invoices entered on dates ops doesn't work
    C6 policy violations (T&E) meals over per-diem, unapproved airfare class
    C7 velocity anomaly        an employee's expense rate jumps 6x mid-year

seeded_findings.json records the ground truth for validation.

Deterministic: seeded.  Run:  python make_sample_data.py
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(20260715)

OUT = Path(__file__).parent / "data"
FY_START = date(2025, 7, 1)
DAYS = 365
APPROVAL_THRESHOLD = 10_000.0    # invoices >= this need VP approval

VENDORS = [
    # (name, category, monthly invoice count range, amount lognormal (mu, sigma))
    ("Amazon Web Services", "infrastructure", (28, 40), (7.6, 0.7)),
    ("Snowflake", "infrastructure", (4, 8), (8.4, 0.5)),
    ("Datadog", "infrastructure", (3, 6), (8.0, 0.4)),
    ("Salesforce", "software", (2, 4), (8.3, 0.3)),
    ("Atlassian", "software", (2, 4), (6.8, 0.4)),
    ("Figma", "software", (1, 3), (6.2, 0.4)),
    ("WeWork", "facilities", (2, 3), (8.9, 0.2)),
    ("Iron Mountain", "facilities", (1, 2), (5.8, 0.5)),
    ("Staples Business", "office", (6, 12), (4.9, 0.8)),
    ("Uline", "office", (2, 5), (5.6, 0.6)),
    ("Robert Half", "recruiting", (3, 8), (8.6, 0.5)),
    ("Indeed", "recruiting", (2, 4), (7.2, 0.5)),
    ("Wilson Sonsini", "legal", (1, 3), (9.2, 0.6)),
    ("PwC", "accounting", (1, 2), (9.5, 0.4)),
    ("Marsh Insurance", "insurance", (1, 2), (8.8, 0.3)),
    ("Global Catering Co", "events", (2, 6), (6.5, 0.7)),
    ("Apex Print Media", "marketing", (2, 5), (6.9, 0.6)),
    ("Meridian Travel", "travel", (4, 9), (6.8, 0.7)),
    ("CDW", "hardware", (3, 7), (7.4, 0.8)),
    ("Verizon Business", "telecom", (2, 3), (7.0, 0.2)),
]

# Long tail: real AP is a few big vendors plus hundreds of small ones.
TAIL_FIRST = ["Acme", "Borealis", "Cinder", "Dockside", "Ember", "Fulcrum",
              "Gable", "Harbor", "Inlet", "Juniper", "Keystone", "Loom",
              "Mosaic", "Nimbus", "Onyx", "Prairie", "Quarry", "Rampart",
              "Sable", "Tundra", "Umber", "Vela", "Wharf", "Yonder", "Zephyr"]
TAIL_LAST = ["Supply", "Services", "Solutions", "Consulting", "Partners",
             "Industries", "Group", "Labs", "Works", "Trading"]
TAIL_CATS = ["office", "software", "marketing", "facilities", "events",
             "hardware", "logistics", "professional_services"]
TAIL_VENDORS = [(f"{a} {b}", random.choice(TAIL_CATS), (0, 3), (5.8, 0.9))
                for a in TAIL_FIRST for b in TAIL_LAST]

EMPLOYEES = [f"E{n:03d}" for n in range(1, 381)]
DEPTS = ["sales", "engineering", "marketing", "g_and_a", "customer_success"]
EXPENSE_TYPES = [
    ("meals", 0.34, (12, 140)), ("airfare", 0.13, (180, 1400)),
    ("lodging", 0.16, (140, 480)), ("rideshare", 0.20, (8, 90)),
    ("software", 0.07, (10, 220)), ("conference", 0.04, (200, 1800)),
    ("office_supplies", 0.06, (5, 120)),
]
MEAL_PER_DIEM = 75.0


def biz_day(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    findings: dict[str, dict] = {}

    # ------------------------------------------------------------------ AP --
    invoices: list[dict] = []
    inv_n = 0

    def add_invoice(vendor: str, category: str, amount: float, d: date,
                    entered: date | None = None) -> dict:
        nonlocal inv_n
        inv_n += 1
        row = {
            "invoice_id": f"AP{inv_n:06d}",
            "vendor": vendor,
            "category": category,
            "invoice_date": d.isoformat(),
            "entered_date": (entered or biz_day(d + timedelta(days=random.randint(0, 4)))).isoformat(),
            "amount": round(amount, 2),
            "approver": f"M{random.randint(1, 14):02d}",
        }
        invoices.append(row)
        return row

    for vendor, cat, (lo_n, hi_n), (mu, sig) in VENDORS + TAIL_VENDORS:
        for m in range(12):
            month_start = FY_START + timedelta(days=30 * m)
            for _ in range(random.randint(lo_n, hi_n)):
                d = month_start + timedelta(days=random.randint(0, 27))
                amt = min(random.lognormvariate(mu, sig), 250_000)
                add_invoice(vendor, cat, amt, d)

    # C1: duplicate payments -- 14 pairs, same vendor & amount, 2-9 days apart,
    # different invoice ids. The second is the duplicate.
    dupes = []
    for _ in range(14):
        src = random.choice([i for i in invoices if i["amount"] > 2_000])
        d2 = date.fromisoformat(src["invoice_date"]) + timedelta(days=random.randint(2, 9))
        dup = add_invoice(src["vendor"], src["category"], src["amount"], d2)
        dupes.append({"original": src["invoice_id"], "duplicate": dup["invoice_id"],
                      "vendor": src["vendor"], "amount": src["amount"]})
    findings["C1_duplicates"] = {
        "count": len(dupes), "exposure": round(sum(d["amount"] for d in dupes), 2),
        "pairs": dupes}

    # C2: round-dollar vendor -- "Pinnacle Consulting" bills only round
    # thousands. Legit vendors almost never do at this frequency.
    round_ids = []
    for m in range(12):
        d = FY_START + timedelta(days=30 * m + random.randint(3, 24))
        amt = random.choice([5_000, 7_500, 9_000, 9_500, 12_000, 15_000])
        row = add_invoice("Pinnacle Consulting", "consulting", amt, d)
        round_ids.append(row["invoice_id"])
    findings["C2_round_dollar"] = {
        "vendor": "Pinnacle Consulting", "count": len(round_ids),
        "exposure": round(sum(i["amount"] for i in invoices
                              if i["vendor"] == "Pinnacle Consulting"), 2)}

    # C3: split transactions -- 6 clusters at "Summit Interiors": a purchase
    # over the $10K approval threshold split into 2-4 invoices just under it,
    # within a 10-day window, same approver.
    split_clusters = []
    for k in range(6):
        base_day = FY_START + timedelta(days=random.randint(10, 350))
        n_parts = random.randint(2, 4)
        total = random.uniform(14_000, 34_000)
        parts, ids = [], []
        remaining = total
        approver = f"M{random.randint(1, 14):02d}"
        for p in range(n_parts):
            if p == n_parts - 1:
                amt = remaining
            else:
                amt = random.uniform(6_500, 9_800)
                remaining -= amt
            amt = min(amt, 9_900)  # every part stays under threshold
            d = base_day + timedelta(days=random.randint(0, 9))
            row = add_invoice("Summit Interiors", "facilities", amt, d)
            row["approver"] = approver
            parts.append(round(amt, 2)); ids.append(row["invoice_id"])
        split_clusters.append({"invoice_ids": ids, "parts": parts,
                               "total": round(sum(parts), 2)})
    findings["C3_splits"] = {
        "vendor": "Summit Interiors", "clusters": len(split_clusters),
        "exposure": round(sum(c["total"] for c in split_clusters), 2),
        "detail": split_clusters}

    # C4: Benford violation -- "Northgate Logistics" amounts fabricated with
    # uniform leading digits (real spend follows Benford's law).
    benford_ids = []
    for _ in range(140):
        lead = random.randint(1, 9)
        mag = random.choice([100, 1000, 10000])
        amt = lead * mag + random.uniform(0, mag * 0.99)
        d = FY_START + timedelta(days=random.randint(0, 360))
        row = add_invoice("Northgate Logistics", "logistics", amt, d)
        benford_ids.append(row["invoice_id"])
    findings["C4_benford"] = {"vendor": "Northgate Logistics", "count": len(benford_ids)}

    # C5: weekend entries -- 31 invoices entered on Saturdays/Sundays.
    weekend_ids = []
    for _ in range(31):
        src = random.choice(invoices)
        d = date.fromisoformat(src["invoice_date"])
        wknd = d + timedelta(days=(5 - d.weekday()) % 7)
        row = add_invoice(src["vendor"], src["category"],
                          random.lognormvariate(7.0, 0.8), d, entered=wknd)
        weekend_ids.append(row["invoice_id"])
    findings["C5_weekend"] = {"count": len(weekend_ids)}

    # ------------------------------------------------------------------ T&E --
    expenses: list[dict] = []
    exp_n = 0

    def add_expense(emp: str, dept: str, etype: str, amount: float, d: date,
                    **extra) -> dict:
        nonlocal exp_n
        exp_n += 1
        row = {
            "expense_id": f"TE{exp_n:06d}",
            "employee_id": emp,
            "department": dept,
            "expense_type": etype,
            "expense_date": d.isoformat(),
            "amount": round(amount, 2),
            "cabin_class": extra.get("cabin", ""),
        }
        expenses.append(row)
        return row

    emp_dept = {e: random.choice(DEPTS) for e in EMPLOYEES}
    for e in EMPLOYEES:
        base_rate = random.uniform(0.4, 1.8)   # expenses per week
        n = int(base_rate * 52)
        for _ in range(n):
            r, cum = random.random(), 0.0
            for etype, wt, (lo, hi) in EXPENSE_TYPES:
                cum += wt
                if r <= cum:
                    break
            amt = random.uniform(lo, hi)
            if etype == "meals":
                amt = min(amt, MEAL_PER_DIEM * random.uniform(0.3, 1.0))
            d = FY_START + timedelta(days=random.randint(0, 360))
            cabin = "economy" if etype == "airfare" else ""
            add_expense(e, emp_dept[e], etype, amt, d, cabin=cabin)

    # C6: policy violations -- meals over per-diem (47) + business-class
    # airfare without approval flag (12).
    meal_ids, air_ids = [], []
    for _ in range(47):
        e = random.choice(EMPLOYEES)
        d = FY_START + timedelta(days=random.randint(0, 360))
        row = add_expense(e, emp_dept[e], "meals",
                          random.uniform(MEAL_PER_DIEM + 10, 320), d)
        meal_ids.append(row["expense_id"])
    for _ in range(12):
        e = random.choice(EMPLOYEES)
        d = FY_START + timedelta(days=random.randint(0, 360))
        row = add_expense(e, emp_dept[e], "airfare",
                          random.uniform(2_400, 6_800), d, cabin="business")
        air_ids.append(row["expense_id"])
    findings["C6_policy"] = {
        "meals_over_perdiem": len(meal_ids), "unapproved_business_air": len(air_ids),
        "meal_ids": meal_ids[:5], "air_ids": air_ids[:5]}

    # C7: velocity anomaly -- E077's monthly expense count jumps ~6x from Feb.
    hot = "E077"
    for m in range(7, 12):  # Feb..Jun of the FY
        month_start = FY_START + timedelta(days=30 * m)
        for _ in range(random.randint(22, 30)):
            etype, _, (lo, hi) = random.choice(EXPENSE_TYPES[:4])
            d = month_start + timedelta(days=random.randint(0, 27))
            add_expense(hot, emp_dept[hot], etype, random.uniform(lo, hi), d)
    findings["C7_velocity"] = {"employee_id": hot, "spike_from_month": "2026-02"}

    # --- write --------------------------------------------------------------
    random.shuffle(invoices)
    random.shuffle(expenses)
    with (OUT / "ap_invoices.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(invoices[0].keys()))
        w.writeheader(); w.writerows(invoices)
    with (OUT / "te_expenses.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(expenses[0].keys()))
        w.writeheader(); w.writerows(expenses)
    (OUT / "seeded_findings.json").write_text(json.dumps(findings, indent=2))

    print(f"AP invoices   {len(invoices):>8,}   ${sum(i['amount'] for i in invoices):>14,.0f}")
    print(f"T&E expenses  {len(expenses):>8,}   ${sum(e['amount'] for e in expenses):>14,.0f}")
    for k, v in findings.items():
        extra = v.get("count") or v.get("clusters") or ""
        print(f"  {k:<18} {extra}")
    print(f"wrote {OUT}/")


if __name__ == "__main__":
    main()
