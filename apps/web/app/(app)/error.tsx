"use client";

export default function ErrorBoundary({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="p-4 sm:p-8 max-w-xl mx-auto">
      <div role="alert" className="rounded-xl border p-6" style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}>
        <h2 className="text-lg font-semibold mb-1" style={{ color: "var(--text)" }}>
          This page could not be loaded
        </h2>
        <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
          {error.message || "Something went wrong."}
          {error.digest ? ` (reference ${error.digest})` : ""}
        </p>
        <button
          type="button"
          onClick={reset}
          className="rounded-lg px-4 py-2 text-sm font-medium text-white focus-visible:ring-2 focus-visible:ring-primary"
          style={{ background: "var(--primary-strong)" }}
        >
          Try again
        </button>
      </div>
    </div>
  );
}
