/** The expiry (seconds since the epoch) in a JWT's payload, or null. The signature is NOT checked: the API does that on every call. This only decides when to refresh. */
export function tokenExpiry(token: string | undefined | null): number | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const json = Buffer.from(parts[1], "base64url").toString("utf8");
    const exp = (JSON.parse(json) as { exp?: unknown }).exp;
    return typeof exp === "number" && Number.isFinite(exp) ? exp : null;
  } catch {
    return null;
  }
}

/** True if there is no usable token, or it expires within `seconds` (default 30). */
export function expiresWithin(token: string | undefined | null, seconds = 30, now = Date.now()): boolean {
  const exp = tokenExpiry(token);
  return exp === null || exp * 1000 - now <= seconds * 1000;
}

export type TokenPair = { access_token: string; refresh_token: string; expires_in: number };

export function isTokenPair(value: unknown): value is TokenPair {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.access_token === "string" &&
    v.access_token.length > 0 &&
    typeof v.refresh_token === "string" &&
    v.refresh_token.length > 0 &&
    typeof v.expires_in === "number" &&
    v.expires_in > 0
  );
}
