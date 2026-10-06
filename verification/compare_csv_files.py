#!/usr/bin/env python3
"""Compare two CSVs in the reference metric format (oracle vs served export).

Usage: compare_csv_files.py <reference.csv> <actual.csv>

Rows are keyed by (object_type, path, author); numeric fields allow the
usual tiny float tolerance, string fields must match exactly. Empty fields
are treated as "not applicable" and skipped.
"""
import csv
import sys
from pathlib import Path

NUMERIC = (
    "commit_count", "added", "removed", "growth", "churn", "modifications",
    "modification_frequency", "churn_rate", "ownership",
)
TEXT = ("ref_sha", "commit_set", "repo")


def load(path):
    rows = {}
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows[(row["object_type"], row["path"], row["author"])] = row
    return rows


def main():
    ref = load(sys.argv[1])
    act = load(sys.argv[2])
    missing = sorted(set(ref) - set(act))
    extra = sorted(set(act) - set(ref))
    mismatches = 0

    for key in sorted(set(ref) & set(act)):
        for field in NUMERIC:
            a, b = ref[key][field].strip(), act[key][field].strip()
            if not a or not b:
                continue
            if abs(float(a) - float(b)) > 1e-9:
                mismatches += 1
                if mismatches <= 10:
                    print(f"MISMATCH {key} {field}: ref={a} got={b}")
        for field in TEXT:
            a, b = ref[key][field].strip(), act[key][field].strip()
            if a and b and a != b:
                mismatches += 1
                if mismatches <= 10:
                    print(f"MISMATCH {key} {field}: ref={a} got={b}")

    print(f"reference rows: {len(ref)}  actual rows: {len(act)}")
    print(f"missing: {len(missing)}  extra: {len(extra)}  "
          f"field mismatches: {mismatches}")
    for key in missing[:5]:
        print("  missing:", key)
    for key in extra[:5]:
        print("  extra:  ", key)
    ok = not missing and not extra and not mismatches
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
