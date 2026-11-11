import { StatCard } from "@/components/ui/StatCard";
import { TierBadge } from "@/components/ui/TierBadge";
import { type Bucket, barHeightPct, bucketColor, bucketStart, tallestBucket } from "@/lib/distribution";
import { describeModelScope } from "@/lib/format";
import { apiFetch } from "@/lib/server/api";
import type { ConversionList, ModelAccuracy, ScoreDistribution } from "@/lib/types";

async function getAnalyticsData() {
  const [accuracy, distribution, conversions] = await Promise.all([
    apiFetch<ModelAccuracy>("/analytics/model-accuracy"),
    apiFetch<ScoreDistribution>("/analytics/score-distribution"),
    apiFetch<ConversionList>("/analytics/conversions?page_size=10"),
  ]);
  return { accuracy, distribution, conversions };
}

export default async function AnalyticsPage() {
  const { accuracy, distribution, conversions } = await getAnalyticsData();

  const tierColors: Record<string, string> = {
    HOT: "var(--hot)",
    WARM: "var(--yellow)",
    COOL: "var(--primary)",
    COLD: "var(--text-faint)",
  };

  const maxBucketCount = tallestBucket(distribution?.buckets);

  return (
    <div className="p-4 sm:p-8 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
          Analytics
        </h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
          Model accuracy, score calibration, and conversion insights
        </p>
      </div>

      {/* Overview KPIs */}
      {accuracy && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <StatCard
            label="Total Leads Scored"
            value={(accuracy.total_scored ?? 0).toLocaleString()}
            sub="all model versions"
          />
          <StatCard
            label="Total Conversions"
            value={(accuracy.total_converted ?? 0).toLocaleString()}
            sub="deals closed"
          />
          <StatCard
            label="Overall Conversion Rate"
            value={`${((accuracy.overall_conversion_rate ?? 0) * 100).toFixed(1)}%`}
            accent="var(--green)"
            sub="leads → customers"
          />
          <StatCard label="Model Version" {...describeModelScope(accuracy.model_version)} />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Tier precision table */}
        <section
          className="rounded-xl border overflow-x-auto"
          style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
        >
          <div className="px-5 py-4 border-b" style={{ borderColor: "var(--border)" }}>
            <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              Precision per Tier
            </h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
              % of leads in each tier that actually converted
            </p>
          </div>

          {!accuracy?.tiers?.length ? (
            <div className="px-5 py-8 text-center text-sm" style={{ color: "var(--text-muted)" }}>
              No conversion data yet.{" "}
              <a href="#record" className="underline" style={{ color: "var(--primary-fg)" }}>
                Record conversions
              </a>{" "}
              to see precision metrics.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["Tier", "Leads", "Converted", "Precision", "Avg Score"].map((h) => (
                    <th
                      key={h}
                      className="text-left px-4 py-2.5 text-xs font-medium"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {accuracy.tiers.map(
                  (t: {
                    tier: string;
                    total_leads: number;
                    converted: number;
                    precision: number;
                    avg_score: number;
                  }) => (
                    <tr
                      key={t.tier}
                      className="border-b last:border-0"
                      style={{ borderColor: "var(--border-muted)" }}
                    >
                      <td className="px-4 py-3">
                        <TierBadge tier={t.tier as "HOT" | "WARM" | "COOL" | "COLD"} />
                      </td>
                      <td className="px-4 py-3 text-xs" style={{ color: "var(--text)" }}>
                        {t.total_leads.toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-xs" style={{ color: "var(--green)" }}>
                        {t.converted.toLocaleString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div
                            className="h-1.5 rounded-full"
                            style={{
                              width: `${Math.round(t.precision * 60)}px`,
                              background: tierColors[t.tier] ?? "var(--primary)",
                            }}
                          />
                          <span className="text-xs font-medium" style={{ color: "var(--text)" }}>
                            {(t.precision * 100).toFixed(1)}%
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs" style={{ color: "var(--text-muted)" }}>
                        {t.avg_score.toFixed(0)}
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          )}
        </section>

        {/* Score distribution histogram */}
        <section
          className="rounded-xl border overflow-x-auto"
          style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
        >
          <div className="px-5 py-4 border-b" style={{ borderColor: "var(--border)" }}>
            <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              Score Distribution
            </h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
              {distribution?.total?.toLocaleString() ?? 0} leads scored
            </p>
          </div>

          <div className="px-5 py-5">
            {!distribution?.buckets?.length ? (
              <div className="text-center text-sm py-8" style={{ color: "var(--text-muted)" }}>
                No score data yet.
              </div>
            ) : (
              // each column fills the chart's height so that a bar's percentage height has something to be a percentage of
              <div className="flex h-36 gap-1">
                {distribution.buckets.map((b: Bucket) => (
                  <div key={b.range} className="flex h-full flex-1 flex-col items-center gap-1" title={`${b.range}: ${b.count} leads`}>
                    <span className="h-3 text-[10px] leading-3" style={{ color: "var(--text-faint)" }}>
                      {b.count > 0 ? b.count : ""}
                    </span>
                    <div className="flex min-h-0 w-full flex-1 items-end">
                      <div className="w-full rounded-sm" style={{ height: `${barHeightPct(b.count, maxBucketCount)}%`, background: bucketColor(bucketStart(b.range)), opacity: 0.85 }} />
                    </div>
                    <span className="text-[10px]" style={{ color: "var(--text-faint)" }}>
                      {bucketStart(b.range)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Recent conversions */}
      <section
        className="rounded-xl border overflow-x-auto"
        style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
        id="record"
      >
        <div
          className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: "var(--border)" }}
        >
          <div>
            <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              Recent Conversions
            </h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
              Deal-won events recorded from HubSpot or manual entry
            </p>
          </div>
          <span className="text-xs px-2 py-1 rounded-sm" style={{ background: "var(--surface-overlay)", color: "var(--text-muted)" }}>
            {conversions?.total ?? 0} total
          </span>
        </div>

        {!conversions?.items?.length ? (
          <div className="px-5 py-10 text-center">
            <p className="text-sm mb-2" style={{ color: "var(--text-muted)" }}>
              No conversions recorded yet.
            </p>
            <p className="text-xs" style={{ color: "var(--text-faint)" }}>
              Configure a HubSpot deal-won webhook at{" "}
              <code
                className="px-1 py-0.5 rounded-sm text-xs"
                style={{ background: "var(--surface-overlay)" }}
              >
                POST /api/v1/analytics/conversions/hubspot
              </code>
            </p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Contact", "Converted At", "Score at Close", "Tier at Close", "Deal Value", "Source"].map(
                  (h) => (
                    <th
                      key={h}
                      className="text-left px-4 py-2.5 text-xs font-medium"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {conversions.items.map(
                (c: {
                  id: string;
                  contact_id: string;
                  converted_at: string;
                  score_at_conversion: number | null;
                  tier_at_conversion: string | null;
                  deal_value: number | null;
                  source: string;
                }) => (
                  <tr
                    key={c.id}
                    className="border-b last:border-0"
                    style={{ borderColor: "var(--border-muted)" }}
                  >
                    <td className="px-4 py-3 text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                      {c.contact_id.slice(0, 8)}…
                    </td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--text)" }}>
                      {new Date(c.converted_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-xs font-medium" style={{ color: "var(--text)" }}>
                      {c.score_at_conversion ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      {c.tier_at_conversion ? (
                        <TierBadge tier={c.tier_at_conversion as "HOT" | "WARM" | "COOL" | "COLD"} />
                      ) : (
                        <span style={{ color: "var(--text-faint)" }}>—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--green)" }}>
                      {c.deal_value != null ? `$${c.deal_value.toLocaleString()}` : "—"}
                    </td>
                    <td
                      className="px-4 py-3 text-xs"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {c.source}
                    </td>
                  </tr>
                )
              )}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
