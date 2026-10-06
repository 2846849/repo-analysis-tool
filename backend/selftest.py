#!/usr/bin/env python3
"""Self-test: hand-computed metric expectations on a scratch repository.

Builds a small repository with deterministic committer dates and asserts the
exact values produced by the metric engine, exercising:

* committer-date semantics (author date intentionally different on c1),
* merge commits excluded from the commit set,
* pure rename = no metric change, rename+modify attributed to the new path,
* binary files not measured, deleted file lines recorded on their path,
* modifications / frequency / churn rate / ownership,
* single-commit sets (exact per-commit metrics),
* author filter, period filter (half-open), path filter (file + directory),
* mailmap merging cross-checked against ``git check-mailmap``.

Run:  python selftest.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import git_reader, metrics  # noqa: E402

ALICE = ("Alice Smith", "alice@x.com")
BOB = ("Bob Builder", "bob@x.com")
CAROL = ("Carol Jones", "carol@x.com")
BOB_OLD = ("Bob B", "bob@old.com")

FAILURES: list = []


def ts(day: int, hour: int = 10) -> int:
    return int(datetime(2024, 1, day, hour, 0, 0,
                        tzinfo=timezone.utc).timestamp())


def git(repo: Path, *args, env=None) -> str:
    full_env = os.environ.copy()
    full_env.update(env or {})
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, env=full_env)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def commit(repo: Path, identity, day: int, message: str,
           author_date: int | None = None) -> None:
    name, email = identity
    when = f"@{ts(day)} +0000"
    author_when = f"@{author_date} +0000" if author_date else when
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message, env={
        "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": author_when, "GIT_COMMITTER_DATE": when,
    })


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_repo(base: Path) -> Path:
    repo = base / "scratch"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@x.com")

    # c1 (Alice, committer Jan 1 / author Dec 25): a.txt +5, docs/b.txt +3,
    # binary docs/img.png, README.md +2
    write(repo, "a.txt", "l1\nl2\nl3\nl4\nl5\n")
    write(repo, "docs/b.txt", "b1\nb2\nb3\n")
    (repo / "docs" / "img.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00binary\x00data\x00\x00")
    write(repo, "README.md", "title\nbody\n")
    commit(repo, ALICE, 1, "c1: initial", author_date=ts(25) - 8 * 86400)

    # c2 (Alice, Jan 2): a.txt +2/-1, docs/b.txt +1/-1
    write(repo, "a.txt", "l1-changed\nl2\nl3\nl4\nl5\nl6\n")
    write(repo, "docs/b.txt", "b1\nb2-changed\nb3\nb4\n")
    commit(repo, ALICE, 2, "c2: edits")

    # c3 (Bob, Jan3): a.txt +1/-1, new a2.txt (+10)
    write(repo, "a.txt", "l1-changed\nl2\nl3\nl4-edited\nl5\nl6\n")
    write(repo, "a2.txt", "x1\nx2\nx3\nx4\nx5\nx6\nx7\nx8\nx9\nx10\n")
    commit(repo, BOB, 3, "c3: bob work")
    side_ref = git(repo, "rev-parse", "HEAD")

    # c4 (Carol, Jan 4): pure rename docs/b.txt -> docs2/b.txt
    (repo / "docs2").mkdir()
    git(repo, "mv", "docs/b.txt", "docs2/b.txt")
    commit(repo, CAROL, 4, "c4: pure rename")

    # c5 (Bob, Jan 5): docs2/b.txt +2/-2
    write(repo, "docs2/b.txt", "b1\nb2-changed\nb3-changed\nb4-changed\n")
    commit(repo, BOB, 5, "c5: edit moved file")

    # c6 (Carol, Jan6): rename a2.txt -> a2r.txt with +1/-1 edit (the file
    # is large enough for git's 50% similarity rename detection)
    git(repo, "mv", "a2.txt", "a2r.txt")
    write(repo, "a2r.txt", "x1\nx2\nx3-edited\nx4\nx5\nx6\nx7\nx8\nx9\nx10\n")
    commit(repo, CAROL, 6, "c6: rename with edit")

    # c7 (Bob B <bob@old.com>, Jan 7): delete README.md
    git(repo, "rm", "-q", "README.md")
    commit(repo, BOB_OLD, 7, "c7: drop readme")

    # c8: merge commit (excluded from H) via commit-tree with identical tree
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    head = git(repo, "rev-parse", "HEAD")
    env = {
        "GIT_AUTHOR_NAME": ALICE[0], "GIT_AUTHOR_EMAIL": ALICE[1],
        "GIT_COMMITTER_NAME": ALICE[0], "GIT_COMMITTER_EMAIL": ALICE[1],
        "GIT_AUTHOR_DATE": f"@{ts(8)} +0000",
        "GIT_COMMITTER_DATE": f"@{ts(8)} +0000",
    }
    merge_sha = git(repo, "commit-tree", tree, "-p", head, "-p",
                    side_ref, "-m", "c8: merge side", env=env).splitlines()[0]
    git(repo, "update-ref", "refs/heads/master", merge_sha)
    git(repo, "checkout", "-q", "master")
    return repo


def expect(label: str, actual, wanted, tolerance: float = 1e-9) -> None:
    ok = False
    if isinstance(wanted, float):
        ok = abs(float(actual) - wanted) <= tolerance
    else:
        ok = actual == wanted
    status = "ok " if ok else "FAIL"
    print(f"  [{status}] {label}: got={actual!r} want={wanted!r}")
    if not ok:
        FAILURES.append(label)


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="rat-selftest-"))
    try:
        repo = build_repo(base)
        print(f"scratch repo: {repo}")

        # -- write a mailmap used later ----------------------------------
        repo_mailmap = "Bob Builder <bob@x.com> <bob@old.com>\n"
        (repo / ".mailmap").write_text(repo_mailmap, encoding="utf-8")
        git(repo, "add", ".mailmap",
            env={"GIT_AUTHOR_DATE": f"@{ts(8)} +0000",
                 "GIT_COMMITTER_DATE": f"@{ts(8)} +0000"})
        # NOTE: do not commit it; the worktree file is what loaders read.

        history = git_reader.load_history(repo, "HEAD")
        print(f"\ncommit set: {len(history.commits)} commits "
              f"(ref_sha={history.ref_sha[:10]})")
        expect("H size (merges excluded)", len(history.commits), 7)

        rules = git_reader.parse_mailmap(repo_mailmap)

        # -- no filters ---------------------------------------------------
        print("\n-- no filters --")
        a = metrics.analyze(history, None, None)
        rm = a["repository"]["metrics"]
        expect("repo added", rm["added"], 28)
        expect("repo removed", rm["removed"], 8)
        expect("repo growth", rm["growth"], 20)
        expect("repo churn", rm["churn"], 36)
        expect("repo modifications", rm["modifications"], 6)
        expect("repo frequency", rm["modification_frequency"], 6 / 7)
        expect("repo churn_rate", rm["churn_rate"], 36 / 7)
        expect("commit_set size", a["commit_set"]["size"], 7)
        expect("files", a["repository"]["files"], 6)
        expect("directories", a["repository"]["directories"], 2)
        expect("first commit (committer date)",
               a["commit_set"]["first_commit_at"], "2024-01-01T10:00:00Z")

        files = {row["path"]: row["metrics"] for row in a["files"]}
        expect("a.txt added", files["a.txt"]["added"], 8)
        expect("a.txt removed", files["a.txt"]["removed"], 2)
        expect("a.txt modifications", files["a.txt"]["modifications"], 3)
        expect("a2.txt added (pre-rename stays)", files["a2.txt"]["added"], 10)
        expect("a2r.txt churn (rename+edit on new path)",
               files["a2r.txt"]["churn"], 2)
        expect("a2r.txt modifications", files["a2r.txt"]["modifications"], 1)
        expect("docs/b.txt added", files["docs/b.txt"]["added"], 5)
        expect("docs/b.txt removed", files["docs/b.txt"]["removed"], 1)
        expect("docs/b.txt churn", files["docs/b.txt"]["churn"], 6)
        expect("docs2/b.txt churn", files["docs2/b.txt"]["churn"], 4)
        expect("README.md churn (delete)", files["README.md"]["churn"], 4)
        expect("binary not measured", "docs/img.png" in files, False)

        authors = {row["author"]: row for row in a["authors"]}
        expect("Alice churn", authors["Alice Smith <alice@x.com>"]["churn"], 16)
        expect("Alice modifications",
               authors["Alice Smith <alice@x.com>"]["modifications"], 2)
        expect("Bob churn", authors["Bob Builder <bob@x.com>"]["churn"], 16)
        expect("Bob modifications",
               authors["Bob Builder <bob@x.com>"]["modifications"], 2)
        expect("Carol churn", authors["Carol Jones <carol@x.com>"]["churn"], 2)
        expect("Carol modifications (rename commit excluded)",
               authors["Carol Jones <carol@x.com>"]["modifications"], 1)
        expect("Carol commits (rename commit counted)",
               authors["Carol Jones <carol@x.com>"]["commits"], 2)
        expect("ownership Alice",
               authors["Alice Smith <alice@x.com>"]["ownership"], 16 / 36)

        # -- single commit (c2) --------------------------------------------
        print("\n-- single commit c2 --")
        c2 = next(c for c in history.commits if c[4] == "c2: edits")
        b = metrics.analyze(history, None, None, hashes=[c2[0]])
        bm = b["repository"]["metrics"]
        expect("size", b["commit_set"]["size"], 1)
        expect("added", bm["added"], 4)
        expect("removed", bm["removed"], 2)
        expect("churn", bm["churn"], 6)
        expect("modifications", bm["modifications"], 1)
        expect("frequency", bm["modification_frequency"], 1.0)
        expect("churn_rate", bm["churn_rate"], 6.0)
        bfiles = {row["path"]: row["metrics"] for row in b["files"]}
        expect("a.txt added", bfiles["a.txt"]["added"], 2)
        expect("a.txt removed", bfiles["a.txt"]["removed"], 1)

        # -- author filter ---------------------------------------------------
        print("\n-- author filter (Bob) --")
        c = metrics.analyze(history, None, None,
                            author="Bob Builder <bob@x.com>")
        cm = c["repository"]["metrics"]
        expect("size stays |H|", c["commit_set"]["size"], 7)
        expect("author commits", c["commit_set"]["author_commits"], 2)
        expect("added", cm["added"], 13)
        expect("removed", cm["removed"], 3)
        expect("churn", cm["churn"], 16)
        expect("modifications", cm["modifications"], 2)

        # -- period filter [Jan 3, Jan 5) -------------------------------------
        print("\n-- period [Jan3 00:00, Jan5 00:00) --")
        d = metrics.analyze(history, None, None,
                            since_ts=ts(3, 0), until_ts=ts(5, 0))
        dm = d["repository"]["metrics"]
        expect("size", d["commit_set"]["size"], 2)
        expect("added", dm["added"], 11)
        expect("removed", dm["removed"], 1)
        expect("churn", dm["churn"], 12)
        expect("modifications", dm["modifications"], 1)

        # -- path filters -----------------------------------------------------
        print("\n-- path filter --")
        e = metrics.analyze(history, None, None, path="a.txt")
        expect("a.txt churn", e["object"]["metrics"]["churn"], 10)
        expect("a.txt modifications", e["object"]["metrics"]["modifications"], 3)
        f = metrics.analyze(history, None, None, path="docs")
        expect("docs dir churn", f["object"]["metrics"]["churn"], 6)
        expect("docs dir files", len(f["files"]), 1)
        g = metrics.analyze(history, None, None, path="docs2")
        expect("docs2 dir churn", g["object"]["metrics"]["churn"], 4)

        # -- mailmap ----------------------------------------------------------
        print("\n-- mailmap --")
        h = metrics.analyze(history, rules, None)
        hauthors = {row["author"]: row for row in h["authors"]}
        expect("Bob merged churn",
               hauthors["Bob Builder <bob@x.com>"]["churn"], 18)
        expect("Bob B gone", "Bob B <bob@old.com>" in hauthors, False)

        name, email = git_reader.apply_mailmap("Bob B", "bob@old.com", rules)
        proc = subprocess.run(
            ["git", "-C", str(repo), "check-mailmap",
             "Bob B <bob@old.com>", "BOB B <BOB@OLD.COM>"],
            capture_output=True, text=True)
        checked = proc.stdout.splitlines()
        expect("apply_mailmap == git check-mailmap",
               f"{name} <{email}>",
               checked[0] if checked
               else f"<rc={proc.returncode}: {proc.stderr.strip()}>")
        expect("mailmap match is case-insensitive",
               checked[1] if len(checked) > 1 else None,
               "Bob Builder <bob@x.com>")

        # -- rename path parsing edge cases -----------------------------------
        print("\n-- rename path parsing --")
        expect("plain rename",
               git_reader.strip_rename_path("old/name.c => new/name.c"),
               "new/name.c")
        expect("brace rename",
               git_reader.strip_rename_path("f/{a.cc => a.c}"),
               "f/a.c")
        expect("empty new part collapses slash",
               git_reader.strip_rename_path("deps/{sub => }/file.c"),
               "deps/file.c")
        expect("rename source plain",
               git_reader.rename_source_path("old/name.c => new/name.c"),
               "old/name.c")
        expect("rename source brace",
               git_reader.rename_source_path("f/{a.cc => a.c}"),
               "f/a.cc")
        expect("empty old part collapses slash",
               git_reader.rename_source_path("deps/{ => sub}/file.c"),
               "deps/file.c")
        expect("non-rename has no source",
               git_reader.rename_source_path("plain/path.c"), None)

        print("\n" + "=" * 60)
        if FAILURES:
            print(f"FAILED: {len(FAILURES)} expectation(s): {FAILURES}")
            return 1
        print("ALL SELF-TEST EXPECTATIONS PASSED")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
