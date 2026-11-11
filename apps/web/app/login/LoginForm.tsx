"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { errorMessage } from "@/lib/errors";

export function LoginForm({ next }: { next: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (!form.get("email") || !form.get("password")) {
      setError("Enter your email and password.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/session/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      if (!response.ok) {
        setError(errorMessage(await response.json().catch(() => null), "Could not sign in."));
        return;
      }
      router.replace(next);
      router.refresh();
    } catch {
      setError("Could not reach the server. Check your connection.");
    } finally {
      setSubmitting(false);
    }
  }

  const input = "w-full rounded-lg border px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary";
  const inputStyle = { background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" };

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <div>
        <label htmlFor="email" className="block text-xs font-medium mb-1" style={{ color: "var(--text-muted)" }}>
          Email
        </label>
        <input id="email" name="email" type="email" autoComplete="username" required autoFocus className={input} style={inputStyle} />
      </div>
      <div>
        <label htmlFor="password" className="block text-xs font-medium mb-1" style={{ color: "var(--text-muted)" }}>
          Password
        </label>
        <input id="password" name="password" type="password" autoComplete="current-password" required className={input} style={inputStyle} />
      </div>
      {error && (
        <p role="alert" className="text-xs rounded-sm px-3 py-2" style={{ background: "rgba(239,68,68,0.1)", color: "var(--red)" }}>
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-60 focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-primary"
        style={{ background: "var(--primary-strong)" }}
      >
        {submitting ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
