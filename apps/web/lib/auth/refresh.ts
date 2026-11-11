import { apiBase } from "@/lib/config";
import { isTokenPair, type TokenPair } from "./tokens";

/** Exchange a refresh token for a new pair. Null if the API refuses it or cannot be reached. */
export async function refreshTokens(refreshToken: string, forwardedFor?: string | null): Promise<TokenPair | null> {
  try {
    const response = await fetch(`${apiBase()}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(forwardedFor ? { "X-Forwarded-For": forwardedFor } : {}) },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
    if (!response.ok) return null;
    const body: unknown = await response.json();
    return isTokenPair(body) ? body : null;
  } catch {
    return null;
  }
}
