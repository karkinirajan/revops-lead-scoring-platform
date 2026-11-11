"use client";

import { useState, useEffect } from "react";
import { ApiError, fetchApi } from "@/lib/api";

type CrmConnection = {
  id: string;
  crm_type: "hubspot" | "salesforce";
  name: string;
  org_id: string | null;
  instance_url: string | null;
  is_active: boolean;
  sync_direction: string;
  last_inbound_sync_at: string | null;
  last_outbound_sync_at: string | null;
  last_sync_error: string | null;
  total_records_synced: number;
  created_at: string;
};

type SyncResult = {
  direction: string;
  records_processed: number;
  success: number;
  failure: number;
  duration_seconds: number;
  synced_at: string;
};

function CrmIcon({ type }: { type: string }) {
  if (type === "hubspot") {
    return (
      <span
        className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold"
        style={{ background: "#ff7a59" }}
      >
        HS
      </span>
    );
  }
  return (
    <span
      className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold"
      style={{ background: "#00a1e0" }}
    >
      SF
    </span>
  );
}

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className="text-xs px-2 py-0.5 rounded-full font-medium"
      style={{
        background: active ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
        color: active ? "var(--green)" : "var(--red)",
      }}
    >
      {active ? "Active" : "Disabled"}
    </span>
  );
}

export default function IntegrationsPage() {
  const [connections, setConnections] = useState<CrmConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<{ id: string; result: SyncResult } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchApi<CrmConnection[]>("/integrations")
      .then(setConnections)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not load integrations"))
      .finally(() => setLoading(false));
  }, []);

  async function triggerSync(connId: string, direction: "inbound" | "outbound") {
    setSyncingId(connId);
    setSyncResult(null);
    setError(null);
    try {
      const result = await fetchApi<SyncResult>(`/integrations/${encodeURIComponent(connId)}/sync-${direction}`, { method: "POST" });
      setSyncResult({ id: connId, result });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Sync failed");
    } finally {
      setSyncingId(null);
    }
  }

  return (
    <div className="p-4 sm:p-8 max-w-4xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
          Integrations
        </h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
          Manage CRM connections — HubSpot and Salesforce
        </p>
      </div>

      {error && (
        <div
          className="mb-4 px-4 py-3 rounded-lg text-sm"
          style={{ background: "rgba(239,68,68,0.1)", color: "var(--red)" }}
        >
          {error}
        </div>
      )}

      {syncResult && (
        <div
          className="mb-4 px-4 py-3 rounded-lg text-sm"
          style={{ background: "rgba(34,197,94,0.1)", color: "var(--green)" }}
        >
          Sync complete — {syncResult.result.success} records synced in{" "}
          {syncResult.result.duration_seconds.toFixed(2)}s
        </div>
      )}

      {loading ? (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>
          Loading…
        </div>
      ) : connections.length === 0 ? (
        <div
          className="rounded-xl border p-8 text-center"
          style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
        >
          <p className="text-sm mb-3" style={{ color: "var(--text-muted)" }}>
            No CRM connections configured yet.
          </p>
          <p className="text-xs" style={{ color: "var(--text-faint)" }}>
            Connect HubSpot via API key, or start a Salesforce OAuth flow at{" "}
            <code
              className="px-1 py-0.5 rounded-sm"
              style={{ background: "var(--surface-overlay)" }}
            >
              /api/v1/integrations/salesforce/oauth/callback
            </code>
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {connections.map((conn) => (
            <div
              key={conn.id}
              className="rounded-xl border p-5"
              style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <CrmIcon type={conn.crm_type} />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>
                        {conn.name}
                      </span>
                      <StatusBadge active={conn.is_active} />
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                      {conn.crm_type.toUpperCase()} ·{" "}
                      {conn.instance_url ?? conn.org_id ?? "—"} ·{" "}
                      {conn.sync_direction}
                    </div>
                  </div>
                </div>

                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => triggerSync(conn.id, "inbound")}
                    disabled={syncingId === conn.id || !conn.is_active}
                    className="text-xs px-3 py-1.5 rounded-md font-medium disabled:opacity-40 transition-opacity"
                    style={{
                      background: "var(--surface-overlay)",
                      color: "var(--text)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    {syncingId === conn.id ? "Syncing…" : "Pull"}
                  </button>
                  <button
                    onClick={() => triggerSync(conn.id, "outbound")}
                    disabled={syncingId === conn.id || !conn.is_active}
                    className="text-xs px-3 py-1.5 rounded-md font-medium disabled:opacity-40 transition-opacity"
                    style={{
                      background: "var(--primary-strong)",
                      color: "#fff",
                    }}
                  >
                    {syncingId === conn.id ? "Syncing…" : "Push Scores"}
                  </button>
                </div>
              </div>

              {/* Sync stats */}
              <div
                className="mt-4 pt-4 border-t grid grid-cols-3 gap-4"
                style={{ borderColor: "var(--border-muted)" }}
              >
                <div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                    Last Inbound
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: "var(--text)" }}>
                    {conn.last_inbound_sync_at
                      ? new Date(conn.last_inbound_sync_at).toLocaleString()
                      : "Never"}
                  </div>
                </div>
                <div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                    Last Outbound
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: "var(--text)" }}>
                    {conn.last_outbound_sync_at
                      ? new Date(conn.last_outbound_sync_at).toLocaleString()
                      : "Never"}
                  </div>
                </div>
                <div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                    Total Synced
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: "var(--text)" }}>
                    {conn.total_records_synced.toLocaleString()} records
                  </div>
                </div>
              </div>

              {conn.last_sync_error && (
                <div
                  className="mt-3 px-3 py-2 rounded-sm text-xs"
                  style={{ background: "rgba(239,68,68,0.08)", color: "var(--red)" }}
                >
                  Last error: {conn.last_sync_error}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Setup guide */}
      <div
        className="mt-8 rounded-xl border p-5"
        style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
      >
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text)" }}>
          Setup Guide
        </h3>
        <div className="flex flex-col gap-3">
          <SetupStep
            title="HubSpot"
            steps={[
              "Get a Private App token from HubSpot Settings → Integrations → Private Apps",
              "POST /api/v1/integrations with crm_type=hubspot and your access_token",
              "Scores sync automatically every 24h, or trigger manually above",
            ]}
          />
          <SetupStep
            title="Salesforce"
            steps={[
              "Create a Connected App in Salesforce Setup → App Manager",
              "Set SALESFORCE_CLIENT_ID, SALESFORCE_CLIENT_SECRET, SALESFORCE_REDIRECT_URI in .env",
              "Visit /api/v1/integrations/salesforce/oauth/callback?code=AUTH_CODE to authorize",
              "Ensure RevOps_Lead_Score__c and RevOps_Priority_Tier__c custom fields exist on Contact",
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function SetupStep({ title, steps }: { title: string; steps: string[] }) {
  return (
    <div>
      <div className="text-xs font-medium mb-1.5" style={{ color: "var(--text)" }}>
        {title}
      </div>
      <ol className="flex flex-col gap-1">
        {steps.map((s, i) => (
          <li key={i} className="flex gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
            <span
              className="w-4 h-4 rounded-full flex items-center justify-center text-[10px] shrink-0 font-medium"
              style={{ background: "var(--surface-overlay)", color: "var(--text)" }}
            >
              {i + 1}
            </span>
            {s}
          </li>
        ))}
      </ol>
    </div>
  );
}
