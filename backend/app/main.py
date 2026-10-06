"""FastAPI backend for the Repo Analysis Tool (RAT).

Endpoints cover: repository management (zip upload / URL deep clone / delete),
author merging (mailmap + manual), commit listing for the manual picker,
path suggestions, metric analysis with all filters, and CSV export in the
reference metric format.
"""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, git_reader, metrics

app = FastAPI(title="Repo Analysis Tool", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CloneRequest(BaseModel):
    url: str
    name: str | None = None


class MailmapRequest(BaseModel):
    text: str = ""


class MergeEntry(BaseModel):
    alias_name: str = ""
    alias_email: str = ""
    canonical_name: str
    canonical_email: str


class MergesRequest(BaseModel):
    merges: list[MergeEntry] = []


class AnalyzeRequest(BaseModel):
    ref: str = "HEAD"
    since: str | None = None
    until: str | None = None
    hashes: list[str] | None = None
    author: str | None = None
    path: str | None = None
    top: int = 250


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(value: str, fallback: str = "repo") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip())
    value = value.strip("-._") or fallback
    return value[:60]


def _unique_repo_path(name: str) -> Path:
    base = db.REPOS_DIR / _slugify(name)
    candidate = base
    counter = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name}-{counter}")
        counter += 1
    return candidate


def _repo_or_404(repo_id: int) -> dict:
    repo = db.get_repository(repo_id)
    if not repo:
        raise HTTPException(404, f"repository {repo_id} not found")
    if not Path(repo["path"]).exists():
        raise HTTPException(
            410, f"repository files for {repo_id} are missing from storage")
    return repo


def _public_repo(repo: dict) -> dict:
    return {
        "id": repo["id"],
        "name": repo["name"],
        "source_type": repo["source_type"],
        "source": repo["source"],
        "created_at": repo["created_at"],
        "has_mailmap_override": bool(
            repo["mailmap_text"] and repo["mailmap_text"].strip()),
    }


def _load_history(repo: dict, ref: str):
    try:
        return git_reader.load_history(repo["path"], ref or "HEAD")
    except git_reader.GitError as exc:
        raise HTTPException(400, str(exc))


def _effective_mailmap(repo: dict) -> str:
    override = repo["mailmap_text"]
    if override and override.strip():
        return override
    return git_reader.read_repo_mailmap(repo["path"])


def _filters(repo: dict):
    rules = git_reader.parse_mailmap(_effective_mailmap(repo))
    merges = metrics.build_merge_map(db.get_merges(repo["id"]))
    return rules, merges


def _parse_timestamp(value, exclusive_end: bool = False):
    """Parse an ISO date or datetime into UTC epoch seconds.

    A date-only ``until`` value is treated as inclusive (the whole day), i.e.
    it becomes the following midnight, keeping the half-open interval
    ``[since, until)`` intact.
    """
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        if len(text) == 10:
            dt = datetime.strptime(text, "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
            if exclusive_end:
                dt = dt + timedelta(days=1)
        else:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(400, f"invalid date/time value: {value!r}")
    return int(dt.timestamp())


def _commit_set_label(since_ts, until_ts, hashes) -> str:
    if hashes:
        return "manual"
    if since_ts is not None or until_ts is not None:
        return "period"
    return "all"


# ---------------------------------------------------------------------------
# Repository management
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/repos")
def list_repos():
    repos = []
    for repo in db.list_repositories():
        item = _public_repo(repo)
        item["available"] = Path(repo["path"]).exists()
        repos.append(item)
    return {"repositories": repos}


@app.get("/api/repos/{repo_id}")
def get_repo(repo_id: int):
    repo = _repo_or_404(repo_id)
    return _public_repo(repo)


@app.post("/api/repos/upload")
def upload_repo(file: UploadFile = File(...), name: str | None = Form(None)):
    filename = file.filename or "repository.zip"
    display_name = (name or Path(filename).stem).strip() or "repository"
    dest = _unique_repo_path(display_name)
    tmp_dir = Path(tempfile.mkdtemp(prefix="rat-upload-"))
    tmp_zip = tmp_dir / "upload.zip"
    try:
        with tmp_zip.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            git_reader.extract_zip(tmp_zip, dest)
        except zipfile.BadZipFile:
            raise HTTPException(400, "the uploaded file is not a valid zip archive")
        try:
            repo_root = git_reader.find_repo_root(dest)
        except git_reader.GitError as exc:
            raise HTTPException(400, str(exc))
        try:
            git_reader.resolve_ref(repo_root, "HEAD")
        except git_reader.GitError as exc:
            raise HTTPException(
                400, f"the archive does not contain a usable git repository ({exc})")
        repo_id = db.add_repository(
            display_name, "zip", filename, str(repo_root))
        return _public_repo(db.get_repository(repo_id))
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/repos/clone")
def clone_repo(req: CloneRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "repository URL is empty")
    name = (req.name or url.rstrip("/").split("/")[-1] or "repository")
    name = re.sub(r"\.git$", "", name, flags=re.IGNORECASE)
    dest = _unique_repo_path(name)
    try:
        git_reader.clone_repository(url, dest)
        git_reader.resolve_ref(dest, "HEAD")
    except git_reader.GitError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(400, str(exc))
    repo_id = db.add_repository(name, "url", url, str(dest))
    return _public_repo(db.get_repository(repo_id))


@app.delete("/api/repos/{repo_id}")
def delete_repo(repo_id: int):
    repo = _repo_or_404(repo_id)
    storage = str(db.REPOS_DIR.resolve())
    resolved = str(Path(repo["path"]).resolve())
    if resolved == storage or not resolved.startswith(storage + os.sep):
        raise HTTPException(400, "refusing to delete a path outside storage")
    git_reader.clear_caches(resolved)
    shutil.rmtree(resolved, ignore_errors=True)
    db.delete_repository(repo_id)
    return {"deleted": repo_id}


# ---------------------------------------------------------------------------
# Author merging
# ---------------------------------------------------------------------------

@app.get("/api/repos/{repo_id}/authors")
def repo_authors(repo_id: int, ref: str = "HEAD"):
    repo = _repo_or_404(repo_id)
    history = _load_history(repo, ref)
    rules, merges = _filters(repo)
    return {
        "identities": metrics.list_author_identities(history, rules, merges),
        "reference_sha": history.ref_sha,
        "total_commits": len(history.commits),
    }


@app.get("/api/repos/{repo_id}/mailmap")
def get_mailmap(repo_id: int):
    repo = _repo_or_404(repo_id)
    repo_text = git_reader.read_repo_mailmap(repo["path"])
    override = repo["mailmap_text"]
    effective = override if (override and override.strip()) else repo_text
    return {
        "override": override,
        "repo_text": repo_text,
        "effective": effective,
        "has_override": bool(override and override.strip()),
    }


@app.put("/api/repos/{repo_id}/mailmap")
def put_mailmap(repo_id: int, req: MailmapRequest):
    _repo_or_404(repo_id)
    db.set_mailmap(repo_id, req.text if req.text.strip() else None)
    return {"ok": True}


@app.get("/api/repos/{repo_id}/merges")
def get_merges(repo_id: int):
    _repo_or_404(repo_id)
    return {"merges": db.get_merges(repo_id)}


@app.put("/api/repos/{repo_id}/merges")
def put_merges(repo_id: int, req: MergesRequest):
    _repo_or_404(repo_id)
    db.replace_merges(repo_id, [m.model_dump() for m in req.merges])
    return {"merges": db.get_merges(repo_id)}


@app.delete("/api/repos/{repo_id}/merges")
def delete_merges(repo_id: int):
    _repo_or_404(repo_id)
    db.clear_merges(repo_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Commits, paths, analysis
# ---------------------------------------------------------------------------

@app.get("/api/repos/{repo_id}/commits")
def repo_commits(repo_id: int, ref: str = "HEAD", q: str = "",
                 limit: int = 100, offset: int = 0):
    repo = _repo_or_404(repo_id)
    history = _load_history(repo, ref)
    needle = q.strip().lower()
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    items = []
    skipped = 0
    for sha, raw_aid, ct, at, subject, files in history.commits:
        identity = history.authors[raw_aid]
        if needle and (needle not in sha.lower()
                       and needle not in subject.lower()
                       and needle not in identity.lower()):
            continue
        if skipped < offset:
            skipped += 1
            continue
        added = sum(f[1] for f in files)
        removed = sum(f[2] for f in files)
        items.append({
            "hash": sha,
            "author": identity,
            "committer_date": metrics.iso_utc(ct),
            "committer_ts": ct,
            "subject": subject,
            "files": len(files),
            "added": added,
            "removed": removed,
            "churn": added + removed,
        })
        if len(items) >= limit:
            break

    return {
        "items": items,
        "reference_sha": history.ref_sha,
        "total": len(history.commits) if not needle else None,
    }


@app.get("/api/repos/{repo_id}/paths")
def repo_paths(repo_id: int, ref: str = "HEAD", q: str = "",
               limit: int = 200):
    repo = _repo_or_404(repo_id)
    history = _load_history(repo, ref)
    data = metrics.list_paths(history)
    needle = q.strip().lower()
    limit = max(1, min(limit, 1000))
    files = sorted(p for p in data["files"] if needle in p.lower())
    dirs = sorted(d for d in data["directories"] if needle in d.lower())
    return {
        "files": files[:limit],
        "directories": dirs[:limit],
        "files_total": len(files),
        "directories_total": len(dirs),
        "reference_sha": history.ref_sha,
    }


@app.post("/api/repos/{repo_id}/analyze")
def analyze_repo(repo_id: int, req: AnalyzeRequest):
    repo = _repo_or_404(repo_id)
    history = _load_history(repo, req.ref)
    rules, merges = _filters(repo)
    try:
        since_ts = _parse_timestamp(req.since, exclusive_end=False)
        until_ts = _parse_timestamp(req.until, exclusive_end=True)
        payload = metrics.analyze(
            history, rules, merges,
            since_ts=since_ts, until_ts=until_ts, hashes=req.hashes,
            author=req.author, path=req.path,
            top=max(1, min(req.top, 2000)),
        )
    except metrics.MetricsError as exc:
        raise HTTPException(400, str(exc))
    payload["repo"] = _public_repo(repo)
    return payload


@app.get("/api/repos/{repo_id}/export.csv")
def export_csv(repo_id: int, ref: str = "HEAD", since: str | None = None,
               until: str | None = None, author: str | None = None,
               hashes: str = ""):
    repo = _repo_or_404(repo_id)
    history = _load_history(repo, ref)
    rules, merges = _filters(repo)
    hash_list = [h for h in (hashes or "").split(",") if h.strip()]
    since_ts = _parse_timestamp(since, exclusive_end=False)
    until_ts = _parse_timestamp(until, exclusive_end=True)
    try:
        _, rows = metrics.export_rows(
            history, repo["name"], rules, merges,
            since_ts=since_ts, until_ts=until_ts,
            hashes=hash_list or None, author=author,
            commit_set_label=_commit_set_label(since_ts, until_ts, hash_list),
        )
    except metrics.MetricsError as exc:
        raise HTTPException(400, str(exc))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(metrics.CSV_COLUMNS)
    for row in rows:
        writer.writerow(["" if row[col] is None else row[col]
                         for col in metrics.CSV_COLUMNS])
    filename = f"{_slugify(repo['name'])}_{history.ref_sha[:12]}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Optionally serve the built frontend (production mode)
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True),
              name="frontend")
else:
    @app.get("/")
    def root():
        return {
            "name": "Repo Analysis Tool API",
            "docs": "/docs",
            "frontend": "run `npm install && npm run dev` inside ./frontend "
                        "(dev) or `npm run build` to serve it from here",
        }
