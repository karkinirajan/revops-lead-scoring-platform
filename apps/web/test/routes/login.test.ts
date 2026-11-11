import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "@/app/session/login/route";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/config";
import { headerOf, json, mockFetch, tokenPair } from "../helpers";

const ORIGIN = { origin: "https://app.example.com", host: "app.example.com" };

function login(body: unknown, headers: Record<string, string> = ORIGIN) {
  return POST(new Request("https://app.example.com/session/login", { method: "POST", headers: { "content-type": "application/json", ...headers }, body: typeof body === "string" ? body : JSON.stringify(body) }));
}

beforeEach(() => vi.stubEnv("API_INTERNAL_URL", "http://api:8000"));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("POST /session/login", () => {
  it("signs in: httpOnly cookies, no tokens in the body", async () => {
    const pair = tokenPair();
    const { calls } = mockFetch(json({ ...pair, token_type: "bearer" }));
    const response = await login({ email: "ada@example.com", password: "correct-horse-battery" });
    expect(response.status).toBe(200);
    const text = await response.text();
    expect(JSON.parse(text)).toEqual({ ok: true });
    expect(text).not.toContain(pair.access_token);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const set = response.headers.getSetCookie().join("\n");
    expect(set).toContain(`${ACCESS_COOKIE}=${pair.access_token}`);
    expect(set).toContain(`${REFRESH_COOKIE}=${pair.refresh_token}`);
    expect(set.match(/HttpOnly/gi)).toHaveLength(2);
    expect(set).toMatch(/SameSite=lax/i);
    expect(calls[0].url).toBe("http://api:8000/api/v1/auth/login");
    expect(calls[0].init.cache).toBe("no-store");
    expect(calls[0].init.method).toBe("POST");
    expect(headerOf(calls[0].init, "content-type")).toBe("application/json");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ email: "ada@example.com", password: "correct-horse-battery" });
  });

  it("passes the browser's address on so the API rate-limits the user, not this server", async () => {
    const { calls } = mockFetch(json(tokenPair()));
    await login({ email: "a@b.co", password: "x" }, { ...ORIGIN, "x-forwarded-for": "203.0.113.9" });
    expect(headerOf(calls[0].init, "x-forwarded-for")).toBe("203.0.113.9");
  });

  it("sends no forwarded address when there is none", async () => {
    const { calls } = mockFetch(json(tokenPair()));
    await login({ email: "a@b.co", password: "x" });
    expect(headerOf(calls[0].init, "x-forwarded-for")).toBeUndefined();
  });

  it.each([
    [401, 401, "Invalid email or password."],
    [403, 403, "This account is inactive."],
    [422, 422, "Enter a valid email and password."],
    [429, 429, "Too many attempts. Wait a minute and try again."],
    [500, 502, "The sign-in service is unavailable. Try again shortly."],
    [503, 502, "The sign-in service is unavailable. Try again shortly."],
  ])("maps the API's %i to %i with a fixed message", async (upstream, status, message) => {
    mockFetch(json({ detail: "internal detail with sk-secret and a stack trace" }, { status: upstream }));
    const response = await login({ email: "a@b.co", password: "x" });
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ detail: message });
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("reports an unreachable API as 502", async () => {
    mockFetch(new Error("connect ECONNREFUSED"));
    const response = await login({ email: "a@b.co", password: "x" });
    expect(response.status).toBe(502);
    expect(JSON.stringify(await response.json())).not.toContain("ECONNREFUSED");
  });

  it.each([[{}], [{ access_token: "a" }], [{ ...tokenPair(), expires_in: 0 }], [null], ["text"]])("treats an answer that is not a token pair (%j) as a failure", async (body) => {
    mockFetch(json(body));
    const response = await login({ email: "a@b.co", password: "x" });
    expect(response.status).toBe(502);
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("refuses a sign-in from another site, without calling the API", async () => {
    const { fake } = mockFetch(json(tokenPair()));
    const response = await login({ email: "a@b.co", password: "x" }, { origin: "https://evil.example", host: "app.example.com" });
    expect(response.status).toBe(403);
    expect(fake).not.toHaveBeenCalled();
  });

  it("refuses a request without an Origin", async () => {
    const { fake } = mockFetch(json(tokenPair()));
    expect((await login({ email: "a@b.co", password: "x" }, { host: "app.example.com" })).status).toBe(403);
    expect(fake).not.toHaveBeenCalled();
  });

  it.each([["not json"], [[]], [{}], [{ email: "a@b.co" }], [{ password: "x" }], [{ email: 5, password: "x" }], [{ email: "a@b.co", password: ["x"] }], [{ email: "", password: "x" }], [{ email: "a@b.co", password: "" }]])(
    "refuses a body that is %j",
    async (body) => {
      const { fake } = mockFetch(json(tokenPair()));
      const response = await login(body);
      expect(response.status).toBe(400);
      expect(fake).not.toHaveBeenCalled();
    },
  );
});
