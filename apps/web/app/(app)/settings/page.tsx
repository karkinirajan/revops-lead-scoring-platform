export default function SettingsPage() {
  return (
    <div className="p-8 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>Settings</h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
          Platform configuration — secrets managed via environment variables
        </p>
      </div>

      <div className="space-y-4">
        <SettingsSection title="HubSpot Integration">
          <SettingsRow label="Access Token" value="Configured via HUBSPOT_ACCESS_TOKEN env var" secret />
          <SettingsRow label="Portal ID" value="Configured via HUBSPOT_PORTAL_ID env var" secret />
          <SettingsRow label="Batch Size" value="100 contacts per API call" />
          <SettingsRow label="Rate Limit" value="10 req/s" />
        </SettingsSection>

        <SettingsSection title="Scoring Engine">
          <SettingsRow label="Model Version" value="v1.0.0" />
          <SettingsRow label="HOT Threshold" value="≥ 75" />
          <SettingsRow label="WARM Threshold" value="≥ 50" />
          <SettingsRow label="COOL Threshold" value="≥ 25" />
          <SettingsRow label="Shadow Mode" value="Disabled — set SCORING_SHADOW_MODEL_VERSION to enable" />
        </SettingsSection>

        <SettingsSection title="Queue Configuration">
          <SettingsRow label="Broker" value="Redis (CELERY_BROKER_URL)" />
          <SettingsRow label="Queues" value="ingest · features · scoring · sync · dlq" />
          <SettingsRow label="Worker Concurrency" value="4 (CELERY_WORKER_CONCURRENCY)" />
          <SettingsRow label="Task Timeout" value="300s soft / 600s hard" />
        </SettingsSection>

        <SettingsSection title="Beat Schedule">
          <SettingsRow label="Feature Recompute" value="Every hour" />
          <SettingsRow label="Scoring Run" value="Every hour" />
          <SettingsRow label="HubSpot Sync" value="Daily" />
          <SettingsRow label="DLQ Reprocessor" value="Every 30 minutes" />
        </SettingsSection>

        <SettingsSection title="Security">
          <SettingsRow label="JWT Algorithm" value="HS256" />
          <SettingsRow label="Token Expiry" value="60 minutes (access) · 7 days (refresh)" />
          <SettingsRow label="Rate Limiting" value="100 req/min per IP (slowapi + Redis)" />
          <SettingsRow label="PII in Logs" value="Redacted (Authorization, password, token fields)" />
        </SettingsSection>
      </div>

      <p className="text-xs mt-8" style={{ color: "var(--text-faint)" }}>
        All secrets must be configured via environment variables. Never commit secrets to source control.
        See <code className="font-mono">.env.example</code> for the full variable reference.
      </p>
    </div>
  );
}

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border overflow-hidden" style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}>
      <div className="px-5 py-3 border-b" style={{ borderColor: "var(--border)" }}>
        <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>{title}</h2>
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
      <span className="text-sm" style={{ color: "var(--text-muted)" }}>{label}</span>
      <span
        className="text-xs font-mono text-right max-w-sm"
        style={{ color: secret ? "var(--text-faint)" : "var(--text)" }}
      >
        {value}
      </span>
    </div>
  );
}
