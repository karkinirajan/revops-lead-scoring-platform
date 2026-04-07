import type { ScoringRun } from "@/lib/types";
import { TriggerRunButton } from "@/components/dashboard/TriggerRunButton";
import { formatDistanceToNow, format } from "date-fns";

const API = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

async function getRuns(): Promise<ScoringRun[]> {
  try {
    const res = await fetch(`${API}/api/v1/scoring/runs?limit=50`, { next: { revalidate: 15 } });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

const STATUS_COLORS: Record<string, string> = {
  completed: "var(--green)",
  running: "var(--primary)",
  failed: "var(--red)",
  partial: "var(--yellow)",
  pending: "var(--text-faint)",
};

export default async function RunsPage() {
  const runs = await getRuns();

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>Run History</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
            {runs.length} recent scoring runs
          </p>
        </div>
        <TriggerRunButton />
      </div>

      <div className="rounded-xl border overflow-hidden" style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}>
        {runs.length === 0 ? (
          <div className="px-5 py-16 text-center text-sm" style={{ color: "var(--text-muted)" }}>
            No scoring runs yet. Click "Run Scoring" to start one.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Status", "Model", "Contacts", "Errors", "Duration", "Started", "Triggered by"].map((h) => (
                  <th key={h} className="text-left px-5 py-3 text-xs font-medium" style={{ color: "var(--text-muted)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-b last:border-0" style={{ borderColor: "var(--border-muted)" }}>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full" style={{ background: STATUS_COLORS[run.status] ?? "var(--text-faint)" }} />
                      <span className="text-xs capitalize" style={{ color: "var(--text)" }}>{run.status}</span>
                    </div>
                  </td>
                  <td className="px-5 py-3 font-mono text-xs" style={{ color: "var(--text)" }}>
                    v{run.model_version}
                    {run.is_shadow && (
                      <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded" style={{ background: "rgba(99,102,241,0.15)", color: "var(--primary)" }}>
                        shadow
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-xs tabular-nums" style={{ color: "var(--text)" }}>
                    <span style={{ color: "var(--green)" }}>{run.scored_count.toLocaleString()}</span>
                    <span style={{ color: "var(--text-faint)" }}> / {run.total_contacts.toLocaleString()}</span>
                  </td>
                  <td className="px-5 py-3 text-xs tabular-nums" style={{ color: run.error_count > 0 ? "var(--red)" : "var(--text-faint)" }}>
                    {run.error_count}
                  </td>
                  <td className="px-5 py-3 text-xs tabular-nums" style={{ color: "var(--text-muted)" }}>
                    {run.duration_seconds != null ? `${run.duration_seconds.toFixed(1)}s` : "—"}
                  </td>
                  <td className="px-5 py-3 text-xs" style={{ color: "var(--text-muted)" }}>
                    <div>{format(new Date(run.started_at), "MMM d, HH:mm")}</div>
                    <div style={{ color: "var(--text-faint)" }}>{formatDistanceToNow(new Date(run.started_at), { addSuffix: true })}</div>
                  </td>
                  <td className="px-5 py-3 text-xs" style={{ color: "var(--text-faint)" }}>
                    {run.triggered_by ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
