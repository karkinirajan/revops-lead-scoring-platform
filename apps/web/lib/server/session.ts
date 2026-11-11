import type { NextResponse } from "next/server";
import { clearedCookies, sessionCookies } from "@/lib/auth/cookies";
import type { TokenPair } from "@/lib/auth/tokens";

/** Put the session cookies for `tokens` on a response. */
export function setSession(response: NextResponse, tokens: TokenPair): NextResponse {
  for (const cookie of sessionCookies(tokens)) response.cookies.set(cookie);
  return response;
}

/** Remove the session cookies from a response. */
export function clearSession(response: NextResponse): NextResponse {
  for (const cookie of clearedCookies()) response.cookies.set(cookie);
  return response;
}

/**
 * The address of the browser, as the reverse proxy reported it: forwarded to the API so its per-address rate limits see the user and not this server.
 * The reverse proxy sets X-Forwarded-For to the address that connected to it (infra/nginx), so the header is one address. If it holds more, something
 * upstream appended to what a client sent, and the last entry is the one the nearest proxy added: the one a client cannot choose. (The first is the
 * client's own claim.) This server must only be reachable through that proxy.
 */
export function clientAddress(request: Request): string | null {
  const forwarded = request.headers.get("x-forwarded-for");
  if (!forwarded) return null;
  const entries = forwarded.split(",");
  return entries[entries.length - 1].trim() || null;
}
