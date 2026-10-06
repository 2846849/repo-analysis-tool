import { shortSha } from "../format";

// Top bar: repository picker plus the global actions (add / authors /
// export / delete) and a one-line summary of the active repository.
export default function RepoBar({
  repos,
  activeId,
  analysis,
  busy,
  theme,
  onThemeToggle,
  onSelect,
  onAdd,
  onDelete,
  onOpenAuthors,
  onExport,
}) {
  const active = repos.find((r) => r.id === activeId) || null;

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">RAT</span>
        <div className="brand-text">
          <h1>Repo Analysis Tool</h1>
          <p className="system-line">
            <span className="status-dot" aria-hidden="true" />
            SYS.ONLINE // GIT INTELLIGENCE
          </p>
        </div>
      </div>

      <div className="topbar-controls">
        <select
          className="repo-select"
          value={activeId ?? ""}
          onChange={(e) => onSelect(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">Select a repository…</option>
          {repos.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name} ({r.source_type})
            </option>
          ))}
        </select>
        <button className="btn" onClick={onAdd}>+ Add repository</button>
        <button className="btn" disabled={!active || busy} onClick={onOpenAuthors}>
          Authors &amp; mailmap
        </button>
        <button className="btn btn-primary" disabled={!active || busy} onClick={onExport}>
          Export CSV
        </button>
        <button
          className="btn theme-toggle"
          onClick={onThemeToggle}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          aria-pressed={theme === "light"}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
        >
          <span aria-hidden="true">{theme === "dark" ? "☼" : "◐"}</span>
          {theme === "dark" ? "LIGHT" : "DARK"}
        </button>
        <button
          className="btn btn-danger"
          disabled={!active || busy}
          onClick={onDelete}
          title="Remove this repository from storage"
        >
          Delete
        </button>
      </div>

      {active && (
        <div className="topbar-meta">
          <span className="muted">
            {active.source_type === "url" ? "cloned from " : "uploaded as "}
            <span className="mono">{active.source}</span>
          </span>
          {analysis && (
            <span className="badge">@{shortSha(analysis.reference_sha, 12)}</span>
          )}
          {active.has_mailmap_override && (
            <span className="badge badge-info">custom mailmap</span>
          )}
          {active.available === false && (
            <span className="badge badge-warn">files missing</span>
          )}
        </div>
      )}
    </header>
  );
}
