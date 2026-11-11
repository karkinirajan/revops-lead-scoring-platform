import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { config, proxy } from "@/proxy";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/config";
import { anHourAgo, headerOf, inOneHour, jwt, json, mockFetch, tokenPair } from "./helpers";

function page(path: string, cookies: Record<string, string> = {}, headers: Record<string, string> = {}) {
  const cookie = Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join("; ");
  return new NextRequest(`https://app.example.com${path}`, { headers: { ...(cookie ? { cookie } : {}), ...headers } });
}

beforeEach(() => vi.stubEnv("API_INTERNAL_URL", "http://api:8000"));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("proxy", () => {
  it("lets a signed-in user through without calling the API", async () => {
    const { fake } = mockFetch(json({}));
    const response = await proxy(page("/dashboard", { [ACCESS_COOKIE]: jwt(inOneHour()) }));
    expect(response.headers.get("x-middleware-next")).toBe("1");
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(fake).not.toHaveBeenCalled();
  });

  it("sends a signed-out visitor to /login and remembers the page", async () => {
    const response = await proxy(page("/leads?tier=HOT"));
    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/leads?tier=HOT");
  });

  it("does not remember the home page", async () => {
    const location = new URL((await proxy(page("/"))).headers.get("location")!);
    expect(location.search).toBe("");
  });

  it("renews an expired access token and lets the page see the new one", async () => {
    const renewed = tokenPair();
    mockFetch(json(renewed));
    const response = await proxy(page("/dashboard", { [ACCESS_COOKIE]: jwt(anHourAgo()), [REFRESH_COOKIE]: "old-refresh", theme: "dark" }));
    expect(response.headers.get("x-middleware-next")).toBe("1");
    const setCookie = response.headers.getSetCookie().join("\n");
    expect(setCookie).toContain(`${ACCESS_COOKIE}=${renewed.access_token}`);
    expect(setCookie).toContain(`${REFRESH_COOKIE}=${renewed.refresh_token}`);
    // the request the page is rendered for carries the new tokens (and the cookies that were not ours)
    const forwarded = response.headers.get("x-middleware-request-cookie");
    expect(forwarded).toContain(`${ACCESS_COOKIE}=${renewed.access_token}`);
    expect(forwarded).toContain("theme=dark");
    expect(forwarded).not.toContain("old-refresh");
  });

  it("renews when only the refresh cookie is left", async () => {
    mockFetch(json(tokenPair()));
    const response = await proxy(page("/runs", { [REFRESH_COOKIE]: "r" }));
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("signs out when the refresh token is refused", async () => {
    mockFetch(json({ detail: "Invalid refresh token" }, { status: 401 }));
    const response = await proxy(page("/runs", { [ACCESS_COOKIE]: jwt(anHourAgo()), [REFRESH_COOKIE]: "dead" }));
    expect(response.status).toBe(307);
    expect(new URL(response.headers.get("location")!).pathname).toBe("/login");
    const cleared = response.headers.getSetCookie();
    expect(cleared).toHaveLength(2);
    expect(cleared.every((c) => /Max-Age=0/i.test(c))).toBe(true);
  });

  it("signs out when the API cannot be reached", async () => {
    mockFetch(new Error("down"));
    const response = await proxy(page("/runs", { [REFRESH_COOKIE]: "r" }));
    expect(response.status).toBe(307);
    expect(response.headers.getSetCookie()).toHaveLength(2);
  });

  it("tells the API the browser's address when it renews a session", async () => {
    const { calls } = mockFetch(json(tokenPair()));
    await proxy(page("/dashboard", { [REFRESH_COOKIE]: "r" }, { "x-forwarded-for": "198.51.100.7" }));
    expect(calls[0].url).toBe("http://api:8000/api/v1/auth/refresh");
    expect(headerOf(calls[0].init, "x-forwarded-for")).toBe("198.51.100.7");
    expect(calls[0].init.cache).toBe("no-store");
  });

  it("sends a visitor with no tokens at all to sign in, clearing nothing that is not there", async () => {
    const { fake } = mockFetch(json({}));
    const response = await proxy(page("/runs"));
    expect(response.status).toBe(307);
    expect(fake).not.toHaveBeenCalled();
  });
});

describe("matcher", () => {
  const regex = new RegExp(`^${config.matcher[0]}$`);
  it.each(["/", "/dashboard", "/leads", "/login", "/session/login", "/bff/scoring/leads"])("runs for %s", (path) => expect(regex.test(path)).toBe(true));
  it.each(["/_next/static/chunk.js", "/_next/image", "/favicon.ico"])("skips static %s", (path) => expect(regex.test(path)).toBe(false));
});

describe("public paths", () => {
  it.each(["/login", "/session/login", "/session/logout", "/bff/scoring/leads", "/bff"])("%s needs no session here", async (path) => {
    const { fake } = mockFetch(json({}));
    const response = await proxy(page(path));
    expect(response.headers.get("x-middleware-next")).toBe("1");
    expect(fake).not.toHaveBeenCalled();
  });

  it.each(["/sessions", "/login-help", "/loginfo", "/bffx", "/sessionx/login"])("%s is a page like any other and needs a session", async (path) => {
    expect((await proxy(page(path))).status).toBe(307);
  });
});
