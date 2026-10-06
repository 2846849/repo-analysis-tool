import { fmtInt } from "../format";

// Lightweight CSS bar chart of commit activity per bucket. Each bar carries
// a native tooltip with date, commits and churn.
export default function ActivityChart({ activity }) {
  const points = (activity && activity.points) || [];
  if (!points.length) {
    return <p className="hint">No activity in this commit set.</p>;
  }
  const max = Math.max(...points.map((p) => p.commits), 1);
  return (
    <div className="chart-wrap">
      <div className="chart-bars">
        {points.map((p) => (
          <div key={p.start} className="chart-bar-slot">
            <div
              className="chart-bar"
              style={{ height: `${Math.max(2, (p.commits / max) * 100)}%` }}
              title={`${String(p.date).slice(0, 10)} · ${fmtInt(p.commits)} commits · churn ${fmtInt(p.churn)}`}
            />
          </div>
        ))}
      </div>
      <div className="chart-axis">
        <span>{String(points[0].date).slice(0, 10)}</span>
        <span className="badge" title="activity bucket granularity">
          {activity.bucket} · max {fmtInt(max)} commits
        </span>
        <span>{String(points[points.length - 1].date).slice(0, 10)}</span>
      </div>
    </div>
  );
}
