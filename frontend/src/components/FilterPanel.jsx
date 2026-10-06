import { useEffect, useState } from "react";

import { api } from "../api";

const TOP_CHOICES = [50, 100, 250, 500, 1000, 2000];

// Left sidebar: commit-set mode (all / period / manual selection), author
// filter, file-or-directory scope, top-N limit and the run/reset buttons.
export default function FilterPanel({
  repoId,
  identities,
  filters,
  onChange,
  onRun,
  onReset,
  onOpenPicker,
  busy,
}) {
  const [suggest, setSuggest] = useState({ files: [], directories: [] });

  // Debounced path suggestions for the datalist (files + directories).
  useEffect(() => {
    if (repoId == null) return undefined;
    const needle = filters.path.replace(/\/+$/, "").trim();
    const handle = setTimeout(async () => {
      try {
        setSuggest(await api.paths(repoId, needle, 40));
      } catch {
        /* suggestions are best-effort */
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [repoId, filters.path]);

  const manualCount = filters.manualHashes.length;

  return (
    <aside className="sidebar">
      <h2>Filters</h2>

      <section className="field-group">
        <span className="field-label">Commit set</span>
        <div className="segmented">
          {[
            ["all", "All commits"],
            ["period", "Period"],
            ["manual", "Selected"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={filters.mode === value ? "seg active" : "seg"}
              onClick={() => onChange({ mode: value })}
            >
              {label}
            </button>
          ))}
        </div>

        {filters.mode === "period" && (
          <div className="period-inputs">
            <label>
              From
              <input
                type="date"
                value={filters.since}
                onChange={(e) => onChange({ since: e.target.value })}
              />
            </label>
            <label>
              To
              <input
                type="date"
                value={filters.until}
                onChange={(e) => onChange({ until: e.target.value })}
              />
            </label>
          </div>
        )}

        {filters.mode === "manual" && (
          <div className="manual-pick">
            <button type="button" className="btn" onClick={onOpenPicker}>
              Choose commits…
            </button>
            <span className="badge badge-info">{manualCount} selected</span>
          </div>
        )}
        {filters.mode === "manual" && manualCount === 0 && (
          <p className="hint">
            Nothing selected yet — the analysis runs over all commits until you pick some.
          </p>
        )}
      </section>

      <section className="field-group">
        <label className="field-label" htmlFor="author-filter">Author</label>
        <select
          id="author-filter"
          value={filters.author}
          onChange={(e) => onChange({ author: e.target.value })}
        >
          <option value="">All authors</option>
          {identities.map((a) => (
            <option key={a.name} value={a.name}>
              {a.name} · {a.commits}
            </option>
          ))}
        </select>
      </section>

      <section className="field-group">
        <label className="field-label" htmlFor="path-filter">File or directory</label>
        <input
          id="path-filter"
          list="path-options"
          placeholder="whole repository"
          value={filters.path}
          onChange={(e) => onChange({ path: e.target.value })}
        />
        <datalist id="path-options">
          {suggest.directories.map((d) => (
            <option key={`dir-${d}`} value={`${d}/`}>{`${d} (directory)`}</option>
          ))}
          {suggest.files.map((f) => (
            <option key={`file-${f}`} value={f} />
          ))}
        </datalist>
        <p className="hint">Leave empty for repository scope; directories end with “/”.</p>
      </section>

      <section className="field-group">
        <label className="field-label" htmlFor="top-select">Top rows</label>
        <select
          id="top-select"
          value={filters.top}
          onChange={(e) => onChange({ top: Number(e.target.value) })}
        >
          {TOP_CHOICES.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </section>

      <div className="sidebar-actions">
        <button className="btn btn-primary btn-block" disabled={busy} onClick={onRun}>
          {busy ? "Analyzing…" : "Run analysis"}
        </button>
        <button className="btn btn-ghost btn-block" disabled={busy} onClick={onReset}>
          Reset filters
        </button>
      </div>
    </aside>
  );
}
