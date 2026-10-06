import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { api, exportUrl } from "./api";
import AddRepoModal from "./components/AddRepoModal";
import AuthorsModal from "./components/AuthorsModal";
import CommitPicker from "./components/CommitPicker";
import Dashboard from "./components/Dashboard";
import FilterPanel from "./components/FilterPanel";
import RepoBar from "./components/RepoBar";

const DEFAULT_FILTERS = {
  mode: "all", // all | period | manual
  since: "",
  until: "",
  manualHashes: [],
  author: "",
  path: "",
  top: 250,
};

function initialTheme() {
  const saved = window.localStorage.getItem("rat-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export default function App() {
  const [theme, setTheme] = useState(initialTheme);
  const [repos, setRepos] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [analysis, setAnalysis] = useState(null);
  const [authorsData, setAuthorsData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const [showAuthors, setShowAuthors] = useState(false);

  const filtersRef = useRef(filters);
  const analysisRef = useRef(analysis);
  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);
  useEffect(() => {
    analysisRef.current = analysis;
  }, [analysis]);

  const activeRepo = repos.find((r) => r.id === activeId) || null;

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("rat-theme", theme);
  }, [theme]);

  const notify = useCallback((text, type = "info") => {
    setToast({ text, type, at: Date.now() });
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const handle = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(handle);
  }, [toast]);

  const loadRepos = useCallback(async () => {
    try {
      const data = await api.listRepos();
      const list = data.repositories || [];
      setRepos(list);
      return list;
    } catch (err) {
      notify(`Could not load repositories: ${err.message}`, "error");
      return [];
    }
  }, [notify]);

  useEffect(() => {
    loadRepos();
  }, [loadRepos]);

  const refreshAuthors = useCallback(
    async (repoId) => {
      if (repoId == null) return;
      try {
        setAuthorsData(await api.authors(repoId));
      } catch (err) {
        notify(`Could not load authors: ${err.message}`, "error");
      }
    },
    [notify]
  );

  const doAnalyze = useCallback(
    async (repoId, f) => {
      if (repoId == null) return;
      const body = { ref: "HEAD", top: f.top };
      if (f.mode === "period") {
        if (f.since) body.since = f.since;
        if (f.until) body.until = f.until;
      }
      if (f.mode === "manual" && f.manualHashes.length) {
        body.hashes = f.manualHashes;
      }
      if (f.author) body.author = f.author;
      if (f.path && f.path.trim()) body.path = f.path.trim();

      setBusy(true);
      try {
        const data = await api.analyze(repoId, body);
        setAnalysis(data);
        const missing = data.commit_set.unresolved_hashes || [];
        if (missing.length) {
          notify(`${missing.length} selected commit(s) could not be resolved.`, "warn");
        }
      } catch (err) {
        notify(`Analysis failed: ${err.message}`, "error");
      } finally {
        setBusy(false);
      }
    },
    [notify]
  );

  const runAnalysis = useCallback(
    (overrides = {}) =>
      doAnalyze(activeId, { ...filtersRef.current, ...overrides }),
    [activeId, doAnalyze]
  );

  // Switching repositories resets all filters, reloads authors and runs the
  // default (all commits) analysis.
  useEffect(() => {
    setFilters(DEFAULT_FILTERS);
    setAnalysis(null);
    setAuthorsData(null);
    if (activeId != null) {
      refreshAuthors(activeId);
      doAnalyze(activeId, DEFAULT_FILTERS);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  // Author dropdown entries: canonical identities with summed commit counts.
  const identities = useMemo(() => {
    if (!authorsData) return [];
    const map = new Map();
    for (const row of authorsData.identities) {
      const entry =
        map.get(row.resolved) || { name: row.resolved, commits: 0, rawCount: 0 };
      entry.commits += row.commits;
      entry.rawCount += 1;
      map.set(row.resolved, entry);
    }
    return [...map.values()].sort((a, b) => b.commits - a.commits);
  }, [authorsData]);

  function handleFilterChange(patch) {
    setFilters((prev) => ({ ...prev, ...patch }));
  }

  function handleReset() {
    setFilters(DEFAULT_FILTERS);
    runAnalysis(DEFAULT_FILTERS);
  }

  function handlePath(path) {
    handleFilterChange({ path });
    runAnalysis({ path });
  }

  function handleAuthorsChanged() {
    refreshAuthors(activeId);
    if (analysisRef.current) runAnalysis();
  }

  function handleExport() {
    if (!activeRepo) return;
    const f = filtersRef.current;
    const url = exportUrl(activeRepo.id, {
      ref: analysisRef.current ? analysisRef.current.reference_sha : "HEAD",
      since: f.mode === "period" ? f.since : "",
      until: f.mode === "period" ? f.until : "",
      author: f.author,
      hashes: f.mode === "manual" ? f.manualHashes : [],
    });
    window.open(url, "_blank");
  }

  async function handleDelete() {
    if (!activeRepo) return;
    if (!window.confirm(`Delete “${activeRepo.name}” and all of its stored files?`)) {
      return;
    }
    try {
      await api.deleteRepo(activeRepo.id);
      notify(`Deleted ${activeRepo.name}.`);
      setActiveId(null);
      setAnalysis(null);
      loadRepos();
    } catch (err) {
      notify(`Delete failed: ${err.message}`, "error");
    }
  }

  function handleCreated(repo) {
    setShowAdd(false);
    notify(`Added “${repo.name}”.`);
    loadRepos().then(() => setActiveId(repo.id));
  }

  return (
    <div className="app">
      <RepoBar
        repos={repos}
        activeId={activeId}
        analysis={analysis}
        busy={busy}
        theme={theme}
        onThemeToggle={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
        onSelect={setActiveId}
        onAdd={() => setShowAdd(true)}
        onDelete={handleDelete}
        onOpenAuthors={() => setShowAuthors(true)}
        onExport={handleExport}
      />

      <div className="layout">
        {activeRepo && (
          <FilterPanel
            repoId={activeRepo.id}
            identities={identities}
            filters={filters}
            onChange={handleFilterChange}
            onRun={() => runAnalysis()}
            onReset={handleReset}
            onOpenPicker={() => setShowPicker(true)}
            busy={busy}
          />
        )}

        <main className="main">
          {!repos.length && (
            <div className="empty-state">
              <h2>No repositories yet</h2>
              <p>
                Add a zip archive containing a <span className="mono">.git</span>{" "}
                directory (or <span className="mono">.git</span> file), or clone a
                repository by URL — full history is analysed either way.
              </p>
              <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
                + Add repository
              </button>
            </div>
          )}

          {repos.length > 0 && !activeRepo && (
            <div className="empty-state">
              <h2>Select a repository</h2>
              <p>Choose a repository in the top bar, or add a new one.</p>
            </div>
          )}

          {activeRepo && busy && (
            <div className="loading-state">
              <div className="spinner" />
              <p>
                Analysing <b>{activeRepo.name}</b>… large histories can take a
                minute on the first run.
              </p>
            </div>
          )}

          {activeRepo && !busy && !analysis && (
            <div className="empty-state">
              <h2>Ready when you are</h2>
              <p>Adjust the filters on the left and press “Run analysis”.</p>
            </div>
          )}

          {activeRepo && !busy && analysis && (
            <Dashboard analysis={analysis} onPath={handlePath} />
          )}
        </main>
      </div>

      {showAdd && (
        <AddRepoModal onClose={() => setShowAdd(false)} onCreated={handleCreated} />
      )}

      {showPicker && activeRepo && (
        <CommitPicker
          repoId={activeRepo.id}
          initialSelected={filters.manualHashes}
          onApply={(hashes) => {
            setFilters((prev) => ({ ...prev, manualHashes: hashes, mode: "manual" }));
            setShowPicker(false);
          }}
          onClose={() => setShowPicker(false)}
        />
      )}

      {showAuthors && activeRepo && (
        <AuthorsModal
          repoId={activeRepo.id}
          repoName={activeRepo.name}
          onClose={() => setShowAuthors(false)}
          onChanged={handleAuthorsChanged}
        />
      )}

      {toast && <div className={`toast toast-${toast.type}`}>{toast.text}</div>}
    </div>
  );
}
