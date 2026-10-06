#!/usr/bin/env python3
"""Cross-check the pure-Python mailmap implementation against git itself.

Every distinct raw author identity of a repository is fed to
``git check-mailmap --stdin`` (git's own mailmap semantics, reading the
repository's ``.mailmap``), and the result is compared with
``git_reader.apply_mailmap`` applied to ``git_reader.parse_mailmap`` output.

Usage:
    python check_mailmap.py [--repo verification/clones/git] [--max-print 40]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import git_reader, metrics  # noqa: E402


def parse_identity(text: str):
    """Split a ``Name <email>`` string (mirrors metric identity parsing)."""
    return metrics.split_identity(text.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo",
                    default=str(ROOT / "verification" / "clones" / "git"))
    ap.add_argument("--max-print", type=int, default=40)
    args = ap.parse_args()
    repo = Path(args.repo)

    history = git_reader.load_history(repo, "HEAD")
    identities = sorted(set(history.authors))
    text = git_reader.read_repo_mailmap(repo)
    rules = git_reader.parse_mailmap(text)
    print(f"repo: {repo}")
    print(f"distinct identities: {len(identities)}  "
          f"parsed mailmap entries: {len(rules)}")

    contacts = []
    skipped = []
    for ident in identities:
        name, email = parse_identity(ident)
        if not email or "<" in name or ">" in name or "<" in email or ">" in email:
            skipped.append(ident)
            continue
        contacts.append((ident, name, email))
    print(f"fed to check-mailmap: {len(contacts)}  "
          f"skipped (empty/odd email or name): {len(skipped)}")
    for ident in skipped[:10]:
        print(f"  skip: {ident!r}")

    proc = subprocess.run(
        ["git", "-C", str(repo), "check-mailmap", "--stdin"],
        input="".join(f"{name} <{email}>\n" for _, name, email in contacts)
        .encode("utf-8", "surrogateescape"),
        capture_output=True)
    if proc.returncode != 0:
        print("!! git check-mailmap failed:",
              proc.stderr.decode("utf-8", "replace").strip())
        return 2
    lines = proc.stdout.decode("utf-8", "surrogateescape").splitlines()
    if len(lines) != len(contacts):
        print(f"!! expected {len(contacts)} output lines, got {len(lines)}")
        return 2

    bad = 0
    changed = 0
    for (ident, name, email), out in zip(contacts, lines):
        exp = parse_identity(out)
        got = git_reader.apply_mailmap(name, email, rules)
        if exp != (name, email):
            changed += 1
        if got != exp:
            bad += 1
            if bad <= args.max_print:
                print(f"  MISMATCH {ident!r}\n"
                      f"    ours: {got[0]!r} {got[1]!r}\n"
                      f"    git : {exp[0]!r} {exp[1]!r}")

    print(f"\nidentities rewritten by git: {changed}")
    print(f"mismatches: {bad}")
    print("RESULT:", "PASS" if bad == 0 else "FAIL")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
