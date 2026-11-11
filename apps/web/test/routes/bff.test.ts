import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DELETE, GET, PATCH, POST } from "@/app/bff/[...path]/route";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/config";
import { anHourAgo, headerOf, inOneHour, jwt, json, mockFetch, tokenPair } from "../helpers";

const HOST = { origin: "https://app.example.com", host: "app.example.com" };

type Options = { method?: string; cookies?: Record<string, string>; headers?: Record<string, string>; body?: string; query?: string };

function request(path: string, { method = "GET", cookies, headers = {}, body, query = "" }: Options = {}) {
  const cookie = cookies ? Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join("; ") : undefined;
  return new NextRequest(`https://app.example.com/bff/${path}${query}`, { method, body, headers: { ...HOST, ...(cookie ? { cookie } : {}), ...headers } });
}

const call = (handler: typeof GET, path: string, options?: Options) => handler(request(path, options), { params: Promise.resolve({ path: path.split("/") }) });
const valid = () => ({ [ACCESS_COOKIE]: jwt(inOneHour()), [REFRESH_COOKIE]: jwt(inOneHour() + 86400, { type: "refresh" }) });

beforeEach(() => vi.stubEnv("API_INTERNAL_URL", "http://api:8000"));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("which paths", () => {
  it.each(["auth/login", "auth/refresh", "auth/users", "ingest", "analytics/conversions/hubspot", "health", "scoring/../auth/login"])("%s is not forwarded", async (path) => {
    const { fake } = mockFetch(json({}));
    const response = await call(GET, path, { cookies: valid() });
    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fake).not.toHaveBeenCalled();
  });
});

describe("forwarding", () => {
  it("adds the user's token from the cookie, and passes the query and the answer back", async () => {
    const cookies = valid();
    const { calls } = mockFetch(json({ items: [], total: 0 }));
    const response = await call(GET, "scoring/leads", { cookies, query: "?page=2&priority_tier=HOT" });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ items: [], total: 0 });
    expect(calls[0].url).toBe("http://api:8000/api/v1/scoring/leads?page=2&priority_tier=HOT");
    expect(headerOf(calls[0].init, "authorization")).toBe(`Bearer ${cookies[ACCESS_COOKIE]}`);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(calls[0].init.cache).toBe("no-store");
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.body).toBeUndefined();
    expect(headerOf(calls[0].init, "accept")).toBe("application/json");
    expect(response.headers.get("x-accel-buffering")).toBeNull(); // only event streams are sent unbuffered
  });

  it("passes on the browser's Accept, which an event stream needs", async () => {
    const { calls } = mockFetch(json({}));
    await call(GET, "contacts/abc/intelligence", { cookies: valid(), headers: { accept: "text/event-stream" } });
    expect(headerOf(calls[0].init, "accept")).toBe("text/event-stream");
  });

  it("passes the API's Retry-After on, so the interface can say when to try again", async () => {
    mockFetch(json({ detail: "Too many requests" }, { status: 429, headers: { "Content-Type": "application/json", "Retry-After": "42" } }));
    const response = await call(GET, "scoring/runs", { cookies: valid() });
    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("42");
  });

  it("sends a JSON body on, with its content type", async () => {
    const { calls } = mockFetch(json({ id: "run-1" }, { status: 202 }));
    const response = await call(POST, "scoring/runs", { method: "POST", cookies: valid(), body: '{"is_shadow":true}', headers: { "content-type": "application/json" } });
    expect(response.status).toBe(202);
    expect(calls[0].init.method).toBe("POST");
    expect(Buffer.from(calls[0].init.body as ArrayBuffer).toString()).toBe('{"is_shadow":true}');
    expect(headerOf(calls[0].init, "content-type")).toBe("application/json");
  });

  it.each([[PATCH, "PATCH"], [DELETE, "DELETE"]] as const)("forwards %s", async (handler, method) => {
    const { calls } = mockFetch(new Response(null, { status: 204 }));
    const response = await call(handler, "webhooks/1", { method, cookies: valid() });
    expect(response.status).toBe(204);
    expect(calls[0].init.method).toBe(method);
  });

  it("passes the browser's address on", async () => {
    const { calls } = mockFetch(json({}));
    await call(GET, "scoring/runs", { cookies: valid(), headers: { "x-forwarded-for": "198.51.100.7" } });
    expect(headerOf(calls[0].init, "x-forwarded-for")).toBe("198.51.100.7");
  });

  it("does not hand the API's cookies or other headers to the browser", async () => {
    mockFetch(json({ ok: 1 }, { headers: { "Content-Type": "application/json", "Set-Cookie": "evil=1", "X-Trace-Id": "t-1", Server: "uvicorn", "X-Secret": "s" } }));
    const response = await call(GET, "scoring/runs", { cookies: valid() });
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("server")).toBeNull();
    expect(response.headers.get("x-secret")).toBeNull();
    expect(response.headers.get("x-trace-id")).toBe("t-1");
  });

  it("streams server-sent events through unbuffered", async () => {
    const stream = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('data: {"chunk":"hi"}\n\n')); c.close(); } });
    mockFetch(new Response(stream, { headers: { "Content-Type": "text/event-stream" } }));
    const response = await call(GET, "contacts/abc/intelligence", { cookies: valid() });
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(await response.text()).toBe('data: {"chunk":"hi"}\n\n');
  });

  it("passes the API's own errors through with their status", async () => {
    mockFetch(json({ detail: "Insufficient permissions" }, { status: 403 }));
    const response = await call(POST, "integrations", { method: "POST", cookies: valid(), body: "{}" });
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: "Insufficient permissions" });
  });

  it("reports an unreachable API as 502", async () => {
    mockFetch(new Error("connect ECONNREFUSED 10.0.0.5:8000"));
    const response = await call(GET, "scoring/runs", { cookies: valid() });
    expect(response.status).toBe(502);
    expect(JSON.stringify(await response.json())).not.toContain("10.0.0.5");
  });

  it("does not follow redirects from the API", async () => {
    const { calls } = mockFetch(json({}));
    await call(GET, "scoring/runs", { cookies: valid() });
    expect(calls[0].init.redirect).toBe("manual");
  });
});

describe("who may call", () => {
  it("answers 401 without a session", async () => {
    const { fake } = mockFetch(json({}));
    const response = await call(GET, "scoring/runs");
    expect(response.status).toBe(401);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fake).not.toHaveBeenCalled();
  });

  it("refuses a change from another site", async () => {
    const { fake } = mockFetch(json({}));
    const response = await call(POST, "scoring/runs", { method: "POST", cookies: valid(), body: "{}", headers: { origin: "https://evil.example" } });
    expect(response.status).toBe(403);
    expect(fake).not.toHaveBeenCalled();
  });

  it("refuses a change with no Origin", async () => {
    const { fake } = mockFetch(json({}));
    const req = new NextRequest("https://app.example.com/bff/scoring/runs", { method: "POST", body: "{}", headers: { host: "app.example.com", cookie: `${ACCESS_COOKIE}=${jwt(inOneHour())}` } });
    const response = await POST(req, { params: Promise.resolve({ path: ["scoring", "runs"] }) });
    expect(response.status).toBe(403);
    expect(fake).not.toHaveBeenCalled();
  });

  it("lets a read from anywhere reach the session check", async () => {
    mockFetch(json({}));
    const response = await call(GET, "scoring/runs", { cookies: valid(), headers: { origin: "https://evil.example" } });
    expect(response.status).toBe(200); // a cross-site GET can read nothing: the answer is not readable cross-origin, and CORS is not enabled
  });
});

describe("refreshing", () => {
  it("renews an expired access token before calling, and sets the new cookies", async () => {
    const renewed = tokenPair();
    const { calls } = mockFetch((url) => (url.endsWith("/auth/refresh") ? json(renewed) : json({ ok: true })));
    const cookies = { [ACCESS_COOKIE]: jwt(anHourAgo()), [REFRESH_COOKIE]: "old-refresh" };
    const response = await call(GET, "scoring/runs", { cookies });
    expect(response.status).toBe(200);
    expect(calls.map((c) => c.url)).toEqual(["http://api:8000/api/v1/auth/refresh", "http://api:8000/api/v1/scoring/runs"]);
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ refresh_token: "old-refresh" });
    expect(headerOf(calls[1].init, "authorization")).toBe(`Bearer ${renewed.access_token}`);
    expect(response.headers.getSetCookie().join("\n")).toContain(`${ACCESS_COOKIE}=${renewed.access_token}`);
  });

  it("renews with just a refresh cookie", async () => {
    const renewed = tokenPair();
    mockFetch((url) => (url.endsWith("/auth/refresh") ? json(renewed) : json({})));
    const response = await call(GET, "scoring/runs", { cookies: { [REFRESH_COOKIE]: "r" } });
    expect(response.status).toBe(200);
  });

  it("retries once when the API says the token is bad, with a fresh one", async () => {
    const renewed = tokenPair();
    const { calls } = mockFetch(
      (url, init) => {
        if (url.endsWith("/auth/refresh")) return json(renewed);
        return headerOf(init, "authorization") === `Bearer ${renewed.access_token}` ? json({ ok: true }) : json({ detail: "Could not validate credentials" }, { status: 401 });
      },
    );
    const response = await call(GET, "scoring/runs", { cookies: valid() });
    expect(response.status).toBe(200);
    expect(calls.map((c) => c.url.split("/api/v1")[1])).toEqual(["/scoring/runs", "/auth/refresh", "/scoring/runs"]);
    expect(response.headers.getSetCookie().join("\n")).toContain(renewed.access_token);
  });

  it("does not refresh twice: a token renewed up front that the API still refuses is not renewed again", async () => {
    const { calls } = mockFetch((url) => (url.endsWith("/auth/refresh") ? json(tokenPair()) : json({ detail: "no" }, { status: 401 })));
    const response = await call(GET, "scoring/runs", { cookies: { [ACCESS_COOKIE]: jwt(anHourAgo()), [REFRESH_COOKIE]: "old-refresh" } });
    expect(response.status).toBe(401);
    expect(calls.map((c) => c.url.split("/api/v1")[1])).toEqual(["/auth/refresh", "/scoring/runs"]);
  });

  it("tells the API the browser's address when it refreshes", async () => {
    const { calls } = mockFetch((url) => (url.endsWith("/auth/refresh") ? json(tokenPair()) : json({})));
    await call(GET, "scoring/runs", { cookies: { [REFRESH_COOKIE]: "r" }, headers: { "x-forwarded-for": "198.51.100.7" } });
    expect(headerOf(calls[0].init, "x-forwarded-for")).toBe("198.51.100.7");
    expect(headerOf(calls[0].init, "content-type")).toBe("application/json");
    expect(calls[0].init.cache).toBe("no-store");
  });

  it("ends the session when the API refuses the token and then the refresh too", async () => {
    mockFetch((url) => (url.endsWith("/auth/refresh") ? json({ detail: "Invalid refresh token" }, { status: 401 }) : json({ detail: "Could not validate credentials" }, { status: 401 })));
    const response = await call(GET, "scoring/runs", { cookies: valid() });
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ detail: "Your session has expired. Sign in again." });
    const cleared = response.headers.getSetCookie();
    expect(cleared).toHaveLength(2);
    expect(cleared.every((c) => /Max-Age=0/i.test(c))).toBe(true);
  });

  it("does not loop: a second 401 is passed on", async () => {
    mockFetch((url) => (url.endsWith("/auth/refresh") ? json(tokenPair()) : json({ detail: "no" }, { status: 401 })));
    const response = await call(GET, "scoring/runs", { cookies: valid() });
    expect(response.status).toBe(401);
  });

  it("ends the session when the refresh token is refused", async () => {
    mockFetch(json({ detail: "Invalid refresh token" }, { status: 401 }));
    const response = await call(GET, "scoring/runs", { cookies: { [ACCESS_COOKIE]: jwt(anHourAgo()), [REFRESH_COOKIE]: "dead" } });
    expect(response.status).toBe(401);
    expect(response.headers.getSetCookie().every((c) => /Max-Age=0/i.test(c))).toBe(true);
    expect(response.headers.getSetCookie()).toHaveLength(2);
  });

  it("does not try to refresh without a refresh cookie", async () => {
    const { calls } = mockFetch(json({ detail: "no" }, { status: 401 }));
    const response = await call(GET, "scoring/runs", { cookies: { [ACCESS_COOKIE]: jwt(inOneHour()) } });
    expect(response.status).toBe(401);
    expect(calls).toHaveLength(1);
  });

  it("replays the body of a POST on the retry", async () => {
    const renewed = tokenPair();
    const bodies: string[] = [];
    mockFetch((url, init) => {
      if (url.endsWith("/auth/refresh")) return json(renewed);
      bodies.push(Buffer.from(init.body as ArrayBuffer).toString());
      return bodies.length === 1 ? json({ detail: "expired" }, { status: 401 }) : json({ id: "1" }, { status: 202 });
    });
    const response = await call(POST, "scoring/runs", { method: "POST", cookies: valid(), body: '{"a":1}', headers: { "content-type": "application/json" } });
    expect(response.status).toBe(202);
    expect(bodies).toEqual(['{"a":1}', '{"a":1}']);
  });

  it("treats a refresh answer that is not a token pair as a refusal", async () => {
    mockFetch(json({ access_token: "only" }));
    const response = await call(GET, "scoring/runs", { cookies: { [REFRESH_COOKIE]: "r" } });
    expect(response.status).toBe(401);
  });
});
