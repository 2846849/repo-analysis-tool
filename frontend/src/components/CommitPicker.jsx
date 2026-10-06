import { useEffect, useState } from "react";

import { api } from "../api";
import { fmtDate, fmtInt, shortSha } from "../format";

const PAGE = 100;

// Modal for building a manual commit set: searchable, paginated commit list
// with checkboxes. Selections are kept across pages / searches until Apply.
export default function CommitPicker({ repoId, initialSelected, onApply, onClose }) {
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(() => new Set(initialSelected || []));

  useEffect(() => {
    let cancelled = false;
    const handle = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.commits(repoId, {
          q: q.trim(),
          limit: PAGE,
          offset,
        });
        if (!cancelled) setItems(data.items);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [repoId, q, offset]);

  function toggle(hash) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(hash)) next.delete(hash);
      else next.add(hash);
      return next;
    });
  }

  const pageAllSelected =
    items.length > 0 && items.every((item) => selected.has(item.hash));

  function togglePage() {
    setSelected((prev) => {
      const next = new Set(prev);
      if (pageAllSelected) {
        for (const item of items) next.delete(item.hash);
      } else {
        for (const item of items) next.add(item.hash);
      }
      return next;
    });
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal modal-wide">
        <div className="modal-head">
          <h2>Choose commits</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="picker-toolbar">
          <input
            type="search"
            placeholder="Search hash / author / subject…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
            autoFocus
          />
          <span className="badge badge-info">{selected.size} selected</span>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setSelected(new Set())}
            disabled={!selected.size}
          >
            Clear selection
          </button>
        </div>

        {error && <p className="form-error">{error}</p>}

        <div className="modal-body picker-body">
          <table className="data-table picker-table">
            <thead>
              <tr>
                <th className="narrow">
                  <input
                    type="checkbox"
                    checked={pageAllSelected}
                    onChange={togglePage}
                    title="Select all on this page"
                  />
                </th>
                <th>Commit</th>
                <th>Date</th>
                <th>Author</th>
                <th>Subject</th>
                <th className="right">Churn</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.hash}
                  className={selected.has(item.hash) ? "picked" : ""}
                  onClick={() => toggle(item.hash)}
                >
                  <td className="narrow">
                    <input
                      type="checkbox"
                      checked={selected.has(item.hash)}
                      onChange={() => toggle(item.hash)}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td className="mono">{shortSha(item.hash)}</td>
                  <td>{fmtDate(item.committer_date)}</td>
                  <td className="ellipsis">{item.author}</td>
                  <td className="ellipsis" title={item.subject}>{item.subject}</td>
                  <td className="right num">
                    +{fmtInt(item.added)} −{fmtInt(item.removed)}
                  </td>
                </tr>
              ))}
              {!loading && !items.length && (
                <tr>
                  <td className="empty" colSpan={6}>No commits match the search.</td>
                </tr>
              )}
            </tbody>
          </table>
          {loading && <p className="hint">Loading commits…</p>}
        </div>

        <div className="modal-foot picker-foot">
          <span className="muted">
            showing {offset + 1}–{offset + items.length}
          </span>
          <div className="spacer" />
          <button
            className="btn"
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
            disabled={offset === 0 || loading}
          >
            ‹ Prev
          </button>
          <button
            className="btn"
            onClick={() => setOffset(offset + PAGE)}
            disabled={items.length < PAGE || loading}
          >
            Next ›
          </button>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button
            className="btn btn-primary"
            onClick={() => onApply([...selected])}
          >
            Apply selection
          </button>
        </div>
      </div>
    </div>
  );
}
