#!/usr/bin/env python3
"""Compare a scripts/run_tests.sh log with KNOWN_TEST_FAILURES.alfred.md (run by alfred-ci.yml's full suite).

The upstream suite cannot be fully green on a +Human tree: some tests pin the upstream names. Their files are
rows of the table in KNOWN_TEST_FAILURES.alfred.md, each with the number of tests known to fail there. This
script fails on a failing file that has no row, on a file where more tests fail than its row says or where no
test passes any more (a file that stopped importing reports one error, which would fit any row), and on a run
that did not reach its summary or ran nothing (a crash or a timeout would otherwise read as "no failures").

    python3 scripts/alfred/known_failures.py <run_tests log>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KNOWN = ROOT / "KNOWN_TEST_FAILURES.alfred.md"

# "[ 27.2% | 16752/~61669 | ✓25289 | ✗    1] ✗ tests/gateway/test_x.py (10✓ 1✗, 6.9s)"
FAILED_FILE_RE = re.compile(r"\] ✗ (tests/\S+\.py)(?: \(([^)]*)\))?")
COUNT_RE = re.compile(r"(\d+)(?:✗|e)(?=[ ,)]|$)")
PASSED_RE = re.compile(r"(\d+)✓")
# "| `tests/gateway/test_x.py` | 1 | why |"
KNOWN_ROW_RE = re.compile(r"^\|\s*`(tests/[^`\s]+\.py)`\s*\|\s*(\d+)\s*\|", re.MULTILINE)
COMPLETE_RE = re.compile(r"=== Summary: \d+ files?, ([1-9]\d*) tests? passed.*\(100% complete\)")


def known_failures(text: str) -> dict[str, int]:
    """{test file: how many of its tests are known to fail}."""
    return {path: int(count) for path, count in KNOWN_ROW_RE.findall(text)}


def failed_files(log: str) -> dict[str, int | None]:
    """{test file: failed + errored tests}; None when the file cannot be judged by a count: the runner printed
    none (a crash, a timeout), or none of its tests passed (it did not import, or every test broke)."""
    found: dict[str, int | None] = {}
    for path, detail in FAILED_FILE_RE.findall(log):
        counts = [int(n) for n in COUNT_RE.findall(detail)]
        passed = sum(int(n) for n in PASSED_RE.findall(detail))
        found[path] = sum(counts) if counts and passed else None
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    log = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
    known = known_failures(KNOWN.read_text(encoding="utf-8"))
    unexpected = 0
    failed = failed_files(log)
    for path, count in sorted(failed.items()):
        allowed = known.get(path)
        if allowed is not None and count is not None and count <= allowed:
            print(f"known failure: {path} ({count} of {allowed})")
            continue
        unexpected += 1
        what = "no test passed, or it did not finish" if count is None else f"{count} failing"
        limit = "no row" if allowed is None else f"{allowed} known"
        print(f"::error::unexpected failure: {path} ({what}, {limit} in {KNOWN.name})")
    if not COMPLETE_RE.search(log):
        print("::error::the test run did not reach its summary or passed no test: it crashed or timed out")
        return 1
    print(f"{len(failed)} failing file(s), {unexpected} unexpected")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
