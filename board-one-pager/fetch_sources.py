"""
Fetch the two controlled Google sources.

Reads config/sources.json and downloads:
    the Sheet's Monthly_Metrics tab  ->  data/monthly_metrics.csv
    the Doc's text export            ->  data/board_context.txt

Both are plain HTTPS GETs against Google's export endpoints. The files are
shared read-only by link, so there is no OAuth dance, no service account, and
no credential anywhere in this repository or in GitHub Actions.

A failed fetch is fatal and leaves the existing local copies untouched, which
is what keeps a stale-but-valid dashboard published when Google is unreachable
or the sharing setting is changed.

    python3 fetch_sources.py            # fetch both
    python3 fetch_sources.py --check    # report reachability, write nothing

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
CONFIG = HERE / "config" / "sources.json"
TIMEOUT = 30


class FetchError(RuntimeError):
    pass


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "board-one-pager/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
            final = r.geturl()
    except urllib.error.HTTPError as e:
        hint = ""
        if e.code in (401, 403):
            hint = ("  The file is not shared by link. In Google Drive open "
                    "Share > General access > 'Anyone with the link' (Viewer).")
        raise FetchError(f"HTTP {e.code} fetching {url}\n{hint}") from None
    except Exception as e:
        raise FetchError(f"could not reach {url}: {e}") from None
    # An un-shared file 302s to the sign-in page and returns HTML, not data.
    if "accounts.google.com" in final or body[:15].lstrip().lower().startswith(b"<!doctype html"):
        raise FetchError(
            f"{url}\n  returned Google's sign-in page rather than the export.\n"
            "  Set Share > General access > 'Anyone with the link' (Viewer).")
    if not body.strip():
        raise FetchError(f"{url} returned an empty body")
    return body


def fetch(check_only: bool = False) -> int:
    cfg = json.loads(CONFIG.read_text())
    targets = [
        ("Sheet", cfg["sheet"]["export_url"], ROOT / cfg["sheet"]["local_path"]),
        ("Doc", cfg["doc"]["export_url"], ROOT / cfg["doc"]["local_path"]),
    ]
    print("FETCHING CONTROLLED SOURCES")
    print("-" * 70)
    for label, url, dest in targets:
        try:
            body = _get(url)
        except FetchError as e:
            print(f"  FAIL  {label}: {e}", file=sys.stderr)
            print("\nRefusing to continue. Local copies are unchanged and the "
                  "published dashboard stays as it is.", file=sys.stderr)
            return 1
        size = len(body)
        if check_only:
            print(f"  ok    {label}: reachable, {size:,} bytes (not written)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        print(f"  ok    {label}: {size:,} bytes -> {dest.relative_to(ROOT)}")
    print("-" * 70)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch the Sheet and Doc exports")
    ap.add_argument("--check", action="store_true",
                    help="report reachability without writing files")
    args = ap.parse_args()
    return fetch(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
