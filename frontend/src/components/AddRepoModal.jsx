import { useState } from "react";

import { api } from "../api";

// Modal for adding a repository: clone a remote URL or upload a zip that
// contains a .git directory (or .git file).
export default function AddRepoModal({ onClose, onCreated }) {
  const [tab, setTab] = useState("clone");
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setError(null);
    if (tab === "clone" && !url.trim()) {
      setError("Enter a repository URL (https:// or git@…).");
      return;
    }
    if (tab === "upload" && !file) {
      setError("Choose a zip archive first.");
      return;
    }
    setBusy(true);
    try {
      const repo =
        tab === "clone"
          ? await api.cloneRepo(url.trim(), name.trim())
          : await api.uploadRepo(file, name.trim());
      onCreated(repo);
    } catch (err) {
      setError(err.message);
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
      <div className="modal">
        <div className="modal-head">
          <h2>Add repository</h2>
          <button className="icon-btn" onClick={onClose} disabled={busy} aria-label="Close">
            ×
          </button>
        </div>

        <div className="radio-tabs">
          <button
            type="button"
            className={tab === "clone" ? "radio-tab active" : "radio-tab"}
            onClick={() => setTab("clone")}
          >
            Clone from URL
          </button>
          <button
            type="button"
            className={tab === "upload" ? "radio-tab active" : "radio-tab"}
            onClick={() => setTab("upload")}
          >
            Upload zip
          </button>
        </div>

        <form onSubmit={submit} className="modal-body">
          {tab === "clone" ? (
            <label className="field-group">
              <span className="field-label">Repository URL</span>
              <input
                type="text"
                placeholder="https://github.com/user/repo.git"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={busy}
                autoFocus
              />
            </label>
          ) : (
            <label className="field-group">
              <span className="field-label">Zip archive (must contain .git)</span>
              <input
                type="file"
                accept=".zip,application/zip"
                onChange={(e) => setFile(e.target.files && e.target.files[0])}
                disabled={busy}
              />
            </label>
          )}

          <label className="field-group">
            <span className="field-label">Display name (optional)</span>
            <input
              type="text"
              placeholder={tab === "clone" ? "derived from URL" : "derived from file name"}
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
            />
          </label>

          {tab === "clone" && (
            <p className="hint">
              A full history clone is performed — large repositories can take a
              few minutes. Keep this window open until it finishes.
            </p>
          )}
          {error && <p className="form-error">{error}</p>}

          <div className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy
                ? tab === "clone"
                  ? "Cloning…"
                  : "Uploading…"
                : tab === "clone"
                  ? "Clone repository"
                  : "Upload repository"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
