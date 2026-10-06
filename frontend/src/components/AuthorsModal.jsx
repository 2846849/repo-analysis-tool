import { useEffect, useState } from "react";

import { api } from "../api";
import { fmtInt } from "../format";

// Modal with two tabs:
//  - Identities: raw author identities with commit counts, multi-select and
//    merge into one canonical identity (manual merges stored per repository)
//  - Mailmap: view the repository .mailmap and edit a custom override
export default function AuthorsModal({ repoId, repoName, onClose, onChanged }) {
  const [tab, setTab] = useState("identities");
  const [rows, setRows] = useState(null);
  const [totalCommits, setTotalCommits] = useState(0);
  const [merges, setMerges] = useState([]);
  const [mailmap, setMailmap] = useState(null);
  const [overrideText, setOverrideText] = useState("");
  const [checked, setChecked] = useState(() => new Set());
  const [canonical, setCanonical] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function reload() {
    try {
      const [authors, mergesData, mm] = await Promise.all([
        api.authors(repoId),
        api.getMerges(repoId),
        api.getMailmap(repoId),
      ]);
      setRows(authors.identities);
      setTotalCommits(authors.total_commits);
      setMerges(mergesData.merges || []);
      setMailmap(mm);
      setOverrideText(mm.override || "");
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId]);

  const identities = rows || [];
  const selectedRows = identities.filter((r) => checked.has(r.raw));
  const groups = new Set(identities.map((r) => r.resolved)).size;

  function toggleRow(raw) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(raw)) next.delete(raw);
      else next.add(raw);
      return next;
    });
    setCanonical((prev) => (prev === raw ? null : prev));
  }

  async function applyMerge() {
    if (selectedRows.length < 2) return;
    const canonRow =
      selectedRows.find((r) => r.raw === canonical) || selectedRows[0];
    const entries = selectedRows
      .filter((r) => r.raw !== canonRow.raw)
      .map((r) => ({
        alias_name: r.effective_name,
        alias_email: r.effective_email,
        canonical_name: canonRow.effective_name,
        canonical_email: canonRow.effective_email,
      }))
      .filter(
        (e) =>
          !(e.alias_name === e.canonical_name && e.alias_email === e.canonical_email)
      );
    if (!entries.length) {
      setError("Those identities already resolve to the same person.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.putMerges(repoId, [...merges, ...entries]);
      setMerges(res.merges);
      setChecked(new Set());
      setCanonical(null);
      setNotice(
        `Merged ${entries.length} identit${entries.length === 1 ? "y" : "ies"} into “${canonRow.effective_name}”.`
      );
      if (onChanged) onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeMerge(entry) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const rest = merges.filter(
        (m) =>
          !(
            m.alias_name === entry.alias_name &&
            m.alias_email === entry.alias_email
          )
      );
      const res = await api.putMerges(repoId, rest);
      setMerges(res.merges);
      if (onChanged) onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function clearMerges() {
    if (!window.confirm("Remove all manual author merges for this repository?")) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.putMerges(repoId, []);
      setMerges(res.merges);
      if (onChanged) onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveMailmap() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.putMailmap(repoId, overrideText);
      await reload();
      setNotice(
        overrideText.trim()
          ? "Custom mailmap override saved."
          : "Override cleared — the repository .mailmap is used again."
      );
      if (onChanged) onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="modal modal-wide">
        <div className="modal-head">
          <h2>Authors &amp; mailmap — {repoName}</h2>
          <button className="icon-btn" onClick={onClose} disabled={busy} aria-label="Close">
            ×
          </button>
        </div>

        <div className="radio-tabs">
          <button
            type="button"
            className={tab === "identities" ? "radio-tab active" : "radio-tab"}
            onClick={() => setTab("identities")}
          >
            Identities ({identities.length})
          </button>
          <button
            type="button"
            className={tab === "mailmap" ? "radio-tab active" : "radio-tab"}
            onClick={() => setTab("mailmap")}
          >
            .mailmap {mailmap && mailmap.has_override ? "(override)" : ""}
          </button>
        </div>

        <div className="modal-body">
          {error && <p className="form-error">{error}</p>}
          {notice && <p className="form-notice">{notice}</p>}

          {tab === "identities" && (
            <>
              <div className="picker-toolbar">
                <span className="muted">
                  {identities.length} raw identities · {groups} resolved authors ·{" "}
                  {fmtInt(totalCommits)} commits
                </span>
                <div className="spacer" />
                <span className="badge badge-info">{selectedRows.length} checked</span>
                <button
                  className="btn btn-primary"
                  disabled={selectedRows.length < 2 || busy}
                  onClick={applyMerge}
                >
                  Merge selected
                </button>
              </div>
              <p className="hint">
                Tick two or more identities, choose the canonical one with the
                radio button, then merge. Merges are applied after the
                repository .mailmap and affect every metric.
              </p>

              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th className="narrow"></th>
                      <th className="narrow" title="Canonical identity">Canon</th>
                      <th>Raw identity</th>
                      <th>Resolves to</th>
                      <th className="right">Commits</th>
                      <th>Flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {identities.map((row) => (
                      <tr
                        key={row.raw}
                        className={checked.has(row.raw) ? "picked" : ""}
                        onClick={() => !row.manually_merged && toggleRow(row.raw)}
                      >
                        <td className="narrow">
                          <input
                            type="checkbox"
                            checked={checked.has(row.raw)}
                            disabled={row.manually_merged}
                            onChange={() => toggleRow(row.raw)}
                            onClick={(e) => e.stopPropagation()}
                          />
                        </td>
                        <td className="narrow">
                          <input
                            type="radio"
                            name="canonical"
                            checked={canonical === row.raw}
                            disabled={!checked.has(row.raw)}
                            onChange={() => setCanonical(row.raw)}
                            onClick={(e) => e.stopPropagation()}
                          />
                        </td>
                        <td className="mono ellipsis" title={row.raw}>{row.raw}</td>
                        <td className="ellipsis">
                          <span className="mono">
                            {row.effective_name} &lt;{row.effective_email}&gt;
                          </span>
                        </td>
                        <td className="right num">{fmtInt(row.commits)}</td>
                        <td>
                          {row.mailmapped && <span className="badge">mailmap</span>}{" "}
                          {row.manually_merged && (
                            <span className="badge badge-info">merged</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="merge-list">
                <div className="panel-head">
                  <h3>Manual merges ({merges.length})</h3>
                  <button
                    className="btn btn-ghost"
                    disabled={!merges.length || busy}
                    onClick={clearMerges}
                  >
                    Clear all
                  </button>
                </div>
                {merges.length ? (
                  <ul className="merge-entries">
                    {merges.map((m) => (
                      <li key={`${m.alias_name}|${m.alias_email}|${m.canonical_email}`}>
                        <span className="mono">
                          {m.alias_name} &lt;{m.alias_email}&gt;
                        </span>
                        <span className="arrow">→</span>
                        <span className="mono">
                          {m.canonical_name} &lt;{m.canonical_email}&gt;
                        </span>
                        <button
                          className="icon-btn"
                          title="Remove this merge"
                          disabled={busy}
                          onClick={() => removeMerge(m)}
                        >
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="hint">No manual merges yet.</p>
                )}
              </div>
            </>
          )}

          {tab === "mailmap" && (
            <>
              <p className="muted">
                Status:{" "}
                {mailmap && mailmap.has_override ? (
                  <span className="badge badge-info">custom override active</span>
                ) : (
                  <span className="badge">using the repository's own .mailmap</span>
                )}{" "}
                — overrides replace the file-based mailmap entirely.
              </p>
              <label className="field-group">
                <span className="field-label">Effective .mailmap (editable)</span>
                <textarea
                  className="mono mailmap-editor"
                  rows={14}
                  spellCheck={false}
                  placeholder="(empty — the repository .mailmap is used)"
                  value={overrideText}
                  onChange={(e) => setOverrideText(e.target.value)}
                  disabled={busy}
                />
              </label>
              <div className="sidebar-actions row-actions">
                <button className="btn btn-primary" disabled={busy} onClick={saveMailmap}>
                  Save override
                </button>
                <button
                  className="btn"
                  disabled={busy || !mailmap}
                  onClick={() => setOverrideText((mailmap && mailmap.repo_text) || "")}
                >
                  Load repo file into editor
                </button>
                <button
                  className="btn btn-ghost"
                  disabled={busy}
                  onClick={() => {
                    setOverrideText("");
                    setNotice(
                      "Editor cleared — press “Save override” to apply (an empty value falls back to the repository .mailmap)."
                    );
                  }}
                >
                  Clear override
                </button>
              </div>
              <p className="hint">
                “Clear override” + Save reverts to the repository file if it has
                one. Mailmap uses the same syntax as git:{" "}
                <span className="mono">Proper Name &lt;commit@email&gt;</span>.
              </p>

              <details className="repo-mailmap">
                <summary>
                  Repository .mailmap file{" "}
                  {mailmap
                    ? `(${fmtInt((mailmap.repo_text || "").length)} bytes)`
                    : ""}
                </summary>
                <pre className="code-block">
                  {(mailmap && mailmap.repo_text) || "(no .mailmap file in this repository)"}
                </pre>
              </details>
            </>
          )}
        </div>

        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose} disabled={busy}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
