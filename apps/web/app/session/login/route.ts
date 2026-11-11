import { NextResponse } from "next/server";
import { isSameOrigin } from "@/lib/auth/origin";
import { isTokenPair } from "@/lib/auth/tokens";
import { apiBase } from "@/lib/config";
import { clientAddress, setSession } from "@/lib/server/session";

export const dynamic = "force-dynamic";

function fail(status: number, detail: string) {
  return NextResponse.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });
}

/** Sign in: check the credentials with the API and keep the tokens in httpOnly cookies, so they never reach the page's JavaScript. */
export async function POST(request: Request) {
  if (!isSameOrigin(request)) return fail(403, "Cross-site request refused.");

  let email: unknown;
  let password: unknown;
  try {
    ({ email, password } = (await request.json()) as { email?: unknown; password?: unknown });
  } catch {
    return fail(400, "Send the email and password as JSON.");
  }
  if (typeof email !== "string" || typeof password !== "string" || !email || !password) return fail(400, "Enter your email and password.");

  const forwardedFor = clientAddress(request);
  let upstream: Response;
  try {
    upstream = await fetch(`${apiBase()}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(forwardedFor ? { "X-Forwarded-For": forwardedFor } : {}) },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
  } catch {
    return fail(502, "The sign-in service is unavailable. Try again shortly.");
  }

  if (upstream.status === 401) return fail(401, "Invalid email or password.");
  if (upstream.status === 403) return fail(403, "This account is inactive.");
  if (upstream.status === 429) return fail(429, "Too many attempts. Wait a minute and try again.");
  if (upstream.status === 422) return fail(422, "Enter a valid email and password.");
  if (!upstream.ok) return fail(502, "The sign-in service is unavailable. Try again shortly.");

  const tokens: unknown = await upstream.json().catch(() => null);
  if (!isTokenPair(tokens)) return fail(502, "The sign-in service answered unexpectedly.");
  return setSession(NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } }), tokens);
}
