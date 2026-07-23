"""
Variance Narrator
=================
Turn a budget-vs-actuals export into the variance commentary that goes in
front of a CFO or a board.

The tedious half of a month-end close is not the math -- it's writing the
same twenty paragraphs of "hosting came in $138K over plan, driven by..."
every single month. The math is deterministic and belongs in code. The
writing is pattern work, and an LLM is good at pattern work once you hand
it the right facts.

So this splits cleanly in two:

  1. Python does the analysis. Variance, direction, materiality, rollups.
     Every number in the output is computed here -- the model never does
     arithmetic and never sees a number it wasn't given.
  2. Claude drafts the narrative from that computed evidence pack.

Run without an API key (--dry-run) and you still get the full analysis plus
the exact prompt that would have been sent. That's deliberate: the analysis
is the part you have to be able to audit.

Usage
-----
    python variance_narrator.py --dry-run
    python variance_narrator.py --period 2026-03
    python variance_narrator.py --threshold-usd 50000 --threshold-pct 0.15

Requires ANTHROPIC_API_KEY for live drafting. See README.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).parent / "data" / "budget_vs_actuals.csv"
MODEL = "claude-opus-4-8"

# Materiality: a line is worth commenting on only if it clears BOTH tests.
# A single test is the classic mistake -- a pure-percentage screen floods you
# with $3K office-supplies lines that moved 40%, and a pure-dollar screen
# buries a small account that quietly tripled. Both, or neither.
DEFAULT_THRESHOLD_USD = 25_000
DEFAULT_THRESHOLD_PCT = 0.10


# ---------------------------------------------------------------------------
# 1. Analysis  (all arithmetic lives here)
# ---------------------------------------------------------------------------
def load(path: Path = DATA_PATH) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"period", "department", "account", "account_type", "budget", "actual"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
    return df


def is_favorable(account_type: str, variance: float) -> bool:
    """Direction depends on which side of the P&L the account sits on.

    Coming in over budget is good news on revenue and bad news on spend.
    Getting this backwards is the single most common bug in home-grown
    variance reports -- it produces commentary that congratulates the team
    for overspending.
    """
    if account_type == "revenue":
        return variance > 0
    return variance < 0  # cogs, opex: under budget is favorable


def analyze(
    df: pd.DataFrame,
    period: str,
    threshold_usd: float = DEFAULT_THRESHOLD_USD,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
) -> dict:
    """Compute the evidence pack for one period."""
    p = df[df["period"] == period].copy()
    if p.empty:
        raise ValueError(
            f"No rows for period {period!r}. Available: {sorted(df['period'].unique())}"
        )

    p["variance"] = p["actual"] - p["budget"]
    p["variance_pct"] = p["variance"] / p["budget"]
    p["favorable"] = [
        is_favorable(t, v) for t, v in zip(p["account_type"], p["variance"])
    ]
    p["material"] = (p["variance"].abs() >= threshold_usd) & (
        p["variance_pct"].abs() >= threshold_pct
    )

    def total(mask) -> dict:
        sub = p[mask]
        b, a = float(sub["budget"].sum()), float(sub["actual"].sum())
        return {
            "budget": b,
            "actual": a,
            "variance": a - b,
            "variance_pct": (a - b) / b if b else 0.0,
        }

    revenue = total(p["account_type"] == "revenue")
    cogs = total(p["account_type"] == "cogs")
    opex = total(p["account_type"] == "opex")

    gross_profit = {
        "budget": revenue["budget"] - cogs["budget"],
        "actual": revenue["actual"] - cogs["actual"],
    }
    gross_profit["variance"] = gross_profit["actual"] - gross_profit["budget"]
    gross_margin_budget = gross_profit["budget"] / revenue["budget"]
    gross_margin_actual = gross_profit["actual"] / revenue["actual"]

    operating_income = {
        "budget": gross_profit["budget"] - opex["budget"],
        "actual": gross_profit["actual"] - opex["actual"],
    }
    operating_income["variance"] = operating_income["actual"] - operating_income["budget"]

    # Department rollup, ranked by how much it moved the bottom line.
    dept_rows = []
    for dept, sub in p.groupby("department"):
        b, a = float(sub["budget"].sum()), float(sub["actual"].sum())
        acct_type = sub["account_type"].iloc[0]
        dept_rows.append(
            {
                "department": dept,
                "budget": b,
                "actual": a,
                "variance": a - b,
                "variance_pct": (a - b) / b if b else 0.0,
                "favorable": is_favorable(acct_type, a - b),
            }
        )
    dept_rows.sort(key=lambda r: abs(r["variance"]), reverse=True)

    material = p[p["material"]].sort_values(
        "variance", key=lambda s: s.abs(), ascending=False
    )
    material_rows = [
        {
            "department": r["department"],
            "account": r["account"],
            "account_type": r["account_type"],
            "budget": float(r["budget"]),
            "actual": float(r["actual"]),
            "variance": float(r["variance"]),
            "variance_pct": float(r["variance_pct"]),
            "favorable": bool(r["favorable"]),
        }
        for _, r in material.iterrows()
    ]

    return {
        "period": period,
        "thresholds": {"usd": threshold_usd, "pct": threshold_pct},
        "summary": {
            "revenue": revenue,
            "cost_of_revenue": cogs,
            "gross_profit": gross_profit,
            "gross_margin_budget": gross_margin_budget,
            "gross_margin_actual": gross_margin_actual,
            "operating_expense": opex,
            "operating_income": operating_income,
        },
        "departments": dept_rows,
        "material_variances": material_rows,
        "lines_reviewed": int(len(p)),
        "lines_material": int(len(material_rows)),
    }


# ---------------------------------------------------------------------------
# 2. Presentation
# ---------------------------------------------------------------------------
def usd(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def print_analysis(a: dict) -> None:
    s = a["summary"]
    w = 78
    print("=" * w)
    print(f"VARIANCE ANALYSIS  |  {a['period']}")
    print("=" * w)
    print(f"{'':<24}{'Budget':>14}{'Actual':>14}{'Variance':>14}{'%':>10}")
    print("-" * w)
    for label, key in [
        ("Revenue", "revenue"),
        ("Cost of revenue", "cost_of_revenue"),
        ("Operating expense", "operating_expense"),
    ]:
        r = s[key]
        print(
            f"{label:<24}{usd(r['budget']):>14}{usd(r['actual']):>14}"
            f"{usd(r['variance']):>14}{pct(r['variance_pct']):>10}"
        )
    gp, oi = s["gross_profit"], s["operating_income"]
    print("-" * w)
    print(f"{'Gross profit':<24}{usd(gp['budget']):>14}{usd(gp['actual']):>14}{usd(gp['variance']):>14}")
    print(
        f"{'  gross margin':<24}{s['gross_margin_budget']:>13.1%}"
        f"{s['gross_margin_actual']:>14.1%}"
    )
    print(f"{'Operating income':<24}{usd(oi['budget']):>14}{usd(oi['actual']):>14}{usd(oi['variance']):>14}")
    print()

    t = a["thresholds"]
    print(
        f"Material variances  ({a['lines_material']} of {a['lines_reviewed']} lines "
        f"cleared both {usd(t['usd'])} and {t['pct']:.0%})"
    )
    print("-" * w)
    for m in a["material_variances"]:
        flag = "FAV" if m["favorable"] else "UNF"
        print(
            f"  [{flag}] {m['department']:<16} {m['account']:<30} "
            f"{usd(m['variance']):>12}  {pct(m['variance_pct']):>8}"
        )
    print()


# ---------------------------------------------------------------------------
# 3. Drafting
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are drafting the variance commentary section of a monthly financial \
package for a venture-backed B2B software company. Your reader is the CEO \
and the board.

Rules you do not break:

- Every number you write must appear in the analysis JSON you were given. \
Never compute, estimate, round differently, or infer a figure.
- You do not know the cause of any variance. The data contains no \
explanation. Where a driver would normally be stated, write the observable \
fact and flag what the FP&A owner needs to confirm -- e.g. "pending \
confirmation from the department owner" -- rather than inventing a reason.
- Lead with the bottom line, then the two or three variances that explain \
most of it. Do not walk the reader line by line through the whole file.
- Favorable and unfavorable are supplied per line. Respect them. Coming in \
over budget on an expense account is not good news.
- Plain declarative sentences. No filler openers, no "it is important to \
note," no bullet lists of adjectives.

Format: markdown. An H2 headline summary of two or three sentences, then \
"### Material variances" with one short paragraph per item, then \
"### Open items" listing what needs a human answer before this goes out."""


def build_prompt(a: dict) -> str:
    header = textwrap.dedent(
        f"""\
        Draft the variance commentary for {a['period']}.

        Here is the complete analysis. Every figure you cite must come from
        this object.
        """
    )
    return f"{header}\n```json\n{json.dumps(a, indent=2)}\n```\n"


def draft_commentary(a: dict, model: str = MODEL) -> str:
    """Call Claude to write the narrative. Requires ANTHROPIC_API_KEY."""
    try:
        import anthropic
    except ImportError:
        sys.exit("anthropic package not installed. Run: pip install -r requirements.txt")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "ANTHROPIC_API_KEY is not set.\n"
            "Set it, or run with --dry-run to see the analysis and the prompt "
            "without making an API call."
        )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(a)}],
    )
    return "".join(b.text for b in response.content if b.type == "text")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("--data", type=Path, default=DATA_PATH)
    ap.add_argument("--period", default=None, help="e.g. 2026-03 (default: latest)")
    ap.add_argument("--threshold-usd", type=float, default=DEFAULT_THRESHOLD_USD)
    ap.add_argument("--threshold-pct", type=float, default=DEFAULT_THRESHOLD_PCT)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the analysis and the prompt; make no API call.",
    )
    ap.add_argument("--out", type=Path, default=None, help="Write commentary to a file")
    args = ap.parse_args()

    df = load(args.data)
    period = args.period or sorted(df["period"].unique())[-1]
    a = analyze(df, period, args.threshold_usd, args.threshold_pct)

    print_analysis(a)

    if args.dry_run:
        print("=" * 78)
        print("PROMPT  (--dry-run: no API call made)")
        print("=" * 78)
        print(build_prompt(a))
        return

    print("Drafting commentary...\n")
    commentary = draft_commentary(a, args.model)
    print(commentary)

    if args.out:
        args.out.write_text(commentary)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
