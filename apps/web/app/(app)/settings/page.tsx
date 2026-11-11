"use client";

import { useState, useEffect } from "react";
import { ApiError, fetchApi } from "@/lib/api";
import { describeDuration } from "@/lib/format";
import type { SystemConfig } from "@/lib/types";

type Notice = { kind: "ok" | "error"; text: string };

function NoticeBar({ notice }: { notice: Notice | null }) {
  if (!notice) return null;
  const ok = notice.kind === "ok";
  return (
    <div
      role={ok ? "status" : "alert"}
      className="mb-4 px-3 py-2 rounded-sm text-xs"
      style={{ background: ok ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)", color: ok ? "var(--green)" : "var(--red)" }}
    >
      {notice.text}
    </div>
  );
}

const messageOf = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

type Tab = "general" | "webhooks" | "models";

type RegisteredModel = {
  id: string;
  version: string;
  stage: "training" | "shadow" | "champion" | "archived" | string;
  roc_auc: number | null;
  precision_hot: number | null;
  training_rows: number | null;
};

type Webhook = {
  id: string;
  name: string;
  url: string;
  events: string;
  tier_filter: string | null;
  status: string;
  total_deliveries: number;
  successful_deliveries: number;
  failed_deliveries: number;
  last_triggered_at: string | null;
  created_at: string;
};

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("general");

  return (
    <div className="p-4 sm:p-8 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
          Settings
        </h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
          Platform configuration
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 p-1 rounded-lg w-fit" style={{ background: "var(--surface-overlay)" }}>
        {(["general", "webhooks", "models"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className="px-4 py-1.5 rounded-md text-sm font-medium capitalize transition-colors"
            style={{
              background: tab === t ? "var(--surface-raised)" : "transparent",
              color: tab === t ? "var(--text)" : "var(--text-muted)",
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "general" && <GeneralTab />}
      {tab === "webhooks" && <WebhooksTab />}
      {tab === "models" && <ModelsTab />}
    </div>
  );
}

function secretRow(label: string, isSet: boolean, variable: string) {
  return <SettingsRow key={label} label={label} value={isSet ? "Set" : `Not set — configure ${variable}`} warn={!isSet} />;
}

function GeneralTab() {
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    fetchApi<SystemConfig>("/system/config")
      .then(setConfig)
      .catch((e: unknown) => setNotice({ kind: "error", text: messageOf(e, "Could not load the configuration") }));
  }, []);

  return (
    <div className="space-y-4">
      <NoticeBar notice={notice} />
      {!config && !notice && (
        <p role="status" className="text-xs" style={{ color: "var(--text-muted)" }}>
          Loading configuration…
        </p>
      )}

      {config && (
        <>
          <SettingsSection title="HubSpot Integration">
            {secretRow("Access Token", config.hubspot_access_token_set, "HUBSPOT_ACCESS_TOKEN")}
            {secretRow("Portal ID", config.hubspot_portal_id_set, "HUBSPOT_PORTAL_ID")}
            <SettingsRow label="Batch Size" value={`${config.hubspot_batch_size} contacts per API call`} />
            <SettingsRow label="Rate Limit" value={`${config.hubspot_rate_limit_per_second} req/s`} />
            {secretRow("Webhook Secret", config.hubspot_webhook_secret_set, "HUBSPOT_WEBHOOK_SECRET")}
          </SettingsSection>

          <SettingsSection title="AI Intelligence">
            <SettingsRow label="Provider" value={`Anthropic Claude (${config.ai_model})`} />
            {secretRow("API Key", config.anthropic_api_key_set, "ANTHROPIC_API_KEY")}
            <SettingsRow label="Cache TTL" value={`${describeDuration(config.ai_cache_ttl_seconds)} (Redis)`} />
            <SettingsRow label="Rate Limit" value={`${config.ai_rate_limit_per_minute} requests/min per user`} />
          </SettingsSection>

          <SettingsSection title="Scoring Engine">
            <SettingsRow label="v1 Model" value="Deterministic formula (always active)" />
            <SettingsRow label="v2 ML Model" value="XGBoost (shadow mode until promoted)" />
            <SettingsRow label="HOT Threshold" value={`≥ ${config.scoring_hot_threshold}`} />
            <SettingsRow label="WARM Threshold" value={`≥ ${config.scoring_warm_threshold}`} />
            <SettingsRow label="COOL Threshold" value={`≥ ${config.scoring_cool_threshold}`} />
          </SettingsSection>
        </>
      )}

      <SettingsSection title="Beat Schedule">
        <SettingsRow label="Feature Recompute" value="Every hour" />
        <SettingsRow label="Scoring Run (v1)" value="Every hour" />
        <SettingsRow label="Shadow ML Scoring" value="Every hour" />
        <SettingsRow label="HubSpot Sync" value="Daily" />
        <SettingsRow label="Webhook Retry Sweep" value="Every 30 minutes" />
        <SettingsRow label="Model Retraining" value="Every 7 days" />
        <SettingsRow label="DLQ Reprocessor" value="Every 30 minutes" />
      </SettingsSection>

      <p className="text-xs mt-4" style={{ color: "var(--text-faint)" }}>
        Secrets are configured through environment variables and are never shown here, only whether each is set. See{" "}
        <code className="font-mono">.env.example</code> for the full reference.
      </p>
    </div>
  );
}

function WebhooksTab() {
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", url: "", events: "tier_crossed", tier_filter: "" });
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [newSecret, setNewSecret] = useState<string | null>(null);

  useEffect(() => {
    fetchApi<Webhook[]>("/webhooks")
      .then(setWebhooks)
      .catch((e: unknown) => setNotice({ kind: "error", text: messageOf(e, "Could not load webhooks") }))
      .finally(() => setLoading(false));
  }, []);

  async function saveWebhook() {
    setSaving(true);
    setNotice(null);
    try {
      const created = await fetchApi<Webhook & { secret: string }>("/webhooks", {
        method: "POST",
        body: JSON.stringify({ ...form, tier_filter: form.tier_filter || null }),
      });
      const { secret, ...webhook } = created;
      setWebhooks((prev) => [webhook, ...prev]);
      setNewSecret(secret); // the API shows the signing secret once, here
      setShowForm(false);
      setForm({ name: "", url: "", events: "tier_crossed", tier_filter: "" });
    } catch (e) {
      setNotice({ kind: "error", text: messageOf(e, "Could not save the webhook") });
    } finally {
      setSaving(false);
    }
  }

  async function deleteWebhook(id: string) {
    setNotice(null);
    try {
      await fetchApi<void>(`/webhooks/${encodeURIComponent(id)}`, { method: "DELETE" });
      setWebhooks((prev) => prev.filter((w) => w.id !== id));
    } catch (e) {
      setNotice({ kind: "error", text: messageOf(e, "Could not delete the webhook") });
    }
  }

  async function testWebhook(id: string) {
    setTestingId(id);
    setNotice(null);
    try {
      const result = await fetchApi<{ delivered_to: number; delivery_status: string }>(`/webhooks/${encodeURIComponent(id)}/test`, {
        method: "POST",
        body: JSON.stringify({ event_type: "tier_crossed" }),
      });
      setNotice(
        result.delivered_to > 0
          ? { kind: "ok", text: "Test ping delivered" }
          : { kind: "error", text: "The test ping was not delivered. See the delivery log for the reason." },
      );
    } catch (e) {
      setNotice({ kind: "error", text: messageOf(e, "Test failed") });
    } finally {
      setTestingId(null);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Fire HTTP POST events when leads cross tier thresholds
        </p>
        <button
          onClick={() => setShowForm(!showForm)}
          className="text-xs px-3 py-1.5 rounded-md font-medium"
          style={{ background: "var(--primary-strong)", color: "#fff" }}
        >
          + Add Webhook
        </button>
      </div>

      <NoticeBar notice={notice} />

      {newSecret && (
        <div className="mb-4 rounded-sm border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--surface-raised)" }}>
          <p className="font-medium mb-1" style={{ color: "var(--text)" }}>
            Signing secret — shown once, copy it now
          </p>
          <code className="block break-all font-mono" style={{ color: "var(--text-muted)" }}>
            {newSecret}
          </code>
          <button className="mt-2 underline" style={{ color: "var(--primary-fg)" }} onClick={() => setNewSecret(null)}>
            I have copied it
          </button>
        </div>
      )}

      {showForm && (
        <div
          className="mb-4 rounded-xl border p-4 space-y-3"
          style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs mb-1" style={{ color: "var(--text-muted)" }}>
                Name
              </label>
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                className="w-full px-3 py-2 rounded-md text-sm"
                style={{
                  background: "var(--surface-overlay)",
                  border: "1px solid var(--border)",
                  color: "var(--text)",
                  outline: "none",
                }}
                placeholder="Slack #hot-leads"
              />
            </div>
            <div>
              <label className="block text-xs mb-1" style={{ color: "var(--text-muted)" }}>
                URL
              </label>
              <input
                value={form.url}
                onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                className="w-full px-3 py-2 rounded-md text-sm"
                style={{
                  background: "var(--surface-overlay)",
                  border: "1px solid var(--border)",
                  color: "var(--text)",
                  outline: "none",
                }}
                placeholder="https://hooks.slack.com/…"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs mb-1" style={{ color: "var(--text-muted)" }}>
                Events (comma-separated)
              </label>
              <input
                value={form.events}
                onChange={(e) => setForm((f) => ({ ...f, events: e.target.value }))}
                className="w-full px-3 py-2 rounded-md text-sm"
                style={{
                  background: "var(--surface-overlay)",
                  border: "1px solid var(--border)",
                  color: "var(--text)",
                  outline: "none",
                }}
                placeholder="tier_crossed,hot_lead"
              />
            </div>
            <div>
              <label className="block text-xs mb-1" style={{ color: "var(--text-muted)" }}>
                Tier Filter (optional)
              </label>
              <input
                value={form.tier_filter}
                onChange={(e) => setForm((f) => ({ ...f, tier_filter: e.target.value }))}
                className="w-full px-3 py-2 rounded-md text-sm"
                style={{
                  background: "var(--surface-overlay)",
                  border: "1px solid var(--border)",
                  color: "var(--text)",
                  outline: "none",
                }}
                placeholder="HOT,WARM (blank = all)"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={saveWebhook}
              disabled={saving || !form.name || !form.url}
              className="text-xs px-4 py-1.5 rounded-md font-medium disabled:opacity-40"
              style={{ background: "var(--primary-strong)", color: "#fff" }}
            >
              {saving ? "Saving…" : "Save Webhook"}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="text-xs px-4 py-1.5 rounded-md font-medium"
              style={{ background: "var(--surface-overlay)", color: "var(--text-muted)" }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>
          Loading…
        </div>
      ) : webhooks.length === 0 ? (
        <div
          className="rounded-xl border p-6 text-center text-sm"
          style={{ background: "var(--surface-raised)", borderColor: "var(--border)", color: "var(--text-muted)" }}
        >
          No webhooks configured yet. Add one above.
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {webhooks.map((wh) => (
            <div
              key={wh.id}
              className="rounded-xl border p-4"
              style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium" style={{ color: "var(--text)" }}>
                      {wh.name}
                    </span>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded-full"
                      style={{
                        background:
                          wh.status === "active" ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
                        color: wh.status === "active" ? "var(--green)" : "var(--red)",
                      }}
                    >
                      {wh.status}
                    </span>
                  </div>
                  <div className="text-xs mt-0.5 font-mono break-all" style={{ color: "var(--text-muted)" }}>
                    {wh.url}
                  </div>
                  <div className="flex gap-3 mt-2 text-xs" style={{ color: "var(--text-faint)" }}>
                    <span>Events: {wh.events}</span>
                    {wh.tier_filter && <span>Tiers: {wh.tier_filter}</span>}
                    <span style={{ color: "var(--green)" }}>
                      ✓ {wh.successful_deliveries}
                    </span>
                    <span style={{ color: "var(--red)" }}>
                      ✗ {wh.failed_deliveries}
                    </span>
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => testWebhook(wh.id)}
                    disabled={testingId === wh.id}
                    className="text-xs px-3 py-1 rounded-md"
                    style={{
                      background: "var(--surface-overlay)",
                      color: "var(--text-muted)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    {testingId === wh.id ? "…" : "Test"}
                  </button>
                  <button
                    onClick={() => deleteWebhook(wh.id)}
                    className="text-xs px-3 py-1 rounded-md"
                    style={{ background: "rgba(239,68,68,0.1)", color: "var(--red)" }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ModelsTab() {
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    fetchApi<RegisteredModel[]>("/models")
      .then(setModels)
      .catch((e: unknown) => setNotice({ kind: "error", text: messageOf(e, "Could not load the model registry") }))
      .finally(() => setLoading(false));
  }, []);

  async function promoteModel(id: string) {
    setNotice(null);
    try {
      await fetchApi<unknown>(`/models/${encodeURIComponent(id)}/promote`, { method: "POST" });
      setModels(await fetchApi<RegisteredModel[]>("/models"));
    } catch (e) {
      setNotice({ kind: "error", text: messageOf(e, "Could not promote the model") });
    }
  }

  return (
    <div>
      <div className="mb-4">
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          ML model registry — train v2 models and promote to champion
        </p>
        <p className="text-xs mt-1 font-mono px-2 py-1 rounded-sm w-fit" style={{ background: "var(--surface-overlay)", color: "var(--text-faint)" }}>
          python -m workers.training.train_model --min-rows 200
        </p>
      </div>

      <NoticeBar notice={notice} />

      {loading ? (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>
          Loading…
        </div>
      ) : models.length === 0 ? (
        <div
          className="rounded-xl border p-6 text-center text-sm"
          style={{ background: "var(--surface-raised)", borderColor: "var(--border)", color: "var(--text-muted)" }}
        >
          No ML models registered yet. Run the training pipeline first.
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {models.map((m) => (
            <div
              key={m.id}
              className="rounded-xl border p-4"
              style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-mono font-medium" style={{ color: "var(--text)" }}>
                      v{m.version}
                    </span>
                    <span
                      className="text-[10px] px-2 py-0.5 rounded-full font-medium"
                      style={{
                        background:
                          m.stage === "champion"
                            ? "rgba(34,197,94,0.15)"
                            : m.stage === "shadow"
                            ? "rgba(99,102,241,0.15)"
                            : "var(--surface-overlay)",
                        color:
                          m.stage === "champion"
                            ? "var(--green)"
                            : m.stage === "shadow"
                            ? "var(--primary)"
                            : "var(--text-faint)",
                      }}
                    >
                      {m.stage}
                    </span>
                  </div>
                  <div className="flex gap-4 text-xs" style={{ color: "var(--text-muted)" }}>
                    {m.roc_auc != null && <span>ROC-AUC: {m.roc_auc.toFixed(3)}</span>}
                    {m.precision_hot != null && (
                      <span>HOT precision: {(m.precision_hot * 100).toFixed(1)}%</span>
                    )}
                    {m.training_rows != null && (
                      <span>{m.training_rows.toLocaleString()} training rows</span>
                    )}
                  </div>
                </div>
                {m.stage === "shadow" && (
                  <button
                    onClick={() => promoteModel(m.id)}
                    className="text-xs px-3 py-1.5 rounded-md font-medium shrink-0"
                    style={{ background: "var(--primary-strong)", color: "#fff" }}
                  >
                    Promote to Champion
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl border overflow-x-auto"
      style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
    >
      <div className="px-5 py-3 border-b" style={{ borderColor: "var(--border)" }}>
        <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
          {title}
        </h2>
      </div>
      <div className="divide-y" style={{ borderColor: "var(--border-muted)" }}>
        {children}
      </div>
    </div>
  );
}

function SettingsRow({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between px-5 py-3">
      <span className="text-sm" style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
      <span
        className="text-xs font-mono text-right max-w-sm"
        style={{ color: warn ? "var(--yellow)" : "var(--text)" }}
      >
        {value}
      </span>
    </div>
  );
}
