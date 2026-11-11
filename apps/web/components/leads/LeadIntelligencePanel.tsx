"use client";

import { useState } from "react";
import { goToLogin } from "@/lib/navigation";
import { applyStreamLine } from "@/lib/sse";

type Props = {
  contactId: string;
  contactName: string;
};

export function LeadIntelligencePanel({ contactId, contactName }: Props) {
  const [open, setOpen] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function loadIntelligence() {
    if (streaming) return;
    setOpen(true);
    setStreaming(true);
    setText("");
    setError(null);

    try {
      const resp = await fetch(`/bff/contacts/${encodeURIComponent(contactId)}/intelligence`, { credentials: "same-origin", cache: "no-store" });

      if (resp.status === 401) {
        goToLogin();
        return;
      }
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}));
        setError(typeof d.detail === "string" ? d.detail : "Intelligence unavailable");
        setStreaming(false);
        return;
      }

      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) {
        setError("Streaming not supported");
        setStreaming(false);
        return;
      }

      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        let finished = false;
        for (const line of lines) {
          const event = applyStreamLine(line);
          if (event.kind === "chunk") setText((prev) => prev + event.text);
          else if (event.kind === "error") setError(event.message);
          if (event.kind === "done" || event.kind === "error") {
            finished = true;
            break;
          }
        }
        if (finished) break;
      }
    } catch {
      setError("Failed to connect to AI service");
    } finally {
      setStreaming(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={loadIntelligence}
        className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md font-medium transition-opacity hover:opacity-80"
        style={{ background: "rgba(99,102,241,0.15)", color: "var(--primary-fg)" }}
        title="Generate AI intelligence report"
      >
        <SparkleIcon />
        AI Intel
      </button>
    );
  }

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
    >
      <div
        className="flex items-center justify-between px-4 py-3 border-b"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="flex items-center gap-2">
          <SparkleIcon />
          <span className="text-xs font-semibold" style={{ color: "var(--primary-fg)" }}>
            AI Intelligence — {contactName}
          </span>
          {streaming && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-sm" style={{ background: "rgba(99,102,241,0.1)", color: "var(--primary-fg)" }}>
              generating…
            </span>
          )}
        </div>
        <button
          onClick={() => setOpen(false)}
          aria-label="Close AI intelligence"
          className="text-xs"
          style={{ color: "var(--text-faint)" }}
        >
          ✕
        </button>
      </div>

      <div className="px-4 py-4 max-h-80 overflow-y-auto">
        {error ? (
          <div className="text-xs" style={{ color: "var(--red)" }}>
            {error}
          </div>
        ) : text ? (
          <pre
            className="text-xs whitespace-pre-wrap font-sans leading-relaxed"
            style={{ color: "var(--text)" }}
          >
            {text}
            {streaming && (
              <span
                className="inline-block w-1.5 h-3 ml-0.5 rounded-sm animate-pulse"
                style={{ background: "var(--primary)" }}
              />
            )}
          </pre>
        ) : (
          <div className="text-xs animate-pulse" style={{ color: "var(--text-muted)" }}>
            Analyzing lead signals…
          </div>
        )}
      </div>

      {!streaming && text && (
        <div className="px-4 pb-3">
          <button
            onClick={loadIntelligence}
            className="text-xs"
            style={{ color: "var(--text-faint)" }}
          >
            Regenerate
          </button>
        </div>
      )}
    </div>
  );
}

function SparkleIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
    </svg>
  );
}
