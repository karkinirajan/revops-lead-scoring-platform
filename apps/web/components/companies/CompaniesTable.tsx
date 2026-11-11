"use client";

import { useState, useCallback, useRef } from "react";
import { ApiError, getCompanies } from "@/lib/api";
import { sizeTierLabel } from "@/lib/format";
import type { Company, PaginatedResponse } from "@/lib/types";

const SIZE_TIERS = ["smb", "mid_market", "enterprise"];

export function CompaniesTable({ initialData }: { initialData: PaginatedResponse<Company> }) {
  const [data, setData] = useState(initialData);
  const [page, setPage] = useState(1);
  const [sizeTier, setSizeTier] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0); // only the newest request may update the table: typing fires one per keystroke and answers can arrive out of order

  const load = useCallback(async (p: number, st: string, s: string) => {
    const mine = ++latest.current;
    setLoading(true);
    setError(null);
    try {
      const result = await getCompanies({ page: p, page_size: 50, size_tier: st || undefined, search: s || undefined });
      if (mine !== latest.current) return;
      setData(result);
      setPage(p);
    } catch (e) {
      if (mine === latest.current) setError(e instanceof ApiError ? e.message : "Could not load companies"); // the rows already shown are kept
    } finally {
      if (mine === latest.current) setLoading(false);
    }
  }, []);

  return (
    <div>
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Search companies…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); load(1, sizeTier, e.target.value); }}
          className="px-3 py-1.5 rounded-sm text-sm border w-56"
          style={{ background: "var(--surface-raised)", borderColor: "var(--border)", color: "var(--text)" }}
        />
        <div className="flex gap-1.5">
          {SIZE_TIERS.map((t) => (
            <button
              key={t}
              onClick={() => { const next = sizeTier === t ? "" : t; setSizeTier(next); load(1, next, search); }}
              className="px-3 py-1 rounded-full text-xs font-medium border transition-colors"
              style={{
                background: sizeTier === t ? "var(--surface-overlay)" : "transparent",
                borderColor: sizeTier === t ? "var(--border)" : "var(--border-muted)",
                color: sizeTier === t ? "var(--text)" : "var(--text-muted)",
              }}
            >
              {sizeTierLabel(t)}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs" style={{ color: "var(--text-faint)" }}>
          {data.total.toLocaleString()} companies
        </span>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-sm px-3 py-2 text-xs" style={{ background: "rgba(239,68,68,0.1)", color: "var(--red)" }}>
          {error}
        </div>
      )}

      <div className="rounded-xl border overflow-x-auto" style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Company", "Domain", "Industry", "Employees", "Tier", "Source"].map((h) => (
                <th key={h} className="text-left px-5 py-3 text-xs font-medium" style={{ color: "var(--text-muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className={loading ? "opacity-50" : ""}>
            {data.items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-5 py-12 text-center text-sm" style={{ color: "var(--text-muted)" }}>
                  No companies found.
                </td>
              </tr>
            ) : (
              data.items.map((co) => (
                <tr key={co.id} className="border-b last:border-0" style={{ borderColor: "var(--border-muted)" }}>
                  <td className="px-5 py-3 font-medium" style={{ color: "var(--text)" }}>{co.name}</td>
                  <td className="px-5 py-3 text-xs font-mono" style={{ color: "var(--text-muted)" }}>{co.domain ?? "—"}</td>
                  <td className="px-5 py-3 text-xs" style={{ color: "var(--text-muted)" }}>{co.industry ?? "—"}</td>
                  <td className="px-5 py-3 text-xs tabular-nums" style={{ color: "var(--text-muted)" }}>
                    {co.employee_count ? co.employee_count.toLocaleString() : "—"}
                  </td>
                  <td className="px-5 py-3">
                    {co.size_tier ? (
                      <span className="text-xs px-2 py-0.5 rounded-sm" style={{ background: "var(--surface-overlay)", color: "var(--text-muted)" }}>
                        {sizeTierLabel(co.size_tier)}
                      </span>
                    ) : "—"}
                  </td>
                  <td className="px-5 py-3 text-xs" style={{ color: "var(--text-faint)" }}>{co.source_system}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {data.pages > 1 && (
          <div className="flex items-center justify-between px-5 py-3 border-t text-xs" style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
            <span>Page {page} of {data.pages}</span>
            <div className="flex gap-2">
              <button disabled={page <= 1 || loading} onClick={() => load(page - 1, sizeTier, search)} className="px-3 py-1.5 rounded-sm border disabled:opacity-40" style={{ borderColor: "var(--border)" }}>← Prev</button>
              <button disabled={page >= data.pages || loading} onClick={() => load(page + 1, sizeTier, search)} className="px-3 py-1.5 rounded-sm border disabled:opacity-40" style={{ borderColor: "var(--border)" }}>Next →</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
