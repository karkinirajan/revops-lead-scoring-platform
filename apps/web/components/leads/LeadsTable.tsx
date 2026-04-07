"use client";

import { useState, useCallback } from "react";
import { TierBadge } from "@/components/ui/TierBadge";
import { ScoreBar } from "@/components/ui/ScoreBar";
import { getLeads } from "@/lib/api";
import type { PaginatedResponse, PriorityTier, RankedLead } from "@/lib/types";
import { formatDistanceToNow } from "date-fns";

const TIERS: PriorityTier[] = ["HOT", "WARM", "COOL", "COLD"];

export function LeadsTable({ initialData }: { initialData: PaginatedResponse<RankedLead> }) {
  const [data, setData] = useState(initialData);
  const [page, setPage] = useState(1);
  const [tier, setTier] = useState<string>("");
  const [minScore, setMinScore] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (p: number, t: string, ms: string) => {
      setLoading(true);
      try {
        const result = await getLeads({
          page: p,
          page_size: 50,
          priority_tier: t || undefined,
          min_score: ms ? Number(ms) : undefined,
        });
        setData(result);
        setPage(p);
      } catch {
        // keep existing data
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  function handleTier(t: string) {
    const next = tier === t ? "" : t;
    setTier(next);
    load(1, next, minScore);
  }

  function handleMinScore(v: string) {
    setMinScore(v);
    load(1, tier, v);
  }

  function exportCsv() {
    const rows = [
      ["Email", "Name", "Company", "Score", "Tier", "Action", "Scored At"],
      ...data.items.map((l) => [
        l.email,
        l.full_name,
        l.company_name ?? "",
        String(l.lead_score),
        l.priority_tier,
        l.recommended_action ?? "",
        l.scored_at,
      ]),
    ];
    const csv = rows.map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `leads_p${page}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        {/* Tier filters */}
        <div className="flex gap-1.5">
          {TIERS.map((t) => (
            <button
              key={t}
              onClick={() => handleTier(t)}
              className="px-3 py-1 rounded-full text-xs font-semibold border transition-colors"
              style={{
                background: tier === t ? "var(--surface-overlay)" : "transparent",
                borderColor: tier === t ? "var(--border)" : "var(--border-muted)",
                color: tier === t ? "var(--text)" : "var(--text-muted)",
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Min score */}
        <div className="flex items-center gap-1.5">
          <label className="text-xs" style={{ color: "var(--text-muted)" }}>
            Min score
          </label>
          <input
            type="number"
            min={0}
            max={100}
            value={minScore}
            onChange={(e) => handleMinScore(e.target.value)}
            className="w-16 px-2 py-1 rounded text-xs border"
            style={{
              background: "var(--surface-raised)",
              borderColor: "var(--border)",
              color: "var(--text)",
            }}
            placeholder="0"
          />
        </div>

        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs" style={{ color: "var(--text-faint)" }}>
            {data.total.toLocaleString()} results
          </span>
          <button
            onClick={exportCsv}
            className="text-xs px-3 py-1.5 rounded border transition-colors"
            style={{
              borderColor: "var(--border)",
              color: "var(--text-muted)",
              background: "transparent",
            }}
          >
            Export CSV
          </button>
        </div>
      </div>

      {/* Table */}
      <div
        className="rounded-xl border overflow-hidden"
        style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Contact", "Company", "Tier", "Score", "Action", "Scored"].map((h) => (
                  <th
                    key={h}
                    className="text-left px-5 py-3 text-xs font-medium"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className={loading ? "opacity-50" : ""}>
              {data.items.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-5 py-12 text-center text-sm"
                    style={{ color: "var(--text-muted)" }}
                  >
                    No leads match the current filters.
                  </td>
                </tr>
              ) : (
                data.items.map((lead) => (
                  <tr
                    key={lead.contact_id}
                    className="border-b last:border-0 hover:bg-[var(--surface-overlay)] transition-colors"
                    style={{ borderColor: "var(--border-muted)" }}
                  >
                    <td className="px-5 py-3">
                      <div className="font-medium" style={{ color: "var(--text)" }}>
                        {lead.full_name}
                      </div>
                      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                        {lead.email}
                      </div>
                      {lead.job_title && (
                        <div className="text-xs" style={{ color: "var(--text-faint)" }}>
                          {lead.job_title}
                        </div>
                      )}
                    </td>
                    <td className="px-5 py-3 text-xs" style={{ color: "var(--text-muted)" }}>
                      <div>{lead.company_name ?? "—"}</div>
                      {lead.company_size_tier && (
                        <div
                          className="text-[10px] capitalize mt-0.5"
                          style={{ color: "var(--text-faint)" }}
                        >
                          {lead.company_size_tier.replace(/_/g, " ")}
                        </div>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      <TierBadge tier={lead.priority_tier} />
                    </td>
                    <td className="px-5 py-3 w-36">
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
                    <td className="px-5 py-3 text-xs whitespace-nowrap" style={{ color: "var(--text-faint)" }}>
                      {formatDistanceToNow(new Date(lead.scored_at), { addSuffix: true })}
                      {lead.synced_to_hubspot_at && (
                        <div className="flex items-center gap-1 mt-0.5" style={{ color: "var(--green)" }}>
                          <span className="w-1.5 h-1.5 rounded-full bg-current" />
                          synced
                        </div>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {data.pages > 1 && (
          <div
            className="flex items-center justify-between px-5 py-3 border-t text-xs"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            <span>
              Page {page} of {data.pages}
            </span>
            <div className="flex gap-2">
              <button
                disabled={page <= 1 || loading}
                onClick={() => load(page - 1, tier, minScore)}
                className="px-3 py-1.5 rounded border disabled:opacity-40 transition-colors"
                style={{ borderColor: "var(--border)", background: "transparent" }}
              >
                ← Prev
              </button>
              <button
                disabled={page >= data.pages || loading}
                onClick={() => load(page + 1, tier, minScore)}
                className="px-3 py-1.5 rounded border disabled:opacity-40 transition-colors"
                style={{ borderColor: "var(--border)", background: "transparent" }}
              >
                Next →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
