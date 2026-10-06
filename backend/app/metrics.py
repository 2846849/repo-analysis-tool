"""Metric computation over an extracted git history.

Definitions implemented here (all over the selected commit set H, following
the brief exactly):

* ``l+(h,o)`` / ``l-(h,o)``: lines added / removed on object ``o`` in commit
  ``h``; ``growth = l+ - l-``; ``churn = l+ + l-``.
* object modifications ``n(H,o)`` = number of commits in H with churn > 0;
  modification frequency ``eta = n / |H|``; churn rate ``rho = churn / |H|``.
* author contributions ``lambda(H,o,a) = sum over commits of a``;
  authorship count ``n(H,o,a)``; ownership ``omega = lambda / lambda(H,o)``.
* repository metrics are exactly the directory metrics of the root.
* directories aggregate recursively over all descendant files.

The whole analysis is a single pass over the selected commits, keeping
integer accumulators per path / directory / author, so it stays fast even
for 100k+ commit histories.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .git_reader import apply_mailmap


class MetricsError(ValueError):
    """Invalid filter combination requested by the caller."""


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------

def canonical_key(name: str, email: str) -> str:
    return f"{(name or '').strip()} <{(email or '').strip()}>"


def split_identity(identity: str) -> tuple[str, str]:
    identity = (identity or "").strip()
    pos = identity.rfind(" <")
    if pos == -1:
        return identity, ""
    return identity[:pos], identity[pos + 2:].rstrip(">")


def build_merge_map(merges) -> dict:
    """Manual merges: {(alias_name, alias_email): (canonical_name, canonical_email)}."""
    mapping = {}
    for m in merges or []:
        key = (m["alias_name"].strip(), m["alias_email"].strip())
        mapping[key] = (m["canonical_name"].strip(), m["canonical_email"].strip())
    return mapping


def resolve_author(name: str, email: str, mailmap_rules=None,
                   merge_map=None) -> str:
    """Resolve one identity to its canonical ``Name <email>`` form.

    The repository mailmap is applied first, then any manual merges keyed on
    the mailmapped identity.
    """
    if mailmap_rules:
        name, email = apply_mailmap(name, email, mailmap_rules)
    if merge_map:
        target = merge_map.get((name, email))
        if target:
            name, email = target
    return canonical_key(name, email)


def _resolve_all(history, mailmap_rules=None, merge_map=None) -> list:
    resolved = []
    for identity in history.authors:
        name, email = split_identity(identity)
        resolved.append(resolve_author(name, email, mailmap_rules, merge_map))
    return resolved


def list_author_identities(history, mailmap_rules=None, merge_map=None) -> list:
    """Raw identities with commit counts plus their effective canonical form."""
    counts: dict = {}
    for commit in history.commits:
        counts[commit[1]] = counts.get(commit[1], 0) + 1

    rows = []
    for idx, raw in enumerate(history.authors):
        name, email = split_identity(raw)
        mm_name, mm_email = (apply_mailmap(name, email, mailmap_rules)
                             if mailmap_rules else (name, email))
        final = (mm_name, mm_email)
        if merge_map:
            final = merge_map.get((mm_name, mm_email), final)
        rows.append({
            "raw": raw,
            "name": name,
            "email": email,
            "commits": counts.get(idx, 0),
            "mailmapped": (mm_name, mm_email) != (name, email),
            "manually_merged": final != (mm_name, mm_email),
            "effective_name": final[0],
            "effective_email": final[1],
            "resolved": canonical_key(*final),
        })
    rows.sort(key=lambda r: (-r["commits"], r["raw"].lower()))
    return rows


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def iso_utc(ts) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _bucket_start(ts: int, mode: str) -> int:
    if mode == "day":
        return ts - (ts % 86400)
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if mode == "week":
        day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        monday = day - timedelta(days=day.weekday())
        return int(monday.timestamp())
    first = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(first.timestamp())


# ---------------------------------------------------------------------------
# Commit selection
# ---------------------------------------------------------------------------

def resolve_hashes(history, hashes) -> tuple[set, list]:
    """Resolve full or unambiguous abbreviated SHAs; returns (found, missing)."""
    have = {c[0] for c in history.commits}
    found: set = set()
    missing: list = []
    prefix_map = None
    for raw in hashes or []:
        token = (raw or "").strip().lower()
        if not token:
            continue
        if token in have:
            found.add(token)
            continue
        if len(token) >= 4:
            if prefix_map is None:
                prefix_map = {}
                for sha in have:
                    prefix_map.setdefault(sha[:10], []).append(sha)
            matches = [s for s in prefix_map.get(token[:10], [])
                       if s.startswith(token)]
            if len(matches) == 1:
                found.add(matches[0])
                continue
        missing.append(raw)
    return found, missing


def select_commits(history, since_ts=None, until_ts=None, hashes=None):
    """Return the commit list for H (newest first, as git log produced it)."""
    if hashes:
        wanted, _ = resolve_hashes(history, hashes)
        return [c for c in history.commits if c[0] in wanted]
    selected = []
    for commit in history.commits:
        ct = commit[2]
        if since_ts is not None and ct < since_ts:
            continue
        if until_ts is not None and ct >= until_ts:
            continue
        selected.append(commit)
    return selected


# ---------------------------------------------------------------------------
# Directory bookkeeping
# ---------------------------------------------------------------------------

def _build_dir_lookup(paths):
    """Return (chains, dir_names, dir_index).

    ``chains[pid]`` is the tuple of ancestor directory ids for a file path,
    deepest first, always ending with the root id 0 (name "").
    """
    dir_index: dict = {"": 0}
    dir_names: list = [""]

    def did(name: str) -> int:
        i = dir_index.get(name)
        if i is None:
            i = len(dir_names)
            dir_index[name] = i
            dir_names.append(name)
        return i

    chains = []
    for path in paths:
        chain = []
        idx = path.rfind("/")
        while idx >= 0:
            chain.append(did(path[:idx]))
            idx = path.rfind("/", 0, idx)
        chain.append(0)
        chains.append(tuple(chain))
    return chains, dir_names, dir_index


def _under_scope(scope_file: int | None, scope_dir: int | None,
                 pid: int, chains) -> bool:
    if scope_file is not None:
        return pid == scope_file
    if scope_dir is not None:
        return scope_dir in chains[pid]
    return True


# ---------------------------------------------------------------------------
# The single-pass aggregation
# ---------------------------------------------------------------------------

def _aggregate(history, commits, resolved_by_raw, author_key=None,
               scope_file=None, scope_dir=None):
    chains, dir_names, _ = _build_dir_lookup(history.paths)
    n_paths = len(history.paths)
    n_dirs = len(dir_names)

    fa_add = [0] * n_paths
    fa_rem = [0] * n_paths
    fa_mods = [0] * n_paths
    fa_last = [0] * n_paths
    fa_auth: dict = {}

    da_add = [0] * n_dirs
    da_rem = [0] * n_dirs
    da_mods = [0] * n_dirs
    da_last = [0] * n_dirs
    da_auth: dict = {}
    da_auth_mods: dict = {}

    au_add: dict = {}
    au_rem: dict = {}
    au_mods: dict = {}
    au_commits: dict = {}

    activity_points = []
    repo_mods = 0
    size = 0
    first_ts = None
    last_ts = None

    for sha, raw_aid, ct, at, subject, files in commits:
        size += 1
        if first_ts is None or ct < first_ts:
            first_ts = ct
        if last_ts is None or ct > last_ts:
            last_ts = ct

        akey = resolved_by_raw[raw_aid]
        if author_key is not None and akey != author_key:
            continue

        au_commits[akey] = au_commits.get(akey, 0) + 1

        commit_add = 0
        commit_rem = 0
        scoped_churn = 0
        dirs_churn: dict = {}

        for pid, added, removed in files:
            lam = added + removed
            if lam == 0:
                continue
            fa_add[pid] += added
            fa_rem[pid] += removed
            fa_mods[pid] += 1
            if ct > fa_last[pid]:
                fa_last[pid] = ct

            key = (pid, akey)
            row = fa_auth.get(key)
            if row is None:
                row = [0, 0, 0]
                fa_auth[key] = row
            row[0] += added
            row[1] += removed
            row[2] += 1

            commit_add += added
            commit_rem += removed

            if _under_scope(scope_file, scope_dir, pid, chains):
                scoped_churn += lam

            for did in chains[pid]:
                da_add[did] += added
                da_rem[did] += removed
                if ct > da_last[did]:
                    da_last[did] = ct
                dkey = (did, akey)
                drow = da_auth.get(dkey)
                if drow is None:
                    drow = [0, 0]
                    da_auth[dkey] = drow
                drow[0] += added
                drow[1] += removed
                dirs_churn[did] = dirs_churn.get(did, 0) + lam

        for did, churn in dirs_churn.items():
            if churn > 0:
                da_mods[did] += 1
                mkey = (did, akey)
                da_auth_mods[mkey] = da_auth_mods.get(mkey, 0) + 1

        total_commit_churn = commit_add + commit_rem
        if total_commit_churn > 0:
            repo_mods += 1
            au_mods[akey] = au_mods.get(akey, 0) + 1
        au_add[akey] = au_add.get(akey, 0) + commit_add
        au_rem[akey] = au_rem.get(akey, 0) + commit_rem

        activity_points.append((ct, scoped_churn))

    return {
        "size": size,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "fa_add": fa_add, "fa_rem": fa_rem, "fa_mods": fa_mods,
        "fa_last": fa_last, "fa_auth": fa_auth,
        "da_add": da_add, "da_rem": da_rem, "da_mods": da_mods,
        "da_last": da_last, "da_auth": da_auth, "da_auth_mods": da_auth_mods,
        "au_add": au_add, "au_rem": au_rem, "au_mods": au_mods,
        "au_commits": au_commits,
        "repo_mods": repo_mods,
        "activity_points": activity_points,
        "chains": chains,
        "dir_names": dir_names,
    }


def _metrics(added: int, removed: int, mods: int, size: int) -> dict:
    churn = added + removed
    return {
        "added": added,
        "removed": removed,
        "growth": added - removed,
        "churn": churn,
        "modifications": mods,
        "modification_frequency": (mods / size) if size else 0.0,
        "churn_rate": (churn / size) if size else 0.0,
    }


def _activity_points_list(points, first_ts, last_ts):
    if not points:
        return "day", []
    span = (last_ts or 0) - (first_ts or 0)
    if span > 2 * 365 * 86400:
        mode = "month"
    elif span > 120 * 86400:
        mode = "week"
    else:
        mode = "day"
    buckets: dict = {}
    for ct, churn in points:
        start = _bucket_start(ct, mode)
        entry = buckets.get(start)
        if entry is None:
            entry = [0, 0]
            buckets[start] = entry
        entry[0] += 1
        entry[1] += churn
    out = [
        {"start": start, "date": iso_utc(start),
         "commits": value[0], "churn": value[1]}
        for start, value in sorted(buckets.items())
    ]
    return mode, out


# ---------------------------------------------------------------------------
# Public analysis entry point
# ---------------------------------------------------------------------------

def _normalize_path(path) -> str:
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.strip("/")
    return p


def analyze(history, mailmap_rules=None, merge_map=None,
            since_ts=None, until_ts=None, hashes=None,
            author=None, path=None, top: int = 250) -> dict:
    """Run the full analysis for one repository and filter combination."""
    resolved_by_raw = _resolve_all(history, mailmap_rules, merge_map)

    author_key = None
    if author:
        author_key = author.strip()
        if author_key not in set(resolved_by_raw):
            raise MetricsError(
                f"author '{author_key}' does not appear in this repository's "
                "commits (after mailmap / manual merges)")

    commits = select_commits(history, since_ts=since_ts, until_ts=until_ts,
                             hashes=hashes)
    missing_hashes: list = []
    if hashes:
        _, missing_hashes = resolve_hashes(history, hashes)

    norm_path = _normalize_path(path)
    chains, dir_names, dir_index = _build_dir_lookup(history.paths)
    scope_file = None
    scope_dir = None
    if norm_path:
        pid = history.path_index(norm_path)
        if pid is not None:
            scope_file = pid
        else:
            did = dir_index.get(norm_path)
            if did is None or did == 0:
                raise MetricsError(
                    f"path '{norm_path}' was not touched anywhere in the "
                    "analyzed history")
            scope_dir = did

    agg = _aggregate(history, commits, resolved_by_raw,
                     author_key=author_key,
                     scope_file=scope_file, scope_dir=scope_dir)

    size = agg["size"]
    fa_add, fa_rem, fa_mods, fa_last = (agg["fa_add"], agg["fa_rem"],
                                        agg["fa_mods"], agg["fa_last"])
    da_add, da_rem, da_mods, da_last = (agg["da_add"], agg["da_rem"],
                                        agg["da_mods"], agg["da_last"])
    au_add, au_rem = agg["au_add"], agg["au_rem"]

    # -- repository (root directory) ------------------------------------
    root_metrics = _metrics(da_add[0], da_rem[0], da_mods[0], size)
    repo_authors = sum(1 for akey, churn in (
        (k, au_add[k] + au_rem[k]) for k in au_add) if churn > 0)
    file_count = sum(1 for pid in range(len(history.paths))
                     if fa_add[pid] + fa_rem[pid] > 0)
    dir_count = sum(1 for did in range(1, len(dir_names))
                    if da_add[did] + da_rem[did] > 0)

    # -- author rows helper ---------------------------------------------
    def author_rows_for_repo():
        rows = []
        for akey in au_add:
            churn_a = au_add[akey] + au_rem[akey]
            if churn_a <= 0 and author_key is None:
                continue
            ownership = (churn_a / root_metrics["churn"]
                         if root_metrics["churn"] else 0.0)
            rows.append({
                "author": akey,
                "added": au_add[akey],
                "removed": au_rem[akey],
                "growth": au_add[akey] - au_rem[akey],
                "churn": churn_a,
                "modifications": agg["au_mods"].get(akey, 0),
                "commits": agg["au_commits"].get(akey, 0),
                "ownership": ownership,
            })
        rows.sort(key=lambda r: -r["churn"])
        return rows

    repository = {
        "metrics": root_metrics,
        "authors": repo_authors,
        "files": file_count,
        "directories": dir_count,
        "distinct_authors_total": len(set(resolved_by_raw)),
        "author_rows": author_rows_for_repo(),
    }

    # -- selected object --------------------------------------------------
    object_payload = None
    if not norm_path:
        object_payload = {
            "kind": "repository",
            "path": "/",
            "metrics": root_metrics,
            "authors": author_rows_for_repo(),
            "last_change": iso_utc(da_last[0] or None),
        }
    elif scope_file is not None:
        pid = scope_file
        metrics = _metrics(fa_add[pid], fa_rem[pid], fa_mods[pid], size)
        churn_o = metrics["churn"]
        rows = []
        for (apid, akey), (a, r, m) in agg["fa_auth"].items():
            if apid != pid:
                continue
            churn_a = a + r
            rows.append({
                "author": akey, "added": a, "removed": r, "growth": a - r,
                "churn": churn_a, "modifications": m,
                "commits": m,
                "ownership": (churn_a / churn_o) if churn_o else 0.0,
            })
        rows.sort(key=lambda r: -r["churn"])
        object_payload = {
            "kind": "file",
            "path": norm_path,
            "metrics": metrics,
            "authors": rows,
            "last_change": iso_utc(fa_last[pid] or None),
        }
    else:
        did = scope_dir
        metrics = _metrics(da_add[did], da_rem[did], da_mods[did], size)
        churn_o = metrics["churn"]
        rows = []
        for (ddid, akey), (a, r) in agg["da_auth"].items():
            if ddid != did:
                continue
            churn_a = a + r
            rows.append({
                "author": akey, "added": a, "removed": r, "growth": a - r,
                "churn": churn_a,
                "modifications": agg["da_auth_mods"].get((did, akey), 0),
                "commits": agg["au_commits"].get(akey, 0),
                "ownership": (churn_a / churn_o) if churn_o else 0.0,
            })
        rows.sort(key=lambda r: -r["churn"])
        object_payload = {
            "kind": "directory",
            "path": norm_path,
            "metrics": metrics,
            "authors": rows,
            "last_change": iso_utc(da_last[did] or None),
        }

    # -- reverse index of per-file authors (main author + counts) --------
    file_main: dict = {}
    file_author_count: dict = {}
    for (pid, akey), (a, r, m) in agg["fa_auth"].items():
        churn_a = a + r
        file_author_count[pid] = file_author_count.get(pid, 0) + 1
        cur = file_main.get(pid)
        if cur is None or churn_a > cur[1]:
            file_main[pid] = (akey, churn_a)

    dir_main: dict = {}
    dir_author_count: dict = {}
    for (did, akey), (a, r) in agg["da_auth"].items():
        churn_a = a + r
        dir_author_count[did] = dir_author_count.get(did, 0) + 1
        cur = dir_main.get(did)
        if cur is None or churn_a > cur[1]:
            dir_main[did] = (akey, churn_a)

    # -- file rows --------------------------------------------------------
    file_rows = []
    for pid, path_name in enumerate(history.paths):
        churn_o = fa_add[pid] + fa_rem[pid]
        if churn_o <= 0:
            continue
        if scope_file is not None and pid != scope_file:
            continue
        if scope_dir is not None and scope_dir not in chains[pid]:
            continue
        metrics = _metrics(fa_add[pid], fa_rem[pid], fa_mods[pid], size)
        main = file_main.get(pid)
        main_name, main_churn = (main if main else ("", 0))
        file_rows.append({
            "path": path_name,
            "metrics": metrics,
            "authors": file_author_count.get(pid, 0),
            "main_author": main_name,
            "main_ownership": (main_churn / churn_o) if churn_o else 0.0,
            "last_change": iso_utc(fa_last[pid] or None),
        })
    file_rows.sort(key=lambda r: -r["metrics"]["churn"])
    files_total = len(file_rows)

    # -- directory rows ----------------------------------------------------
    dir_file_counts: dict = {}
    for pid in range(len(history.paths)):
        if fa_add[pid] + fa_rem[pid] <= 0:
            continue
        for did in chains[pid]:
            dir_file_counts[did] = dir_file_counts.get(did, 0) + 1

    dir_rows = []
    for did in range(1, len(dir_names)):
        churn_o = da_add[did] + da_rem[did]
        if churn_o <= 0:
            continue
        if scope_file is not None:
            continue
        if scope_dir is not None and did != scope_dir:
            # only descendants of the selected directory
            name = dir_names[did]
            parent = dir_names[scope_dir]
            if not name.startswith(parent + "/"):
                continue
        metrics = _metrics(da_add[did], da_rem[did], da_mods[did], size)
        main = dir_main.get(did)
        main_name, main_churn = (main if main else ("", 0))
        dir_rows.append({
            "path": dir_names[did],
            "metrics": metrics,
            "authors": dir_author_count.get(did, 0),
            "files": dir_file_counts.get(did, 0),
            "main_author": main_name,
            "main_ownership": (main_churn / churn_o) if churn_o else 0.0,
            "last_change": iso_utc(da_last[did] or None),
        })
    dir_rows.sort(key=lambda r: -r["metrics"]["churn"])
    dirs_total = len(dir_rows)

    # -- activity ----------------------------------------------------------
    bucket_mode, activity = _activity_points_list(
        agg["activity_points"], agg["first_ts"], agg["last_ts"])

    return {
        "reference": history.ref,
        "reference_sha": history.ref_sha,
        "commit_set": {
            "size": size,
            "first_commit_at": iso_utc(agg["first_ts"]),
            "last_commit_at": iso_utc(agg["last_ts"]),
            "mode": "hashes" if hashes else ("period" if (
                since_ts is not None or until_ts is not None) else "all"),
            "unresolved_hashes": missing_hashes,
            "author_commits": (agg["au_commits"].get(author_key, 0)
                               if author_key else None),
        },
        "filters": {
            "author": author_key,
            "path": norm_path or None,
            "since_ts": since_ts,
            "until_ts": until_ts,
            "hash_count": len(hashes) if hashes else 0,
        },
        "repository": {
            "metrics": repository["metrics"],
            "authors": repository["authors"],
            "files": repository["files"],
            "directories": repository["directories"],
            "distinct_authors_total": repository["distinct_authors_total"],
        },
        "object": object_payload,
        "authors": author_rows_for_repo() if object_payload is None else
        object_payload["authors"],
        "files": file_rows[:top],
        "files_total": files_total,
        "directories": dir_rows[:top],
        "directories_total": dirs_total,
        "activity": {"bucket": bucket_mode, "points": activity},
    }


# ---------------------------------------------------------------------------
# Oracle-format row export (used by /export and the verification script)
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "repo", "ref_sha", "commit_set", "commit_count", "object_type", "path",
    "author", "added", "removed", "growth", "churn", "modifications",
    "modification_frequency", "churn_rate", "ownership",
]


def export_rows(history, repo_name: str, mailmap_rules=None, merge_map=None,
                since_ts=None, until_ts=None, hashes=None, author=None,
                commit_set_label: str = "all") -> tuple[int, list]:
    """Build every metric row (ALL + per author) in the reference CSV format.

    Returns ``(commit_set_size, rows)`` where each row is a dict with keys
    from :data:`CSV_COLUMNS`; empty (undefined) values are ``None``.
    """
    resolved_by_raw = _resolve_all(history, mailmap_rules, merge_map)
    author_key = author.strip() if author else None
    if author_key and author_key not in set(resolved_by_raw):
        raise MetricsError(f"author '{author_key}' not found in repository")

    commits = select_commits(history, since_ts=since_ts, until_ts=until_ts,
                             hashes=hashes)
    agg = _aggregate(history, commits, resolved_by_raw, author_key=author_key)
    size = agg["size"]

    fa_add, fa_rem, fa_mods = agg["fa_add"], agg["fa_rem"], agg["fa_mods"]
    da_add, da_rem, da_mods = agg["da_add"], agg["da_rem"], agg["da_mods"]
    dir_names = agg["dir_names"]

    file_authors: dict = {}
    for (pid, akey), (a, r, m) in agg["fa_auth"].items():
        file_authors.setdefault(pid, []).append((akey, a, r, m))
    dir_authors: dict = {}
    for (did, akey), (a, r) in agg["da_auth"].items():
        m = agg["da_auth_mods"].get((did, akey), 0)
        dir_authors.setdefault(did, []).append((akey, a, r, m))

    base = {
        "repo": repo_name,
        "ref_sha": history.ref_sha,
        "commit_set": commit_set_label,
        "commit_count": size,
    }

    rows: list = []

    def emit(object_type: str, path_label: str, added: int, removed: int,
             mods: int, author_list):
        metrics = _metrics(added, removed, mods, size)
        churn_o = metrics["churn"]
        rows.append({
            **base,
            "object_type": object_type,
            "path": path_label,
            "author": "ALL",
            "added": metrics["added"],
            "removed": metrics["removed"],
            "growth": metrics["growth"],
            "churn": metrics["churn"],
            "modifications": metrics["modifications"],
            "modification_frequency": metrics["modification_frequency"],
            "churn_rate": metrics["churn_rate"],
            "ownership": None,
        })
        author_list = [entry for entry in author_list
                       if entry[1] + entry[2] > 0]
        author_list.sort(key=lambda e: -(e[1] + e[2]))
        for akey, a, r, m in author_list:
            churn_a = a + r
            rows.append({
                **base,
                "object_type": object_type,
                "path": path_label,
                "author": akey,
                "added": a,
                "removed": r,
                "growth": a - r,
                "churn": churn_a,
                "modifications": m,
                "modification_frequency": None,
                "churn_rate": None,
                "ownership": (churn_a / churn_o) if churn_o else 0.0,
            })

    # repository (root)
    emit("repository", "/", da_add[0], da_rem[0], da_mods[0],
         [(akey, agg["au_add"].get(akey, 0), agg["au_rem"].get(akey, 0),
           agg["au_mods"].get(akey, 0))
          for akey in set(list(agg["au_add"]) + list(agg["au_rem"]))])

    # directories (skip root)
    for did in sorted(range(1, len(dir_names)), key=lambda d: dir_names[d]):
        emit("directory", dir_names[did], da_add[did], da_rem[did],
             da_mods[did], dir_authors.get(did, []))

    # files
    for pid in sorted(range(len(history.paths)),
                      key=lambda p: history.paths[p]):
        emit("file", history.paths[pid], fa_add[pid], fa_rem[pid],
             fa_mods[pid], file_authors.get(pid, []))

    return size, rows


def list_paths(history) -> dict:
    """All touched file paths and directories (for pickers / suggestions)."""
    chains, dir_names, _ = _build_dir_lookup(history.paths)
    return {
        "files": history.paths,
        "directories": dir_names[1:],
    }
