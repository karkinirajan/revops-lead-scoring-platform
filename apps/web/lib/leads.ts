import type { PriorityTier } from "@/lib/types";

export const TIERS: PriorityTier[] = ["HOT", "WARM", "COOL", "COLD"];

export type LeadFilters = { tier: PriorityTier | ""; minScore: string; page: number };
export const NO_FILTERS: LeadFilters = { tier: "", minScore: "", page: 1 };

type RawParams = Record<string, string | string[] | undefined>;

const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

/**
 * The leads page's filters from its URL. Anything that is not a valid value is dropped rather than passed to the API
 * (a repeated parameter arrives as an array and would otherwise reach it as "HOT,WARM", which it rejects).
 */
export function parseLeadFilters(raw: RawParams): LeadFilters {
  const tier = first(raw.tier)?.toUpperCase() as PriorityTier | undefined;
  const score = first(raw.min_score);
  const minScore = score !== undefined && score.trim() !== "" && Number(score) >= 0 && Number(score) <= 100 ? String(Number(score)) : "";
  const page = Number(first(raw.page));
  return {
    tier: tier && TIERS.includes(tier) ? tier : "",
    minScore,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  };
}

export function leadsQuery(filters: LeadFilters, pageSize = 50): URLSearchParams {
  const query = new URLSearchParams({ page: String(filters.page), page_size: String(pageSize) });
  if (filters.tier) query.set("priority_tier", filters.tier);
  if (filters.minScore) query.set("min_score", filters.minScore);
  return query;
}
