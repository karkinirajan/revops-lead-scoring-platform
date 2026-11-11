import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ACCESS_COOKIE } from "@/lib/config";
import { ApiError } from "@/lib/errors";
import { headerOf, json, mockFetch } from "./helpers";

let cookieValue: string | undefined;
const redirect = vi.fn((url: string) => {
  throw new Error(`NEXT_REDIRECT ${url}`);
});

vi.mock("next/headers", () => ({ cookies: async () => ({ get: (name: string) => (name === ACCESS_COOKIE && cookieValue ? { name, value: cookieValue } : undefined) }) }));
vi.mock("next/navigation", () => ({ redirect: (url: string) => redirect(url) }));

const { apiFetch } = await import("@/lib/server/api");

beforeEach(() => {
  cookieValue = "access-jwt";
  redirect.mockClear();
  vi.stubEnv("API_INTERNAL_URL", "http://api:8000/");
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("calls the API as the signed-in user and does not cache", async () => {
    const { calls } = mockFetch(json({ total: 3 }));
    expect(await apiFetch<{ total: number }>("/scoring/leads?page_size=1")).toEqual({ total: 3 });
    expect(calls[0].url).toBe("http://api:8000/api/v1/scoring/leads?page_size=1");
    expect(headerOf(calls[0].init, "authorization")).toBe("Bearer access-jwt");
    expect(calls[0].init.cache).toBe("no-store");
  });

  it("keeps the caller's headers and method", async () => {
    const { calls } = mockFetch(json({}));
    await apiFetch("/scoring/runs", { method: "POST", headers: { "X-Test": "1" }, body: "{}" });
    expect(calls[0].init.method).toBe("POST");
    expect(headerOf(calls[0].init, "x-test")).toBe("1");
    expect(headerOf(calls[0].init, "authorization")).toBe("Bearer access-jwt");
  });

  it("a caller cannot replace the token", async () => {
    const { calls } = mockFetch(json({}));
    await apiFetch("/x", { headers: { Authorization: "Bearer someone-else" } });
    expect(headerOf(calls[0].init, "authorization")).toBe("Bearer access-jwt");
  });

  it("sends a user with no session to sign in, without calling the API", async () => {
    cookieValue = undefined;
    const { fake } = mockFetch(json({}));
    await expect(apiFetch("/scoring/runs")).rejects.toThrow("NEXT_REDIRECT /login");
    expect(fake).not.toHaveBeenCalled();
  });

  it("sends a user the API rejects to sign in", async () => {
    mockFetch(json({ detail: "Could not validate credentials" }, { status: 401 }));
    await expect(apiFetch("/scoring/runs")).rejects.toThrow("NEXT_REDIRECT /login");
  });

  it("turns other errors into an ApiError carrying the API's message", async () => {
    mockFetch(json({ detail: "Insufficient permissions" }, { status: 403 }));
    const error = (await apiFetch("/models").catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.message]).toEqual([403, "Insufficient permissions"]);
  });

  it("has a message when the error body is not JSON", async () => {
    mockFetch(new Response("<html>bad gateway</html>", { status: 502 }));
    const error = (await apiFetch("/models").catch((e: unknown) => e)) as ApiError;
    expect([error.status, error.message]).toEqual([502, "The API answered 502."]);
  });

  it("reports an unreachable API without exposing why", async () => {
    mockFetch(new Error("connect ECONNREFUSED 10.1.2.3:8000"));
    const error = (await apiFetch("/models").catch((e: unknown) => e)) as ApiError;
    expect([error.status, error.message]).toEqual([502, "The API is unreachable."]);
  });
});
