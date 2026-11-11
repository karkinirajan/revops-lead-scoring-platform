import { apiFetch } from "@/lib/server/api";
import type { Company, PaginatedResponse } from "@/lib/types";
import { CompaniesTable } from "@/components/companies/CompaniesTable";

async function getCompanies(filters: Record<string, string>): Promise<PaginatedResponse<Company>> {
  const q = new URLSearchParams({ page: filters.page ?? "1", page_size: filters.page_size ?? "50" });
  if (filters.size_tier) q.set("size_tier", filters.size_tier);
  if (filters.search) q.set("search", filters.search);
  return apiFetch<PaginatedResponse<Company>>(`/companies?${q}`);
}

export default async function CompaniesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string>>;
}) {
  const filters = await searchParams;
  const data = await getCompanies(filters);

  return (
    <div className="p-4 sm:p-8 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
          Companies
        </h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
          {data.total.toLocaleString()} companies in the pipeline
        </p>
      </div>
      <CompaniesTable initialData={data} />
    </div>
  );
}
