import { useMemo, useState } from "react";

// Generic sortable table. Columns: { key, label, align, render(row),
// sortValue(row), defaultDir }. Rows may carry path/author keys for React.
export default function DataTable({
  columns,
  rows,
  initialSort,
  onRowClick,
  emptyText = "No rows.",
}) {
  const [sort, setSort] = useState(initialSort || null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col || !col.sortValue) return rows;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const va = col.sortValue(a);
      const vb = col.sortValue(b);
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (typeof va === "string" || typeof vb === "string") {
        return String(va).localeCompare(String(vb)) * dir;
      }
      return va < vb ? -dir : dir;
    });
  }, [rows, sort, columns]);

  function clickHeader(col) {
    if (!col.sortValue) return;
    setSort((prev) => {
      if (prev && prev.key === col.key) {
        return { key: col.key, dir: prev.dir === "asc" ? "desc" : "asc" };
      }
      return { key: col.key, dir: col.defaultDir || "desc" };
    });
  }

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={[
                  c.align === "right" ? "right" : "",
                  c.sortValue ? "sortable" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => clickHeader(c)}
              >
                {c.label}
                {sort && sort.key === c.key ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, index) => (
            <tr
              key={row.path ?? row.author ?? index}
              className={[
                onRowClick ? "clickable" : "",
                row.path === undefined && row.picked ? "picked" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((c) => (
                <td key={c.key} className={c.align === "right" ? "right num" : ""}>
                  {c.render ? c.render(row) : row[c.key]}
                </td>
              ))}
            </tr>
          ))}
          {!sorted.length && (
            <tr>
              <td className="empty" colSpan={columns.length}>{emptyText}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
