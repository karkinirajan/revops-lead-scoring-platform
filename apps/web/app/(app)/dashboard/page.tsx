import { StatCard } from "@/components/ui/StatCard";
import { TierBadge } from "@/components/ui/TierBadge";
import { ScoreBar } from "@/components/ui/ScoreBar";
import { TriggerRunButton } from "@/components/dashboard/TriggerRunButton";
import type { PriorityTier, RankedLead, ScoringRun } from "@/lib/types";
import { formatDistanceToNow } from "date-fns";

const API = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

async function getDashboardData() {
  try {
    const [leadsRes, runsRes] = await Promise.all([
      fetch(`${API}/api/v1/scoring/leads?page_size=5&priority_tier=HOT`, {
        next: { revalidate: 60 },
      }),
      fetch(`${API}/api/v1/scoring/runs?limit=5`, {
        next: { revalidate: 60 },
      }),
    ]);

    const [leads, runs] = await Promise.all([
      leadsRes.ok ? leadsRes.json() : { items: [], total: 0 },
      runsRes.ok ? runsRes.json() : [],
    ]);

    const allLeadsRes = await fetch(
      `${API}/api/v1/scoring/leads?page_size=1`,
      { next: { revalidate: 60 } },
    );
    const allLeads = allLeadsRes.ok ? await allLeadsRes.json() : { total: 0 };

    return { leads, runs, total: allLeads.total };
  } catch {
    return { leads: { items: [], total: 0 }, runs: [], total: 0 };
  }
}

export default async function DashboardPage() {
  const { leads, runs, total } = await getDashboardData();

  const hotCount: number = leads.total ?? 0;
  const lastRun: ScoringRun | null = runs[0] ?? null;
  const topLeads: RankedLead[] = leads.items ?? [];

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
            Dashboard
          </h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
            Pipeline health and top lead activity
          </p>
        </div>
        <TriggerRunButton />
      </div>

      {/* KPI Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Total Leads Scored"
          value={total.toLocaleString()}
          sub="all time"
        />
        <StatCard
          label="HOT Leads"
          value={hotCount.toLocaleString()}
          accent="var(--hot)"
          sub="score ≥ 75"
        />
        <StatCard
          label="Last Run Duration"
          value={lastRun?.duration_seconds ? `${lastRun.duration_seconds.toFixed(1)}s` : "—"}
          sub={
            lastRun?.started_at
              ? formatDistanceToNow(new Date(lastRun.started_at), { addSuffix: true })
              : "no runs yet"
          }
        />
        <StatCard
          label="Model Version"
          value={lastRun?.model_version ?? "—"}
          sub={lastRun ? `${lastRun.scored_count.toLocaleString()} contacts` : "no run yet"}
        />
      </div>

      {/* Two-column lower section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top HOT leads */}
        <section
          className="rounded-xl border overflow-hidden"
          style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
        >
          <div
            className="flex items-center justify-between px-5 py-4 border-b"
            style={{ borderColor: "var(--border)" }}
          >
            <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              Top HOT Leads
            </h2>
            <a
              href="/leads?tier=HOT"
              className="text-xs"
              style={{ color: "var(--primary)" }}
            >
              View all →
            </a>
          </div>
          {topLeads.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm" style={{ color: "var(--text-muted)" }}>
              No HOT leads yet. Run a scoring pass first.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["Contact", "Company", "Score", "Action"].map((h) => (
                    <th
                      key={h}
                      className="text-left px-5 py-2.5 text-xs font-medium"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {topLeads.map((lead) => (
                  <tr
                    key={lead.contact_id}
                    className="border-b last:border-0"
                    style={{ borderColor: "var(--border-muted)" }}
                  >
                    <td className="px-5 py-3">
                      <div className="font-medium text-xs" style={{ color: "var(--text)" }}>
                        {lead.full_name}
                      </div>
                      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                        {lead.email}
                      </div>
                    </td>
                    <td className="px-5 py-3 text-xs" style={{ color: "var(--text-muted)" }}>
                      {lead.company_name ?? "—"}
                    </td>
                    <td className="px-5 py-3 w-32">
                      <ScoreBar score={lead.lead_score} />
                    </td>
                    <td className="px-5 py-3">
                      <span
                        className="text-xs px-2 py-0.5 rounded"
                        style={{ background: "var(--surface-overlay)", color: "var(--text-muted)" }}
                      >
                        {lead.recommended_action?.replace(/_/g, " ") ?? "—"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* Recent runs */}
        <section
          className="rounded-xl border overflow-hidden"
          style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
        >
          <div
            className="flex items-center justify-between px-5 py-4 border-b"
            style={{ borderColor: "var(--border)" }}
          >
            <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              Recent Scoring Runs
            </h2>
            <a href="/runs" className="text-xs" style={{ color: "var(--primary)" }}>
              View all →
            </a>
          </div>
          {(runs as ScoringRun[]).length === 0 ? (
            <div className="px-5 py-8 text-center text-sm" style={{ color: "var(--text-muted)" }}>
              No runs yet.
            </div>
          ) : (
            <div className="divide-y" style={{ borderColor: "var(--border-muted)" }}>
              {(runs as ScoringRun[]).map((run) => (
                <div key={run.id} className="px-5 py-3 flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <RunStatusDot status={run.status} />
                      <span className="text-xs font-medium" style={{ color: "var(--text)" }}>
                        v{run.model_version}
                      </span>
                      {run.is_shadow && (
                        <span
                          className="text-[10px] px-1.5 py-0.5 rounded"
                          style={{ background: "rgba(99,102,241,0.15)", color: "var(--primary)" }}
                        >
                          shadow
                        </span>
                      )}
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                      {run.scored_count.toLocaleString()} / {run.total_contacts.toLocaleString()} contacts
                      {run.duration_seconds != null && ` · ${run.duration_seconds.toFixed(1)}s`}
                    </div>
                  </div>
                  <div className="text-xs" style={{ color: "var(--text-faint)" }}>
                    {formatDistanceToNow(new Date(run.started_at), { addSuffix: true })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function RunStatusDot({ status }: { status: ScoringRun["status"] }) {
  const colors: Record<string, string> = {
    completed: "var(--green)",
    running: "var(--primary)",
    failed: "var(--red)",
    partial: "var(--yellow)",
    pending: "var(--text-faint)",
  };
  return (
    <span
      className="w-2 h-2 rounded-full inline-block"
      style={{ background: colors[status] ?? "var(--text-faint)" }}
    />
  );
}
