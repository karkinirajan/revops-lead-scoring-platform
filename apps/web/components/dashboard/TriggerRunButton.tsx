"use client";

import { useState } from "react";
import { triggerScoringRun } from "@/lib/api";

export function TriggerRunButton() {
  const [loading, setLoading] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setLastResult(null);
    try {
      const run = await triggerScoringRun();
      setLastResult(`Run ${run.id.slice(0, 8)} queued`);
    } catch (e: unknown) {
      setLastResult(e instanceof Error ? e.message : "Failed to trigger run");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={handleClick}
        disabled={loading}
        className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-60 transition-colors"
        style={{ background: "var(--primary)" }}
      >
        {loading ? (
          <>
            <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Triggering…
          </>
        ) : (
          <>
            <span>▶</span> Run Scoring
          </>
        )}
      </button>
      {lastResult && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {lastResult}
        </p>
      )}
    </div>
  );
}
