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
        elif e.code == 400:
            # The usual cause, and it looks nothing like a permissions problem:
            # a Sheet created by importing a CSV does NOT number its first tab
            # gid=0, so the obvious guess returns 400 on a correctly shared file.
            hint = ("  Usually a wrong gid. A Sheet created by importing a CSV\n"
                    "  does not use gid=0 for its first tab. Open the tab in the\n"
                    "  browser and copy the gid= value out of the URL, then update\n"
                    "  config/sources.json.")
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
    """Fetch both sources, then install both or neither.

    Atomic by construction: each export is downloaded to a temporary file,
    BOTH temporaries must exist and be non-trivial before either destination
    is touched, and the swap into place happens last. An earlier version
    wrote the Sheet to disk the moment it arrived and only then fetched the
    Doc -- so a Sheet-success / Doc-failure left the two sources from
    different moments on disk, and with continue-on-error in the workflow
    that half-refreshed pair could be validated and committed. The docs
    claimed that was impossible. It was not, until this.
    """
    cfg = json.loads(CONFIG.read_text())
    targets = [
        ("Sheet", cfg["sheet"]["export_url"], ROOT / cfg["sheet"]["local_path"]),
        ("Doc", cfg["doc"]["export_url"], ROOT / cfg["doc"]["local_path"]),
    ]
    print("FETCHING CONTROLLED SOURCES")
    print("-" * 70)
    staged: list[tuple[str, Path, Path]] = []       # (label, tmp, dest)
    try:
        # Phase 1: download everything to temporaries. Nothing on disk changes.
        for label, url, dest in targets:
            body = _get(url)
            tmp = dest.with_suffix(dest.suffix + ".fetching")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(body)
            staged.append((label, tmp, dest))
            print(f"  ok    {label}: {len(body):,} bytes staged")
        if check_only:
            print("  (check only -- nothing installed)")
            return 0
        # Phase 2: both arrived. Install both. A failure here is a disk error,
        # not a network one, and is still reported before anything partial
        # can be committed.
        for label, tmp, dest in staged:
            tmp.replace(dest)
            print(f"  ok    {label}: installed -> {dest.relative_to(ROOT)}")
        staged = []
        print("-" * 70)
        return 0
    except FetchError as e:
        print(f"  FAIL  {e}", file=sys.stderr)
        print("\nRefusing to continue. Neither local copy was changed and the "
              "published dashboard stays as it is.", file=sys.stderr)
        return 1
    finally:
        # Any temporaries still staged mean we did not reach the install
        # phase. Remove them so a later run cannot mistake them for input.
        for _label, tmp, _dest in staged:
            try: tmp.unlink()
            except FileNotFoundError: pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch the Sheet and Doc exports")
    ap.add_argument("--check", action="store_true",
                    help="report reachability without writing files")
    args = ap.parse_args()
    return fetch(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
