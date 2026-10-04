#!/usr/bin/env python3
"""Flag anything in the standing instructions that looks specific to a track or task.

A mandate that names track-specific detail (product nouns, endpoint paths,
field names, error codes) disqualifies the entry. Run this before every
submission and after any edit to mandates/, PROTOCOL.md or CLAUDE.md:

    python3 scripts/check_mandates.py

Exit code 0 means nothing suspicious was found. It is a guard, not a proof:
still read the mandates and ask "would this make sense for a different product?"
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = sorted((ROOT / "mandates").glob("*.md")) + [ROOT / "PROTOCOL.md", ROOT / "CLAUDE.md"]

CHECKS = [
    ("product word", re.compile(
        r"\b(reserv\w*|book(ing|ings|ed|s)?|restaurants?|diners?|tables?|seating|"
        r"opentable|tablekeeper|wallets?|payments?|payers?|payees?|transfers?|"
        r"balances?|venmo|pocketful|ledgers?|money|currenc(y|ies)|cents?|"
        r"time ?zones?|dst)\b", re.I)),
    ("endpoint path", re.compile(r"(^|[\s`'\"(])/[A-Za-z{:]")),
    ("HTTP method + path", re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+/")),
    ("status or error code", re.compile(r"\b[1-5]\d\d\b")),
]


def main() -> int:
    problems = 0
    for path in FILES:
        if not path.exists():
            print(f"missing: {path.relative_to(ROOT)}")
            problems += 1
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for kind, pattern in CHECKS:
                if pattern.search(line):
                    print(f"{path.relative_to(ROOT)}:{lineno}: [{kind}] {line.strip()}")
                    problems += 1
    if problems:
        print(f"\n{problems} suspicious line(s). Make them generic before submitting.")
        return 1
    print(f"OK: {len(FILES)} files checked, nothing track-specific found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
