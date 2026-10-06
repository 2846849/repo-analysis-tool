"""Git history extraction built on the git CLI.

The full history of a repository is materialised with a single
``git log --no-merges -M50% --numstat`` invocation so every metric is derived
from one canonical snapshot, following the test brief precisely:

* committer dates (``%ct``) drive all period computations,
* merge commits are excluded from the commit set (``--no-merges``),
* renames are detected at the 50% similarity threshold and any accompanying
  changes are attributed to the *new* path; the *old* path is still
  registered as touched (it is reported with zero metrics if it has no
  history of its own),
* binary file changes are ignored entirely (``-`` numstat rows),
* zero/zero rows (pure renames, mode-only changes, empty files) carry no
  lines; every path they mention is registered as touched.

Touched paths and author identities are interned to integer indices to keep
memory use low for very large histories (100k+ commits), and parsed histories
are cached both in memory and on disk (gzip + pickle) keyed by the resolved
reference SHA.
"""

from __future__ import annotations

import codecs
import gzip
import hashlib
import os
import pickle
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"
CACHE_VERSION = 6

# One record per commit; numstat lines follow each header line.
LOG_FORMAT = "--format=%x1e%H%x1f%an%x1f%ae%x1f%ct%x1f%at%x1f%P%x1f%s"

BACKEND_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BACKEND_DIR / "storage"
CACHE_DIR = STORAGE_DIR / "cache"

_URL_RE = re.compile(
    r"^(https?://|ssh://|git://|ftps?://|[\w.+-]+@[\w.-]+:)", re.IGNORECASE)

_ANGLE_RE = re.compile(r"<([^<>]*)>")


class GitError(RuntimeError):
    """Raised when a git command fails or git is unavailable."""


# ---------------------------------------------------------------------------
# Low level helpers
# ---------------------------------------------------------------------------

def run_git(args, cwd=None, timeout=3600) -> bytes:
    """Run a git command and return raw stdout bytes, raising GitError."""
    cmd = ["git"] + [str(a) for a in args]
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    try:
        proc = subprocess.run(
            cmd,
            cwd=(str(cwd) if cwd else None),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable was not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(
            f"git timed out after {timeout}s: {' '.join(cmd)}") from exc
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip() or "unknown error"
        raise GitError(f"git {' '.join(cmd)} failed: {message}")
    return proc.stdout


def clone_repository(url: str, dest: Path, timeout: int = 3600) -> Path:
    """Deep clone ``url`` into ``dest`` (full history, default branch)."""
    url = (url or "").strip()
    if not url:
        raise GitError("repository URL is empty")
    if not _URL_RE.match(url):
        raise GitError(
            "unsupported repository URL; use http(s)://, ssh://, git:// "
            "or user@host:path")
    dest = Path(dest)
    if dest.exists():
        raise GitError(f"destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_git(["clone", "--quiet", url, str(dest)], timeout=timeout)
    return dest


def extract_zip(zip_path: Path, dest: Path) -> Path:
    """Extract an uploaded archive, guarding against path traversal."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = str(dest.resolve())
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            target = os.path.realpath(os.path.join(dest_resolved, name))
            if target != dest_resolved and not target.startswith(
                    dest_resolved + os.sep):
                raise GitError(f"unsafe path in zip archive: {name}")
        zf.extractall(dest)
    return dest


def _looks_like_git_dir(path: Path) -> bool:
    return (path / "HEAD").is_file() and (path / "objects").is_dir()


def find_repo_root(start: Path, max_depth: int = 4) -> Path:
    """Locate the repository root inside an extracted archive.

    Accepts a work tree containing a ``.git`` directory or file, or a bare
    repository directory. Searches breadth-first up to ``max_depth`` levels
    so archives that wrap the repository in a folder still work.
    """
    start = Path(start).resolve()

    def check(path: Path) -> Path | None:
        if (path / ".git").is_dir() or (path / ".git").is_file():
            return path
        if _looks_like_git_dir(path):
            return path
        return None

    found = check(start)
    if found:
        return found
    queue = [(start, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        try:
            children = sorted(c for c in current.iterdir() if c.is_dir())
        except OSError:
            continue
        for child in children:
            found = check(child)
            if found:
                return found
            queue.append((child, depth + 1))
    raise GitError(
        "no git repository found in the archive (expected a .git directory "
        "or file, or a bare repository). Note: \"Download ZIP\" exports "
        "from GitHub/GitLab contain no .git folder -- clone the repository "
        "URL instead, or re-zip a local clone including its .git directory")


def read_repo_mailmap(repo_root: Path) -> str:
    """Return the repository's own mailmap text, if present."""
    repo_root = Path(repo_root)
    worktree_mailmap = repo_root / ".mailmap"
    if worktree_mailmap.is_file():
        return worktree_mailmap.read_text(encoding="utf-8", errors="replace")
    git_marker = repo_root / ".git"
    if git_marker.is_dir():
        internal = git_marker / "mailmap"
        if internal.is_file():
            return internal.read_text(encoding="utf-8", errors="replace")
    return ""


# ---------------------------------------------------------------------------
# Mailmap handling (mirrors git-shortlog semantics)
# ---------------------------------------------------------------------------

def _parse_nameinfo(segment: str, allow_empty_email: bool):
    """Mirror ``parse_name_and_email`` from git's mailmap.c.

    Extracts one ``Name <email>`` chunk. Returns ``(name_or_None, email)``
    or ``None`` when the chunk carries no usable email.
    """
    left = segment.find("<")
    if left == -1:
        return None
    right = segment.find(">", left + 1)
    if right == -1:
        return None
    email = segment[left + 1:right]
    if not email and not allow_empty_email:
        return None
    return (segment[:left].strip() or None), email


def _add_mailmap_rule(rules, new_name, new_email, old_name, old_email):
    """Mirror ``add_mapping`` from git's mailmap.c.

    With no ``old_email`` this is the simple form and only the name/email
    fields of the entry are updated; otherwise a name-specific sub-entry
    (matched on the commit name as well) is registered.
    """
    if old_email is None:
        old_email = new_email
        new_email = None
    entry = rules.get(old_email.casefold())
    if entry is None:
        entry = {"name": None, "email": None, "namemap": {}}
        rules[old_email.casefold()] = entry
    if old_name is None:
        if new_name:
            entry["name"] = new_name
        if new_email:
            entry["email"] = new_email
    else:
        entry["namemap"][old_name.casefold()] = (new_name, new_email)


def parse_mailmap(text: str) -> dict:
    """Parse mailmap text with git's exact semantics (mailmap.c).

    Returns ``{commit_email_casefolded: entry}`` where each entry is::

        {"name": proper_name_or_None,    # simple form name override
         "email": proper_email_or_None,  # simple form email override
         "namemap": {commit_name_casefolded: (name_or_None, email_or_None)}}

    Supported forms (gitmailmap(5))::

        Proper Name <commit@email>                              (name only)
        <proper@email> <commit@email>                           (email only)
        Proper Name <proper@email> <commit@email>               (both)
        Proper Name <proper@email> Commit Name <commit@email>   (both, if
                                                                 the commit
                                                                 name matches)

    Only a ``#`` as the very first character starts a comment line (this
    mirrors read_mailmap_line in mailmap.c); anything after the second
    ``<...>`` chunk on a line is simply never examined.
    """
    rules: dict = {}
    for raw_line in (text or "").splitlines():
        if raw_line[:1] == "#":
            continue
        line = raw_line.strip()
        if not line:
            continue
        first = _parse_nameinfo(line, allow_empty_email=False)
        if first is None:
            continue
        name1, email1 = first
        name2 = email2 = None
        rest = line[line.find(">") + 1:].strip()
        if rest:
            second = _parse_nameinfo(rest, allow_empty_email=True)
            if second is not None:
                name2, email2 = second
        _add_mailmap_rule(rules, name1, email1, name2, email2)
    return rules


def apply_mailmap(name: str, email: str, rules: dict) -> tuple[str, str]:
    """Apply parsed mailmap rules to one identity (mirrors ``map_user``).

    Matches the commit email case-insensitively; a name-specific entry is
    preferred when it matches the commit name case-insensitively, and the
    simple entry is the fallback otherwise.
    """
    if not rules:
        return name, email
    entry = rules.get((email or "").casefold())
    if entry is None:
        return name, email
    new_name = entry["name"]
    new_email = entry["email"]
    matched = entry["namemap"].get((name or "").casefold())
    if matched is not None:
        new_name, new_email = matched
    if new_name is None and new_email is None:
        return name, email
    return (new_name if new_name is not None else name,
            new_email if new_email is not None else email)


# ---------------------------------------------------------------------------
# Parsing of raw git log output
# ---------------------------------------------------------------------------

def _decode_c_quoted(raw: bytes) -> str:
    """Decode a numstat path that git may have C-quoted."""
    if len(raw) >= 2 and raw.startswith(b'"') and raw.endswith(b'"'):
        try:
            unescaped, _ = codecs.escape_decode(raw[1:-1])
            raw = unescaped
        except Exception:
            raw = raw[1:-1]
    return raw.decode("utf-8", "surrogateescape")


def _collapse_slashes(path: str) -> str:
    """Collapse doubled slashes created by git's compact rename form."""
    while "//" in path:
        path = path.replace("//", "/")
    return path


def split_rename_path(path: str):
    """Split a numstat path into ``(old_path, new_path)``.

    For a rename entry (``old => new`` or the compact ``pre{old => new}suffix``
    form produced by ``git log -M``) the old path is returned alongside the
    new one; for a plain path ``(None, path)`` is returned. Git's compact
    form can join two slashes when one side is empty, e.g.
    ``deps/{build-aux => }/config.guess``.
    """
    if " => " not in path:
        return None, path
    if "{" in path:
        brace_start = path.find("{")
        brace_end = path.find("}", brace_start)
        if brace_end != -1 and " => " in path[brace_start:brace_end]:
            middle = path[brace_start + 1:brace_end]
            old_part, new_part = middle.split(" => ", 1)
            prefix, suffix = path[:brace_start], path[brace_end + 1:]
            return (_collapse_slashes(prefix + old_part + suffix),
                    _collapse_slashes(prefix + new_part + suffix))
    old_path, new_path = path.split(" => ", 1)
    return old_path, new_path


def rename_source_path(path: str) -> str | None:
    """Return the old path of a rename entry, or ``None`` for a plain path."""
    return split_rename_path(path)[0]


def strip_rename_path(path: str) -> str:
    """Extract the *new* path from a numstat rename entry.

    Handles both ``old => new`` and the compact ``pre{old => new}suffix``
    forms produced by ``git log -M``.
    """
    return split_rename_path(path)[1]


class History:
    """Parsed history with interned paths and authors."""

    __slots__ = ("repo_root", "ref", "ref_sha", "paths", "authors", "commits",
                 "_path_index")

    def __init__(self, repo_root, ref, ref_sha, paths, authors, commits):
        self.repo_root = repo_root
        self.ref = ref
        self.ref_sha = ref_sha
        self.paths = paths        # list[str]
        self.authors = authors    # list[str] "Name <email>"
        # commits: list[(sha, author_idx, committer_ts, author_ts, subject,
        #                tuple[(path_idx, added, removed)])]
        self.commits = commits
        self._path_index = {p: i for i, p in enumerate(paths)}

    def path_index(self, path: str):
        return self._path_index.get(path)

    def __getstate__(self):
        return (self.repo_root, self.ref, self.ref_sha,
                self.paths, self.authors, self.commits)

    def __setstate__(self, state):
        (self.repo_root, self.ref, self.ref_sha,
         self.paths, self.authors, self.commits) = state
        self._path_index = {p: i for i, p in enumerate(self.paths)}


def build_history(raw: bytes, repo_root, ref, ref_sha) -> History:
    """Parse the raw byte output of the log command into a History."""
    path_ids: dict = {}
    paths: list = []
    author_ids: dict = {}
    authors: list = []
    commits: list = []

    def path_id(p):
        i = path_ids.get(p)
        if i is None:
            i = len(paths)
            path_ids[p] = i
            paths.append(p)
        return i

    def author_id(a):
        i = author_ids.get(a)
        if i is None:
            i = len(authors)
            author_ids[a] = i
            authors.append(a)
        return i

    sep = RECORD_SEP.encode("ascii")
    fsep = FIELD_SEP.encode("ascii")
    current = None

    for line in raw.split(b"\n"):
        if not line:
            continue
        if line.startswith(sep):
            parts = line[1:].split(fsep, 6)
            if len(parts) != 7:
                continue
            try:
                ct = int(parts[3])
                at = int(parts[4])
            except ValueError:
                continue
            sha = parts[0].decode("ascii", "replace").strip()
            name = parts[1].decode("utf-8", "surrogateescape")
            email = parts[2].decode("utf-8", "surrogateescape")
            subject = parts[6].decode("utf-8", "surrogateescape")
            current = [sha, author_id(f"{name} <{email}>"), ct, at, subject, []]
            commits.append(current)
            continue
        if current is None:
            continue
        tab = line.find(b"\t")
        if tab < 0:
            continue
        tab2 = line.find(b"\t", tab + 1)
        if tab2 < 0:
            continue
        added_raw = line[:tab]
        removed_raw = line[tab + 1:tab2]
        path_raw = line[tab2 + 1:]
        if not (added_raw.isdigit() or added_raw == b"-"):
            continue
        if not (removed_raw.isdigit() or removed_raw == b"-"):
            continue
        if added_raw == b"-" or removed_raw == b"-":
            # binary change: not measured by the brief
            continue
        old_path, path = split_rename_path(_decode_c_quoted(path_raw))
        if old_path is not None:
            # every rename registers both sides; the old path is touched with
            # no lines of its own (zero row when it has no other history)
            path_id(old_path)
        if added_raw == b"0" and removed_raw == b"0":
            # pure rename / mode change / empty file: the path is registered
            # (and reported with zero metrics) but contributes no lines
            path_id(path)
            continue
        current[5].append((path_id(path), int(added_raw), int(removed_raw)))

    frozen = [
        (sha, aid, ct, at, subject, tuple(files))
        for sha, aid, ct, at, subject, files in commits
    ]
    return History(repo_root, ref, ref_sha, paths, authors, frozen)


# ---------------------------------------------------------------------------
# Loading with caching
# ---------------------------------------------------------------------------

_MEM_CACHE: dict = {}


def resolve_ref(repo_root, ref: str = "HEAD") -> tuple[str, str]:
    """Resolve a reference (branch, tag, SHA, HEAD) to a commit SHA."""
    ref = (ref or "HEAD").strip() or "HEAD"
    try:
        out = run_git(["-C", str(repo_root), "rev-parse", "--verify",
                       f"{ref}^{{commit}}"], timeout=120)
    except GitError as exc:
        raise GitError(f"cannot resolve reference '{ref}'") from exc
    return out.decode("ascii", "replace").strip(), ref


def _cache_dir(repo_root: str) -> Path:
    digest = hashlib.sha256(
        repo_root.encode("utf-8", "surrogateescape")).hexdigest()[:16]
    return CACHE_DIR / digest


def _load_disk_cache(repo_root: str, ref_sha: str):
    path = _cache_dir(repo_root) / f"{ref_sha}.hist.gz"
    if not path.is_file():
        return None
    try:
        with gzip.open(path, "rb") as fh:
            blob = pickle.load(fh)
        if not isinstance(blob, dict) or blob.get("version") != CACHE_VERSION:
            return None
        return History(blob["repo_root"], blob["ref"], blob["ref_sha"],
                       blob["paths"], blob["authors"], blob["commits"])
    except Exception:
        return None


def _save_disk_cache(repo_root: str, ref_sha: str, history: History) -> None:
    path = _cache_dir(repo_root) / f"{ref_sha}.hist.gz"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        blob = {
            "version": CACHE_VERSION,
            "repo_root": history.repo_root,
            "ref": history.ref,
            "ref_sha": history.ref_sha,
            "paths": history.paths,
            "authors": history.authors,
            "commits": history.commits,
        }
        with gzip.open(tmp, "wb") as fh:
            pickle.dump(blob, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
    except Exception:
        pass


def _subset_history(repo_root: str, ref_sha: str):
    """Derive a History for an ancestor ref from the cached HEAD history.

    When the requested reference is reachable from HEAD (the common case for
    a chosen commit/branch/tag), the full parse can be reused and filtered by
    the reachable set instead of running the expensive log again.
    """
    try:
        head_sha = run_git(["-C", repo_root, "rev-parse", "HEAD"],
                           timeout=60).decode("ascii", "replace").strip()
    except GitError:
        return None
    if head_sha == ref_sha:
        return None
    base = _MEM_CACHE.get((repo_root, head_sha)) or _load_disk_cache(
        repo_root, head_sha)
    if base is None:
        return None
    try:
        out = run_git(["-C", repo_root, "rev-list", "--no-merges", ref_sha],
                      timeout=900)
    except GitError:
        return None
    wanted = set(out.decode("ascii", "replace").split())
    have = {c[0] for c in base.commits}
    if len(wanted) != len(have) or not wanted <= have:
        return None
    commits = [c for c in base.commits if c[0] in wanted]
    return History(base.repo_root, ref_sha, ref_sha,
                   base.paths, base.authors, commits)


def load_history(repo_root, ref: str = "HEAD", use_cache: bool = True) -> History:
    """Parse (or fetch from cache) the history reachable from ``ref``."""
    repo_root = str(Path(repo_root).resolve())
    ref_sha, ref_label = resolve_ref(repo_root, ref)

    key = (repo_root, ref_sha)
    if use_cache and key in _MEM_CACHE:
        _MEM_CACHE[key].ref = ref_label
        return _MEM_CACHE[key]

    history = None
    if use_cache:
        history = _load_disk_cache(repo_root, ref_sha)
        if history is None:
            history = _subset_history(repo_root, ref_sha)

    if history is None:
        out = run_git([
            "-C", repo_root,
            "-c", "core.quotePath=false",
            "log", ref_sha, "--no-merges", "-M50%", "--numstat",
            LOG_FORMAT,
        ], timeout=7200)
        history = build_history(out, repo_root, ref_label, ref_sha)
        if use_cache:
            _save_disk_cache(repo_root, ref_sha, history)

    history.ref = ref_label
    if use_cache:
        _MEM_CACHE[key] = history
    return history


def clear_caches(repo_root) -> None:
    """Forget cached histories for a repository (used when it is deleted)."""
    repo_root = str(Path(repo_root).resolve())
    for key in [k for k in _MEM_CACHE if k[0] == repo_root]:
        _MEM_CACHE.pop(key, None)
    shutil.rmtree(_cache_dir(repo_root), ignore_errors=True)
