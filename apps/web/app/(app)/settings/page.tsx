"use client";

import { useState, useEffect } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Tab = "general" | "webhooks" | "models";

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
    <div className="p-8 max-w-3xl mx-auto">
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

function GeneralTab() {
  return (
    <div className="space-y-4">
      <SettingsSection title="HubSpot Integration">
        <SettingsRow label="Access Token" value="Configured via HUBSPOT_ACCESS_TOKEN" secret />
        <SettingsRow label="Portal ID" value="Configured via HUBSPOT_PORTAL_ID" secret />
        <SettingsRow label="Batch Size" value="100 contacts per API call" />
        <SettingsRow label="Rate Limit" value="10 req/s" />
        <SettingsRow label="Webhook Secret" value="Configured via HUBSPOT_WEBHOOK_SECRET" secret />
      </SettingsSection>

      <SettingsSection title="AI Intelligence">
        <SettingsRow label="Provider" value="Anthropic Claude (claude-sonnet-4-6)" />
        <SettingsRow label="API Key" value="Configured via ANTHROPIC_API_KEY" secret />
        <SettingsRow label="Cache TTL" value="6 hours (Redis)" />
        <SettingsRow label="Rate Limit" value="10 requests/min per user" />
      </SettingsSection>

      <SettingsSection title="Scoring Engine">
        <SettingsRow label="v1 Model" value="Deterministic formula (always active)" />
        <SettingsRow label="v2 ML Model" value="XGBoost (shadow mode until promoted)" />
        <SettingsRow label="HOT Threshold" value="≥ 75" />
        <SettingsRow label="WARM Threshold" value="≥ 50" />
        <SettingsRow label="COOL Threshold" value="≥ 25" />
      </SettingsSection>

      <SettingsSection title="Beat Schedule">
        <SettingsRow label="Feature Recompute" value="Every hour" />
        <SettingsRow label="Scoring Run (v1)" value="Every hour" />
        <SettingsRow label="Shadow ML Scoring" value="Every hour" />
        <SettingsRow label="HubSpot Sync" value="Daily" />
        <SettingsRow label="Webhook Retry Sweep" value="Every 30 minutes" />
        <SettingsRow label="Model Retraining" value="Weekly (Sunday 2am UTC)" />
        <SettingsRow label="DLQ Reprocessor" value="Every 30 minutes" />
      </SettingsSection>

      <p className="text-xs mt-4" style={{ color: "var(--text-faint)" }}>
        All secrets configured via environment variables. See{" "}
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
  const [testResult, setTestResult] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/api/v1/webhooks`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then(setWebhooks)
      .catch(() => setWebhooks([]))
      .finally(() => setLoading(false));
  }, []);

  async function saveWebhook() {
    setSaving(true);
    const r = await fetch(`${API}/api/v1/webhooks`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("token") ?? ""}`,
      },
      body: JSON.stringify({ ...form, tier_filter: form.tier_filter || null }),
    });
    if (r.ok) {
      const wh = await r.json();
      setWebhooks((prev) => [wh, ...prev]);
      setShowForm(false);
      setForm({ name: "", url: "", events: "tier_crossed", tier_filter: "" });
    }
    setSaving(false);
  }

  async function deleteWebhook(id: string) {
    await fetch(`${API}/api/v1/webhooks/${id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}` },
    });
    setWebhooks((prev) => prev.filter((w) => w.id !== id));
  }

  async function testWebhook(id: string) {
    setTestingId(id);
    setTestResult(null);
    const r = await fetch(`${API}/api/v1/webhooks/${id}/test`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("token") ?? ""}`,
      },
      body: JSON.stringify({ event_type: "tier_crossed" }),
    });
    const d = await r.json();
    setTestResult(r.ok ? "Test ping sent successfully" : d.detail ?? "Test failed");
    setTestingId(null);
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Fire HTTP POST events when leads cross tier thresholds
        </p>
        <button
          onClick={() => setShowForm(!showForm)}
          className="text-xs px-3 py-1.5 rounded-md font-medium"
          style={{ background: "var(--primary)", color: "#fff" }}
        >
          + Add Webhook
        </button>
      </div>

      {testResult && (
        <div
          className="mb-4 px-3 py-2 rounded text-xs"
          style={{ background: "rgba(34,197,94,0.1)", color: "var(--green)" }}
        >
          {testResult}
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
              style={{ background: "var(--primary)", color: "#fff" }}
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
  const [models, setModels] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/api/v1/models`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}` },
    })
      .then((r) => (r.ok ? r.json() : []))
      .then(setModels)
      .catch(() => setModels([]))
      .finally(() => setLoading(false));
  }, []);

  async function promoteModel(id: string) {
    await fetch(`${API}/api/v1/models/${id}/promote`, {
      method: "POST",
      headers: { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}` },
    });
    // Refresh
    const r = await fetch(`${API}/api/v1/models`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}` },
    });
    if (r.ok) setModels(await r.json());
  }

  return (
    <div>
      <div className="mb-4">
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          ML model registry — train v2 models and promote to champion
        </p>
        <p className="text-xs mt-1 font-mono px-2 py-1 rounded w-fit" style={{ background: "var(--surface-overlay)", color: "var(--text-faint)" }}>
          python -m workers.training.train_model --min-rows 200
        </p>
      </div>

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
                    style={{ background: "var(--primary)", color: "#fff" }}
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
      className="rounded-xl border overflow-hidden"
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

function SettingsRow({ label, value, secret }: { label: string; value: string; secret?: boolean }) {
  return (
    <div className="flex items-center justify-between px-5 py-3">
      <span className="text-sm" style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
      <span
        className="text-xs font-mono text-right max-w-sm"
        style={{ color: secret ? "var(--text-faint)" : "var(--text)" }}
      >
        {value}
      </span>
    </div>
  );
}
