import { useState } from "react";

import { fmtDateTime, fmtInt, fmtNum, fmtPct } from "../format";
import ActivityChart from "./ActivityChart";
import DataTable from "./DataTable";

function MetricCards({ metrics }) {
  const cards = [
    ["Added", fmtInt(metrics.added)],
    ["Removed", fmtInt(metrics.removed)],
    ["Growth", fmtInt(metrics.growth)],
    ["Churn", fmtInt(metrics.churn)],
    ["Modifications", fmtInt(metrics.modifications)],
    ["Mod. frequency", fmtNum(metrics.modification_frequency)],
    ["Churn rate", fmtNum(metrics.churn_rate)],
  ];
  return (
    <div className="cards">
      {cards.map(([label, value]) => (
        <div className="card" key={label}>
          <span className="card-label">{label}</span>
          <span className="card-value">{value}</span>
        </div>
      ))}
    </div>
  );
}

const intCol = (key, label, get, extra = {}) => ({
  key,
  label,
  align: "right",
  sortValue: get,
  render: (row) => fmtInt(get(row)),
  ...extra,
});

const floatCol = (key, label, get) => ({
  key,
  label,
  align: "right",
  sortValue: get,
  render: (row) => fmtNum(get(row)),
});

const pctCol = (key, label, get) => ({
  key,
  label,
  align: "right",
  sortValue: get,
  render: (row) => fmtPct(get(row)),
});

const authorColumns = [
  {
    key: "author",
    label: "Author",
    render: (row) => <span className="mono">{row.author}</span>,
  },
  intCol("commits", "Commits", (r) => r.commits),
  intCol("added", "Added", (r) => r.added),
  intCol("removed", "Removed", (r) => r.removed),
  intCol("growth", "Growth", (r) => r.growth),
  intCol("churn", "Churn", (r) => r.churn),
  intCol("modifications", "Mods", (r) => r.modifications),
  pctCol("ownership", "Ownership", (r) => r.ownership),
];

const fileColumns = [
  {
    key: "path",
    label: "File",
    render: (row) => <span className="mono">{row.path}</span>,
  },
  intCol("f_added", "Added", (r) => r.metrics.added),
  intCol("f_removed", "Removed", (r) => r.metrics.removed),
  intCol("f_growth", "Growth", (r) => r.metrics.growth),
  intCol("f_churn", "Churn", (r) => r.metrics.churn),
  intCol("f_mods", "Mods", (r) => r.metrics.modifications),
  floatCol("f_freq", "Mod freq", (r) => r.metrics.modification_frequency),
  floatCol("f_rate", "Churn rate", (r) => r.metrics.churn_rate),
  intCol("f_authors", "Authors", (r) => r.authors),
  {
    key: "main_author",
    label: "Main author",
    render: (row) => <span className="mono">{row.main_author || "–"}</span>,
  },
  pctCol("main_ownership", "Main %", (r) => r.main_ownership),
  {
    key: "last_change",
    label: "Last change",
    render: (row) => fmtDateTime(row.last_change),
    sortValue: (row) => row.last_change || "",
  },
];

const dirColumns = [
  {
    key: "path",
    label: "Directory",
    render: (row) => <span className="mono">{row.path}</span>,
  },
  intCol("d_files", "Files", (r) => r.files),
  intCol("d_authors", "Authors", (r) => r.authors),
  intCol("d_added", "Added", (r) => r.metrics.added),
  intCol("d_removed", "Removed", (r) => r.metrics.removed),
  intCol("d_growth", "Growth", (r) => r.metrics.growth),
  intCol("d_churn", "Churn", (r) => r.metrics.churn),
  intCol("d_mods", "Mods", (r) => r.metrics.modifications),
  floatCol("d_freq", "Mod freq", (r) => r.metrics.modification_frequency),
  floatCol("d_rate", "Churn rate", (r) => r.metrics.churn_rate),
  {
    key: "d_main_author",
    label: "Main author",
    render: (row) => <span className="mono">{row.main_author || "–"}</span>,
  },
  pctCol("d_main_ownership", "Main %", (r) => r.main_ownership),
  {
    key: "d_last_change",
    label: "Last change",
    render: (row) => fmtDateTime(row.last_change),
    sortValue: (row) => row.last_change || "",
  },
];

// Main results view: scope summary + metric cards, activity chart and the
// authors / files / directories tabs.
export default function Dashboard({ analysis, onPath }) {
  const [tab, setTab] = useState("authors");
  const { repository, object, commit_set: commitSet, activity } = analysis;

  const scopeTitle =
    object.kind === "repository"
      ? "Repository overview"
      : object.kind === "file"
        ? `File · ${object.path}`
        : `Directory · ${object.path}`;

  return (
    <div className="dashboard">
      <section className="panel">
        <div className="panel-head">
          <h2>{scopeTitle}</h2>
          <span className="badge">{object.kind}</span>
          {object.last_change && (
            <span className="muted">last change {fmtDateTime(object.last_change)}</span>
          )}
        </div>
        <MetricCards metrics={object.metrics} />
        <div className="meta-row">
          <span>
            Commit set: <b>{fmtInt(commitSet.size)}</b> commits · {commitSet.mode}
          </span>
          <span>
            {fmtDateTime(commitSet.first_commit_at)} → {fmtDateTime(commitSet.last_commit_at)}
          </span>
          {commitSet.author_commits !== null && commitSet.author_commits !== undefined && (
            <span>
              author's commits in set: <b>{fmtInt(commitSet.author_commits)}</b>
            </span>
          )}
        </div>
        <div className="meta-row">
          <span>Files changed: <b>{fmtInt(repository.files)}</b></span>
          <span>Directories changed: <b>{fmtInt(repository.directories)}</b></span>
          <span>Authors with churn: <b>{fmtInt(repository.authors)}</b></span>
          <span>Distinct identities: <b>{fmtInt(repository.distinct_authors_total)}</b></span>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Activity</h2>
          <span className="muted">commits per {activity.bucket}</span>
        </div>
        <ActivityChart activity={activity} />
      </section>

      <section className="panel">
        <div className="tabs">
          <button
            className={tab === "authors" ? "tab active" : "tab"}
            onClick={() => setTab("authors")}
          >
            Authors ({analysis.authors.length})
          </button>
          <button
            className={tab === "files" ? "tab active" : "tab"}
            onClick={() => setTab("files")}
          >
            Files ({fmtInt(analysis.files.length)} of {fmtInt(analysis.files_total)})
          </button>
          <button
            className={tab === "directories" ? "tab active" : "tab"}
            onClick={() => setTab("directories")}
          >
            Directories ({fmtInt(analysis.directories.length)} of{" "}
            {fmtInt(analysis.directories_total)})
          </button>
        </div>

        {tab === "authors" && (
          <DataTable
            columns={authorColumns}
            rows={analysis.authors}
            initialSort={{ key: "churn", dir: "desc" }}
            emptyText="No authors in this commit set."
          />
        )}
        {tab === "files" && (
          <DataTable
            columns={fileColumns}
            rows={analysis.files}
            initialSort={{ key: "f_churn", dir: "desc" }}
            onRowClick={(row) => onPath(row.path)}
            emptyText="No file changes in this commit set."
          />
        )}
        {tab === "directories" && (
          <DataTable
            columns={dirColumns}
            rows={analysis.directories}
            initialSort={{ key: "d_churn", dir: "desc" }}
            onRowClick={(row) => onPath(row.path)}
            emptyText="No directory changes in this commit set."
          />
        )}
        {tab !== "authors" && (
          <p className="hint">
            Showing top {fmtInt(tab === "files" ? analysis.files.length : analysis.directories.length)} rows
            (increase “Top rows” in the sidebar for more) · click a row to scope the whole
            analysis to it.
          </p>
        )}
      </section>
    </div>
  );
}
