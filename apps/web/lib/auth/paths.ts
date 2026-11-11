/** The parts of the API the web app's proxy (/bff) will forward to. Everything else, including sign-in, token refresh, user creation and the webhook receivers, is not reachable from a browser through it. */
const ALLOWED = /^(contacts|companies|scoring|analytics|webhooks|models|integrations|leads)(\/|$)|^(auth\/me|system\/config)$/;
const SEGMENT = /^[A-Za-z0-9._~-]+$/;

export function isProxyablePath(segments: string[]): boolean {
  if (segments.length === 0) return false;
  if (!segments.every((s) => SEGMENT.test(s) && s !== "." && s !== "..")) return false;
  const path = segments.join("/");
  if (path.startsWith("analytics/conversions/hubspot")) return false; // the HubSpot webhook receiver: HubSpot calls it, a browser never does
  return ALLOWED.test(path);
}

/** Pages and routes that answer without a session: the sign-in page, and the session and proxy routes (which check the session themselves). Whole path segments only: "/sessions" is a different page. */
export function isPublicPath(pathname: string): boolean {
  return /^\/(login|session|bff)(\/|$)/.test(pathname);
}

const ORIGIN_FOR_PARSING = "https://app.invalid";

/**
 * Only same-site paths may be used as the page to return to after signing in. The value is checked the way the browser will read it, not as typed: URL parsers
 * drop tabs and line breaks anywhere ("/\t/evil.test" is "//evil.test"), read a backslash as a slash, and resolve "." and ".." ("/..//evil.test" is "//evil.test").
 * So control characters and backslashes are refused outright, and what is returned is the parsed path, which must still be this site and must not start "//".
 */
export function safeNext(value: string | null | undefined): string {
  if (!value || /[\u0000-\u001F\u007F\\]/.test(value)) return "/dashboard";
  if (!value.startsWith("/") || value.startsWith("//")) return "/dashboard";
  const parsed = new URL(value, ORIGIN_FOR_PARSING);
  if (parsed.origin !== ORIGIN_FOR_PARSING) return "/dashboard";
  const path = parsed.pathname + parsed.search + parsed.hash;
  if (path.startsWith("//")) return "/dashboard";
  if (/^\/(login|session|bff)(\/|\?|#|$)/.test(path)) return "/dashboard";
  return path;
}
