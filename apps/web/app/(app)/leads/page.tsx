import { LeadsTable } from "@/components/leads/LeadsTable";
import { type LeadFilters, leadsQuery, parseLeadFilters } from "@/lib/leads";
import { apiFetch } from "@/lib/server/api";
import type { PaginatedResponse, RankedLead } from "@/lib/types";

async function getLeads(filters: LeadFilters): Promise<PaginatedResponse<RankedLead>> {
  return apiFetch<PaginatedResponse<RankedLead>>(`/scoring/leads?${leadsQuery(filters)}`);
}

export default async function LeadsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const filters = parseLeadFilters(await searchParams);
  const data = await getLeads(filters);

  return (
    <div className="p-4 sm:p-8 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
          Leads
        </h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
          {data.total.toLocaleString()} total scored contacts — ranked highest first
        </p>
      </div>
      <LeadsTable initialData={data} initialFilters={filters} />
    </div>
  );
}
