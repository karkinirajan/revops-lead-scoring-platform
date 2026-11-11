const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * CSRF check for requests that change something. The session cookies are SameSite=Lax, which already keeps them off cross-site POSTs; this also requires the
 * browser's `Origin` header to name this site. A request without an Origin (a script, not a browser) is refused: the web app's own pages always send one.
 */
export function isSameOrigin(request: Request): boolean {
  if (SAFE_METHODS.has(request.method)) return true; // Request normalises the case of the methods that matter here
  const origin = request.headers.get("origin");
  if (!origin) return false;
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}
