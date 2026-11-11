import { type NextRequest, NextResponse } from "next/server";
import { isSameOrigin } from "@/lib/auth/origin";
import { isProxyablePath } from "@/lib/auth/paths";
import { refreshTokens } from "@/lib/auth/refresh";
import { expiresWithin } from "@/lib/auth/tokens";
import { ACCESS_COOKIE, REFRESH_COOKIE, apiBase } from "@/lib/config";
import { clearSession, clientAddress, setSession } from "@/lib/server/session";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ path: string[] }> };

// Headers worth passing back to the browser. Set-Cookie and anything else the API sends stay behind.
const RESPONSE_HEADERS = ["content-type", "x-trace-id", "retry-after"];

function problem(status: number, detail: string) {
  return NextResponse.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });
}

async function call(url: string, request: NextRequest, body: ArrayBuffer | undefined, token: string): Promise<Response> {
  const forwardedFor = clientAddress(request);
  const headers: Record<string, string> = { Authorization: `Bearer ${token}`, Accept: request.headers.get("accept") ?? "application/json" };
  const contentType = request.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;
  if (forwardedFor) headers["X-Forwarded-For"] = forwardedFor;
  return fetch(url, { method: request.method, headers, body, cache: "no-store", redirect: "manual" });
}

/**
 * The browser's way to the API: same origin, so there is no CORS, and the access token is added here from an httpOnly cookie. If the API says the token has
 * expired, it is refreshed once and the call retried. Only the parts of the API the interface uses are reachable (see lib/auth/paths.ts).
 */
async function handle(request: NextRequest, { params }: Context): Promise<Response> {
  const { path } = await params;
  if (!isProxyablePath(path)) return problem(404, "Not found.");
  if (!isSameOrigin(request)) return problem(403, "Cross-site request refused.");

  let access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  let renewed = null as Awaited<ReturnType<typeof refreshTokens>>;

  if (expiresWithin(access) && refresh) {
    renewed = await refreshTokens(refresh, clientAddress(request));
    if (!renewed) return clearSession(problem(401, "Your session has expired. Sign in again."));
    access = renewed.access_token;
  }
  if (!access) return problem(401, "Sign in to continue.");

  const url = `${apiBase()}/api/v1/${path.join("/")}${request.nextUrl.search}`;
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await call(url, request, body, access);
    if (upstream.status === 401 && refresh && !renewed) {
      renewed = await refreshTokens(refresh, clientAddress(request));
      if (!renewed) return clearSession(problem(401, "Your session has expired. Sign in again."));
      upstream = await call(url, request, body, renewed.access_token);
    }
  } catch {
    return problem(502, "The API is unreachable.");
  }

  const headers = new Headers({ "Cache-Control": "no-store" });
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (upstream.headers.get("content-type")?.startsWith("text/event-stream")) headers.set("X-Accel-Buffering", "no");
  const response = new NextResponse(upstream.body, { status: upstream.status, headers });
  return renewed ? setSession(response, renewed) : response;
}

export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };
