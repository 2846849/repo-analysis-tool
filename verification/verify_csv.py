#!/usr/bin/env python3
"""Verify the RAT metric engine against a reference CSV (the oracle).

Usage:
    python verify_csv.py --repo <path-to-clone> --csv <reference.csv>
                         [--dump <out.csv>] [--max-print 40]

The reference CSVs were generated from the current HEAD of each repository,
so ``--repo`` should point at a fresh clone. Every row (object + author
combination) is compared field by field; float fields use a 1e-9 tolerance,
integer fields are exact.

The repository's own ``.mailmap`` is applied by default (the reference data
is canonicalised with it); pass ``--no-mailmap`` to disable.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import git_reader, metrics  # noqa: E402

INT_FIELDS = ["added", "removed", "growth", "churn", "modifications"]
FLOAT_FIELDS = ["modification_frequency", "churn_rate", "ownership"]
ALL_FIELDS = INT_FIELDS + FLOAT_FIELDS


def load_reference(csv_path: Path):
    rows: dict = {}
    meta = {}
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            meta.setdefault("repo", row["repo"])
            meta.setdefault("ref_sha", row["ref_sha"])
            meta.setdefault("commit_count", int(row["commit_count"]))
            key = (row["object_type"], row["path"], row["author"])
            rows[key] = row
    return meta, rows


def compare(meta, expected, history, max_print, mailmap_rules=None):
    size, rows = metrics.export_rows(history, meta["repo"], mailmap_rules)
    got = {(r["object_type"], r["path"], r["author"]): r for r in rows}

    print(f"  engine: ref_sha={history.ref_sha[:12]} "
          f"commits={len(history.commits)} rows={len(got)}")
    if history.ref_sha != meta["ref_sha"]:
        print("  !! WARNING: clone HEAD differs from the CSV ref_sha; "
              "numbers will not match. Re-clone / fetch first.")
    if len(history.commits) != meta["commit_count"]:
        print(f"  !! WARNING: commit count {len(history.commits)} != "
              f"CSV commit_count {meta['commit_count']}")

    missing = [k for k in expected if k not in got]
    extra = [k for k in got if k not in expected]
    common = [k for k in expected if k in got]

    field_issues = []
    for key in common:
        exp, act = expected[key], got[key]
        for field in ALL_FIELDS:
            ev = exp.get(field, "")
            if ev is None or ev == "":
                continue  # field is undefined in the reference
            av = act.get(field)
            if av is None:
                field_issues.append((key, field, ev, av))
                continue
            if field in INT_FIELDS:
                ok = int(ev) == int(av)
            else:
                ok = abs(float(ev) - float(av)) <= 1e-9 * max(1.0, abs(float(ev)))
            if not ok:
                field_issues.append((key, field, ev, av))

    print(f"\n  rows only in CSV   : {len(missing)}")
    print(f"  rows only in engine: {len(extra)}")
    print(f"  field mismatches   : {len(field_issues)} "
          f"({len(common)} common rows compared x {len(ALL_FIELDS)} fields)")

    by_field: dict = {}
    for key, field, ev, av in field_issues:
        by_field[field] = by_field.get(field, 0) + 1
    if by_field:
        print("  mismatches by field:",
              ", ".join(f"{f}={n}" for f, n in sorted(by_field.items())))

    shown = 0
    for key, field, ev, av in field_issues:
        if shown >= max_print:
            break
        print(f"    {key[0]:10s} {key[1]:45s} {key[2]:45s} "
              f"{field}: csv={ev} engine={av}")
        shown += 1
    for k in missing[:max_print]:
        print(f"    MISSING ROW {k}")
    for k in extra[:max_print]:
        print(f"    EXTRA ROW   {k}")

    ok = not (missing or extra or field_issues)
    print(f"\n  RESULT: {'PASS' if ok else 'FAIL'}")
    return ok, (size, rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="path to the cloned repository")
    ap.add_argument("--csv", required=True, help="path to the reference CSV")
    ap.add_argument("--dump", default=None, help="write engine rows to this CSV")
    ap.add_argument("--no-mailmap", action="store_true",
                    help="do not apply the repository's own .mailmap")
    ap.add_argument("--max-print", type=int, default=40)
    args = ap.parse_args()

    meta, expected = load_reference(Path(args.csv))
    print(f"Reference: {args.csv}")
    print(f"  repo={meta['repo']} ref_sha={meta['ref_sha'][:12]} "
          f"rows={len(expected)} commit_count={meta['commit_count']}")

    rules = None
    if not args.no_mailmap:
        rules = git_reader.parse_mailmap(
            git_reader.read_repo_mailmap(args.repo)) or None
    if rules:
        mapped = sum(1 for e in rules.values())
        print(f"  mailmap: {mapped} commit-email entries applied")
    else:
        print("  mailmap: none")

    history = git_reader.load_history(args.repo, "HEAD")
    ok, (size, rows) = compare(meta, expected, history, args.max_print, rules)

    if args.dump:
        with open(args.dump, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(metrics.CSV_COLUMNS)
            for row in rows:
                writer.writerow(["" if row[c] is None else row[c]
                                 for c in metrics.CSV_COLUMNS])
        print(f"  engine rows written to {args.dump}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
