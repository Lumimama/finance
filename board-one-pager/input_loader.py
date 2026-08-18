"""
Input layer for the Board One-Pager.

Replaces the seeded generator with two controlled sources that a human
maintains each month:

    Google Sheet  ->  data/monthly_metrics.csv     (numbers; one row per month)
    Google Doc    ->  data/board_context.txt       (reporting period, commentary,
                                                    disclosure -- narrative only)

Both files are plain exports (Sheet: File > Share > "Anyone with the link",
then the /export?format=csv URL; Doc: the /export?format=txt URL). The daily
GitHub Actions workflow curls them; a reviewer can also drop a CSV in by hand.

Everything here fails loudly. A malformed input raises InputError with the
field and month named, and board.py turns that into a non-zero exit so the
published dashboard is never overwritten by a broken refresh.

Standard library only.
"""
from __future__ import annotations

import csv
import hashlib
import math
import re
from pathlib import Path

REQUIRED_COLUMNS = [
    "month",
    "beg_arr", "new_arr", "expansion", "contraction", "churn_arr", "arr",
    "beg_cust", "new_cust", "churn_cust", "customers",
    "revenue", "ai_cost", "infra_cost", "support_cost", "cogs",
    "sm", "rd", "ga", "ebitda", "capex", "fcf", "cash",
    "bookings", "billings", "pipeline",
    "headcount", "tokens", "inference_calls",
]
NUMERIC_COLUMNS = [c for c in REQUIRED_COLUMNS if c != "month"]
COUNT_COLUMNS = ["beg_cust", "new_cust", "churn_cust", "customers", "headcount"]
MIN_ROWS = 12          # LTM window; YoY needs the first row's beginning ARR
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

DOC_HEADINGS = ["Reporting Period", "Metric Definitions", "Source Precedence",
                "Management Commentary", "Dashboard Disclosure"]


class InputError(ValueError):
    """Raised for any input problem. Message names the field/month."""


# ---------------------------------------------------------------------------
def _num(raw: str, col: str, month: str) -> float:
    s = (raw or "").strip().replace(",", "").replace("$", "")
    if s.startswith("(") and s.endswith(")"):        # accounting negatives
        s = "-" + s[1:-1]
    if s == "":
        raise InputError(f"{col} is blank for {month}")
    try:
        v = float(s)
    except ValueError:
        raise InputError(f"{col} for {month} is not a number: {raw!r}") from None
    if not math.isfinite(v):
        raise InputError(f"{col} for {month} is not finite: {raw!r}")
    return v


def load_csv(path: Path) -> list[dict]:
    """Read the normalized monthly table and return board.py's row structure."""
    path = Path(path)
    if not path.exists():
        raise InputError(f"input file not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise InputError(f"missing required column(s): {', '.join(missing)}")
        extra = [h for h in header if h and h not in REQUIRED_COLUMNS]
        rows = []
        for raw in reader:
            raw = {(k or "").strip(): (v or "") for k, v in raw.items()}
            if not any(v.strip() for v in raw.values()):
                continue                              # skip blank trailing rows
            month = raw["month"].strip()
            if not MONTH_RE.match(month):
                raise InputError(f"month {month!r} is not in YYYY-MM form")
            row = {"month": month}
            for c in NUMERIC_COLUMNS:
                v = _num(raw[c], c, month)
                if c in COUNT_COLUMNS:
                    if abs(v - round(v)) > 1e-6:
                        raise InputError(f"{c} for {month} must be a whole number, got {v}")
                    v = int(round(v))       # so the dashboard prints 330, not 330.0
                row[c] = v
            rows.append(row)

    if len(rows) < MIN_ROWS:
        raise InputError(f"need at least {MIN_ROWS} monthly rows, found {len(rows)}")
    months = [r["month"] for r in rows]
    dupes = sorted({m for m in months if months.count(m) > 1})
    if dupes:
        raise InputError(f"duplicate month(s): {', '.join(dupes)}")
    if months != sorted(months):
        raise InputError("months are not in chronological order (oldest first)")
    for a, b in zip(months, months[1:]):
        ya, ma = int(a[:4]), int(a[5:])
        yb, mb = int(b[:4]), int(b[5:])
        if (yb * 12 + mb) - (ya * 12 + ma) != 1:
            raise InputError(f"gap in months between {a} and {b}")
    for r in rows:
        for c in ("customers", "beg_cust", "headcount"):
            if r[c] <= 0:
                raise InputError(f"{c} must be positive for {r['month']}")
    # Denominators that produce N/A instead of a fabricated number are handled
    # in board.py; here we only refuse things that can't be data at all.
    if extra:
        print(f"note: ignoring extra column(s): {', '.join(extra)}")
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    """Export rows in the exact column order the loader expects (seeds the Sheet)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            # Counts stay integers; dollars keep six decimals so the seeded
            # export round-trips through the Sheet without the identities
            # drifting on rounding alone.
            out = {}
            for k in REQUIRED_COLUMNS:
                if k == "month":
                    out[k] = r[k]
                elif k in ("beg_cust", "new_cust", "churn_cust", "customers", "headcount"):
                    out[k] = f"{r[k]:.0f}"
                else:
                    out[k] = f"{r[k]:.6f}"
            w.writerow(out)


# ---------------------------------------------------------------------------
def load_context(path: Path | None) -> dict:
    """Parse the Google Doc text export into sections keyed by heading.

    The Doc uses the five fixed headings in DOC_HEADINGS, each on its own line.
    Anything before the first heading is ignored. Missing file -> empty context
    (the dashboard still renders; the commentary box says so).
    """
    ctx = {h: "" for h in DOC_HEADINGS}
    ctx["_present"] = False
    if not path or not Path(path).exists():
        return ctx
    text = Path(path).read_text(encoding="utf-8-sig")
    current = None
    buf: dict[str, list[str]] = {h: [] for h in DOC_HEADINGS}
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip().rstrip(":")
        if stripped in DOC_HEADINGS:
            current = stripped
            continue
        if current:
            buf[current].append(line.rstrip())
    for h in DOC_HEADINGS:
        ctx[h] = "\n".join(buf[h]).strip()
    ctx["_present"] = True
    missing = [h for h in DOC_HEADINGS if not ctx[h]]
    if missing:
        raise InputError(f"board context doc is missing section(s): {', '.join(missing)}")
    return ctx


def sha256_of(path: Path | None) -> str:
    if not path or not Path(path).exists():
        return ""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
