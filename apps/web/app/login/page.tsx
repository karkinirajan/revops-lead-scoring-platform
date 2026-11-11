import type { Metadata } from "next";
import { safeNext } from "@/lib/auth/paths";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Sign in — RevOps Lead Scoring" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-xl border p-8" style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}>
        <h1 className="text-xl font-bold mb-1" style={{ color: "var(--text)" }}>
          RevOps Lead Scoring
        </h1>
        <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
          Sign in to continue
        </p>
        <LoginForm next={safeNext(next)} />
      </div>
    </main>
  );
}
