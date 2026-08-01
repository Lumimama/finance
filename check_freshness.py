"""
Staleness guard for published dashboards.

The audit of 2026-08-01 found the cohorts dashboard header reading 1,450
customers against a 1,448-row dataset. The cause was a figure hardcoded into
the HTML template rather than computed -- exactly the defect the per-project
--validate checks cannot see, because they validate the ANALYSIS, never the
PUBLISHED ARTIFACT.

This closes that gap: every examples/*.html must be newer than the script and
the data that produce it. Run before every push.

    python3 check_freshness.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).parent
stale, missing = [], []

for proj in sorted(p for p in ROOT.iterdir() if p.is_dir() and (p / "examples").is_dir()):
    htmls = list((proj / "examples").glob("*.html"))
    if not htmls:
        continue
    srcs = list(proj.glob("*.py")) + list((proj / "data").glob("*")) \
        if (proj / "data").is_dir() else list(proj.glob("*.py"))
    if not srcs:
        continue
    newest_src = max(s.stat().st_mtime for s in srcs)
    for h in htmls:
        if h.stat().st_mtime < newest_src - 2:      # 2s grace
            stale.append(f"{proj.name}/{h.name}")

print("DASHBOARD FRESHNESS")
print("-" * 70)
if stale:
    for s in stale:
        print(f"  STALE  {s}  (source newer than published HTML)")
    print("-" * 70)
    print(f"  FAIL -- {len(stale)} dashboard(s) out of date. Regenerate before pushing.")
    sys.exit(1)
print(f"  ok -- every published dashboard is newer than its source and data")
print("-" * 70)
print("  PASS")
