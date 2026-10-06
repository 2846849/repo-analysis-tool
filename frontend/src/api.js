// Thin fetch wrappers around the FastAPI backend.

async function parse(resp) {
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const data = await resp.json();
      if (data && data.detail !== undefined) {
        detail = typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail);
      }
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return resp.json();
}

function toQuery(params) {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      q.set(key, String(value));
    }
  }
  return q.toString();
}

export const api = {
  listRepos: () => fetch("/api/repos").then(parse),

  cloneRepo: (url, name) =>
    fetch("/api/repos/clone", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, name: name || null }),
    }).then(parse),

  uploadRepo: (file, name) => {
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    return fetch("/api/repos/upload", { method: "POST", body: form }).then(parse);
  },

  deleteRepo: (repoId) =>
    fetch(`/api/repos/${repoId}`, { method: "DELETE" }).then(parse),

  authors: (repoId, ref = "HEAD") =>
    fetch(`/api/repos/${repoId}/authors?ref=${encodeURIComponent(ref)}`).then(parse),

  getMailmap: (repoId) => fetch(`/api/repos/${repoId}/mailmap`).then(parse),

  putMailmap: (repoId, text) =>
    fetch(`/api/repos/${repoId}/mailmap`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).then(parse),

  getMerges: (repoId) => fetch(`/api/repos/${repoId}/merges`).then(parse),

  putMerges: (repoId, merges) =>
    fetch(`/api/repos/${repoId}/merges`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ merges }),
    }).then(parse),

  commits: (repoId, { ref = "HEAD", q = "", limit = 100, offset = 0 } = {}) =>
    fetch(`/api/repos/${repoId}/commits?${toQuery({ ref, q, limit, offset })}`)
      .then(parse),

  paths: (repoId, q = "", limit = 50, ref = "HEAD") =>
    fetch(`/api/repos/${repoId}/paths?${toQuery({ ref, q, limit })}`).then(parse),

  analyze: (repoId, body) =>
    fetch(`/api/repos/${repoId}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(parse),
};

export function exportUrl(repoId, { ref, since, until, author, hashes }) {
  const query = toQuery({
    ref: ref || "HEAD",
    since,
    until,
    author,
    hashes: hashes && hashes.length ? hashes.join(",") : "",
  });
  return `/api/repos/${repoId}/export.csv?${query}`;
}
