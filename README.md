# Repo Analysis Tool (RAT)

A web app that computes per-file / per-directory / per-repository / per-commit-set
metrics for any git history, with author merging and CSV export in the reference
metric format.

## Features

- **Add repositories** two ways: upload a zip archive that contains a `.git`
  directory (or `.git` file), or clone a remote URL with full history.
  (Note: "Download ZIP" exports from GitHub/GitLab contain no `.git` folder
  and cannot be analysed — clone the repository URL instead, or re-zip a
  local clone including its `.git` directory.)
- **Filters**
  - *Commit set*: all commits, a date period (inclusive dates, committer-date
    semantics), or a hand-picked list of commits (searchable, paginated picker).
  - *Author*: any canonical identity after `.mailmap` + manual merges.
  - *Path*: whole repository, one file, or one directory (with descendants).
- **Author merging**
  - the repository's own `.mailmap` is applied automatically (exact git
    semantics, verified against `git check-mailmap`);
  - additional manual merges per repository via the "Authors & mailmap" dialog,
    or a full custom mailmap override.
- **Dashboard**: metric cards (added / removed / growth / churn / modifications /
  modification frequency / churn rate), activity chart, sortable authors /
  files / directories tables with ownership and main-author info.
- **Persistent light and dark themes** with a responsive technical command-centre
  interface; the selected theme is remembered in the browser.
- **CSV export** (`/api/repos/{id}/export.csv`) in the exact 15-column reference
  format, honouring all active filters.

## Metric semantics (as implemented and verified)

- Merge commits are excluded (`--no-merges`); filters use committer dates.
- Renames are detected at 50% similarity (`-M50%`); line churn (x/y) is
  attributed to the **new** path, and both sides of a rename are registered as
  paths (a rename source with no other history appears with zero churn).
- Binary files are not measured (no line counts); zero-churn registered paths
  are listed with zero metrics but no author rows.
- `modification_frequency = modifications / commit-set size`;
  `churn_rate = churn / commit-set size`;
  `ownership = author churn / scope churn`;
  repository/directory `modifications` = commits with churn touching the scope.

## Running the platform (clone → app running)

### 1. Requirements

| Tool | Needed for | Notes |
| --- | --- | --- |
| Python 3.10+ | backend (FastAPI) | `python3 -m venv` must be available |
| git | analysing histories | the engine shells out to the `git` CLI |
| Node.js 18+ / npm | building the web UI | optional — without it the API still runs |
| Internet | cloning repositories, npm install | not needed once everything is built |

### 2. Clone and start

```bash
git clone https://github.com/2846849/repo-analysis-tool repo-analysis-tool
cd repo-analysis-tool
./run.sh
```

`run.sh` is idempotent; on first run it:

1. creates `backend/.venv` and installs `backend/requirements.txt`;
2. builds the frontend (`npm install` + `npm run build`) if `frontend/dist`
   is missing;
3. starts the API + UI on **http://127.0.0.1:8000**.

### 3. Open the app

Browse to http://127.0.0.1:8000. A fresh install starts empty — all app data
(repository registry, caches, uploaded repositories) lives in
`backend/storage/`, which is created automatically and is gitignored.

### 4. Add a repository

Use **+ Add repository** in the sidebar:

- **Clone from URL** — paste any git URL (e.g. `https://github.com/git/git.git`).
  Full history is fetched. The first analysis of a large repository takes a few
  seconds while the log is parsed; later analyses are served from a cache.
- **Upload zip** — the archive must contain a `.git` directory (or `.git` file)
  anywhere within 4 folder levels, e.g. `zip -r repo.zip .` from inside a clone.
  "Download ZIP" exports from GitHub/GitLab contain no `.git` and are rejected.

### 5. Analyse and export

1. pick the repository in the top bar;
2. choose filters — commit set (all / date period / hand-picked commits),
   author, path (file or directory), top-N — and press **Run analysis**;
3. click rows in the Files / Directories tables to re-scope the analysis;
4. **Export CSV** downloads the current view in the 15-column reference format.

### Manual setup (without run.sh)

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install && npm run build)      # optional, needs Node 18+
cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Arguments after `./run.sh` are passed to uvicorn, e.g. `./run.sh --port 8001`.

### Development mode

```bash
# terminal 1 — backend
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000
# terminal 2 — frontend dev server with /api proxy
cd frontend && npm run dev        # http://127.0.0.1:5173
```

### Troubleshooting

- **Port already in use** → `./run.sh --port 8001` (or any free port).
- **UI not served (only /docs works)** → npm was missing during the first run;
  run `cd frontend && npm install && npm run build`, then restart.
- **Zip upload rejected** → the archive contains no `.git`; zip a local clone
  (`zip -r repo.zip .` inside it), or use "Clone from URL" instead.

## Verification

Re-create the reference clones first (gitignored, ~630 MB, takes a few minutes):

```bash
./verification/clone_repos.sh                      # clones cJSON, redis, git into verification/clones/
```

Then, pointing `--csv` at the reference CSV files provided with the assignment:

```bash
python3 backend/selftest.py                        # synthetic scenario, all expectations must pass
python3 verification/verify_csv.py --repo verification/clones/cJSON \
    --csv ~/Downloads/repo-references/cJSON_6d9f2443ab07.csv        # oracle comparison
python3 verification/compare_csv_files.py ref.csv served.csv        # compare any two exports
python3 verification/check_mailmap.py --repo verification/clones/git # mailmap vs git check-mailmap
```

All three reference CSVs pass with zero discrepancies — cJSON (983 rows),
redis (18,301 rows) and git.git (62,600 rows, the repository's own `.mailmap`
applied) — both via the local engine (`verify_csv.py`) and via the served HTTP
export endpoint (`compare_csv_files.py` against `/api/repos/{id}/export.csv`).

## HTTP API

| Method & path | Purpose |
| --- | --- |
| `GET /api/repos` | list repositories |
| `POST /api/repos/upload` | add from zip (multipart `file`, optional `name`) |
| `POST /api/repos/clone` | add from URL `{"url", "name"}` |
| `DELETE /api/repos/{id}` | delete repository + stored files |
| `GET /api/repos/{id}/authors` | raw identities + commit counts + canonical form |
| `GET/PUT /api/repos/{id}/mailmap` | read/set the mailmap override |
| `GET/PUT/DELETE /api/repos/{id}/merges` | manual author merges |
| `GET /api/repos/{id}/commits` | commit list for the picker (`q`, `limit`, `offset`) |
| `GET /api/repos/{id}/paths` | file/directory suggestions (`q`) |
| `POST /api/repos/{id}/analyze` | full analysis (`ref`, `since`, `until`, `hashes`, `author`, `path`, `top`) |
| `GET /api/repos/{id}/export.csv` | CSV export honouring the same filters |

Interactive API docs: `http://127.0.0.1:8000/docs`.

## Layout

```
backend/            FastAPI app (app/main.py, metrics.py, git_reader.py, db.py),
                    requirements.txt, selftest.py, storage/ (db, caches, repos)
frontend/           React + Vite UI (src/App.jsx, src/components/*)
verification/       oracle CSV tooling + clone_repos.sh (clones are gitignored)
run.sh              one-command build + serve
```
