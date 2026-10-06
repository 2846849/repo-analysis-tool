// Small value formatters shared by the dashboard tables and cards.

export function fmtInt(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return Number(value).toLocaleString("en-US");
}

export function fmtNum(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 3 });
}

export function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return `${(Number(value) * 100).toLocaleString("en-US", {
    maximumFractionDigits: 1,
  })}%`;
}

export function fmtDate(iso) {
  return iso ? String(iso).slice(0, 10) : "–";
}

export function fmtDateTime(iso) {
  if (!iso) return "–";
  return String(iso).replace("T", " ").replace("Z", " UTC");
}

export function shortSha(sha, length = 10) {
  return sha ? String(sha).slice(0, length) : "";
}
