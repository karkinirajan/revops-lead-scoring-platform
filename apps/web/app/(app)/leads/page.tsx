import { LeadsTable } from "@/components/leads/LeadsTable";
import type { PaginatedResponse, RankedLead } from "@/lib/types";

const API = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

async function getLeads(filters: Record<string, string>): Promise<PaginatedResponse<RankedLead>> {
  const page = filters.page ?? "1";
  const tier = filters.tier ?? "";
  const min_score = filters.min_score ?? "";
  const page_size = filters.page_size ?? "50";

  const q = new URLSearchParams({ page, page_size });
  if (tier) q.set("priority_tier", tier);
  if (min_score) q.set("min_score", min_score);

  try {
    const res = await fetch(`${API}/api/v1/scoring/leads?${q}`, {
      next: { revalidate: 30 },
    });
    if (!res.ok) return { items: [], total: 0, page: 1, page_size: 50, pages: 1 };
    return res.json();
  } catch {
    return { items: [], total: 0, page: 1, page_size: 50, pages: 1 };
  }
}

export default async function LeadsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string>>;
}) {
  const params = await searchParams;
  const data = await getLeads(params);

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
          Leads
        </h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
          {data.total.toLocaleString()} total scored contacts — ranked highest first
        </p>
      </div>
      <LeadsTable initialData={data} />
    </div>
  );
}
