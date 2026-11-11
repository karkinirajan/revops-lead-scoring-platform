"use client";

import { useState } from "react";
import { simulateScore } from "@/lib/api";
import { TierBadge } from "@/components/ui/TierBadge";
import { ScoreBar } from "@/components/ui/ScoreBar";
import type { ScoreSimulateRequest, ScoreSimulateResponse } from "@/lib/types";

const DEFAULTS: ScoreSimulateRequest = {
  api_calls_7d: 0,
  api_calls_30d: 0,
  page_views_7d: 0,
  pricing_page_visited: false,
  email_opens_7d: 0,
  email_clicks_7d: 0,
  demo_requested: false,
  free_trial_active: false,
  integration_connected: false,
  integrations_count: 0,
  days_since_last_activity: 30,
  company_size_tier: "unknown",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    // The row is the label, so the control inside it is named by the text and a click on the text reaches the control
    <label className="flex items-center justify-between py-2.5 border-b last:border-0" style={{ borderColor: "var(--border-muted)" }}>
      <span className="text-sm" style={{ color: "var(--text-muted)" }}>{label}</span>
      {children}
    </label>
  );
}

function NumInput({ value, onChange, min = 0, max }: { value: number; onChange: (v: number) => void; min?: number; max?: number }) {
  return (
    <input
      type="number"
      min={min}
      max={max}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-20 px-2 py-1 rounded-sm text-sm text-right border font-mono"
      style={{ background: "var(--surface-overlay)", borderColor: "var(--border)", color: "var(--text)" }}
    />
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="w-11 h-6 shrink-0 rounded-full border transition-colors relative focus-visible:ring-2 focus-visible:ring-primary"
      // a border, not an inset shadow, marks the off state: an inline box-shadow would override the focus ring.
      // (The dark --border colour alone is 1.3:1 against the card; --text-faint is 5.3:1.)
      style={checked ? { background: "var(--primary)", borderColor: "transparent" } : { background: "var(--surface-overlay)", borderColor: "var(--text-faint)" }}
    >
      <span
        className="absolute top-[3px] w-4 h-4 rounded-full bg-white transition-all"
        style={{ left: checked ? "calc(100% - 19px)" : "3px" }}
      />
    </button>
  );
}

export function SimulateForm() {
  const [form, setForm] = useState<ScoreSimulateRequest>(DEFAULTS);
  const [result, setResult] = useState<ScoreSimulateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof ScoreSimulateRequest>(key: K, value: ScoreSimulateRequest[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await simulateScore(form);
      setResult(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Simulation failed");
    } finally {
      setLoading(false);
    }
  }

  const topContribs = result
    ? Object.entries(result.feature_contributions)
        .filter(([k, v]) => !k.startsWith("_") && v > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6)
    : [];

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {/* Form */}
      <form onSubmit={handleSubmit} className="rounded-xl border p-5" style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}>
        <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--text)" }}>Feature Vector</h2>

        <div className="mb-4">
          <p className="text-xs font-medium mb-2" style={{ color: "var(--text-muted)" }}>API Usage</p>
          <Field label="API calls (7d)"><NumInput value={form.api_calls_7d} onChange={(v) => set("api_calls_7d", v)} /></Field>
          <Field label="API calls (30d)"><NumInput value={form.api_calls_30d} onChange={(v) => set("api_calls_30d", v)} /></Field>
        </div>

        <div className="mb-4">
          <p className="text-xs font-medium mb-2" style={{ color: "var(--text-muted)" }}>Web Engagement</p>
          <Field label="Page views (7d)"><NumInput value={form.page_views_7d} onChange={(v) => set("page_views_7d", v)} /></Field>
          <Field label="Pricing page visited"><Toggle checked={form.pricing_page_visited} onChange={(v) => set("pricing_page_visited", v)} /></Field>
        </div>

        <div className="mb-4">
          <p className="text-xs font-medium mb-2" style={{ color: "var(--text-muted)" }}>Email Engagement</p>
          <Field label="Email opens (7d)"><NumInput value={form.email_opens_7d} onChange={(v) => set("email_opens_7d", v)} /></Field>
          <Field label="Email clicks (7d)"><NumInput value={form.email_clicks_7d} onChange={(v) => set("email_clicks_7d", v)} /></Field>
        </div>

        <div className="mb-4">
          <p className="text-xs font-medium mb-2" style={{ color: "var(--text-muted)" }}>Intent Signals</p>
          <Field label="Demo requested"><Toggle checked={form.demo_requested} onChange={(v) => set("demo_requested", v)} /></Field>
          <Field label="Free trial active"><Toggle checked={form.free_trial_active} onChange={(v) => set("free_trial_active", v)} /></Field>
          <Field label="Integration connected"><Toggle checked={form.integration_connected} onChange={(v) => set("integration_connected", v)} /></Field>
          <Field label="Integrations count"><NumInput value={form.integrations_count} onChange={(v) => set("integrations_count", v)} /></Field>
        </div>

        <div className="mb-5">
          <p className="text-xs font-medium mb-2" style={{ color: "var(--text-muted)" }}>Context</p>
          <Field label="Days since last activity"><NumInput value={form.days_since_last_activity} onChange={(v) => set("days_since_last_activity", v)} min={0} max={999} /></Field>
          <Field label="Company size tier">
            <select
              value={form.company_size_tier}
              onChange={(e) => set("company_size_tier", e.target.value)}
              className="px-2 py-1 rounded-sm text-sm border"
              style={{ background: "var(--surface-overlay)", borderColor: "var(--border)", color: "var(--text)" }}
            >
              {["unknown", "smb", "mid_market", "enterprise"].map((v) => (
                <option key={v} value={v}>{v.replace("_", " ")}</option>
              ))}
            </select>
          </Field>
        </div>

        {error && <p className="text-xs mb-3" style={{ color: "var(--red)" }}>{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2 rounded-lg text-sm font-medium text-white disabled:opacity-60 transition-colors"
          style={{ background: "var(--primary-strong)" }}
        >
          {loading ? "Calculating…" : "Simulate Score"}
        </button>
      </form>

      {/* Result */}
      <div>
        {result ? (
          <div className="rounded-xl border p-5 space-y-5" style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}>
            <div className="flex items-center justify-between">
              <TierBadge tier={result.priority_tier} />
              <span className="text-xs font-mono" style={{ color: "var(--text-faint)" }}>
                model v{result.model_version}
              </span>
            </div>
            <div>
              <p className="text-5xl font-bold tabular-nums" style={{ color: "var(--text)" }}>
                {result.lead_score}
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>/ 100</p>
            </div>
            <ScoreBar score={result.lead_score} />
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-muted)" }}>
              {result.score_reason}
            </p>

            {topContribs.length > 0 && (
              <div>
                <p className="text-xs font-medium mb-2" style={{ color: "var(--text-muted)" }}>
                  Top contributing signals
                </p>
                <div className="space-y-2">
                  {topContribs.map(([key, val]) => (
                    <div key={key} className="flex items-center gap-2">
                      <div className="flex-1 text-xs" style={{ color: "var(--text)" }}>
                        {key.replace(/_/g, " ")}
                      </div>
                      <div
                        className="h-1.5 rounded-full"
                        style={{
                          width: `${Math.round((val / Math.max(...topContribs.map((c) => c[1]))) * 80)}px`,
                          background: "var(--primary)",
                        }}
                      />
                      <span className="text-xs font-mono w-6 text-right" style={{ color: "var(--text-muted)" }}>
                        +{val}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div
            className="rounded-xl border p-8 flex items-center justify-center h-full min-h-64 text-sm"
            style={{ background: "var(--surface-raised)", borderColor: "var(--border)", color: "var(--text-faint)" }}
          >
            Score result will appear here
          </div>
        )}
      </div>
    </div>
  );
}
