// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchApi, getCompanies, getLeads, getRun, signOut, simulateScore, triggerScoringRun } from "@/lib/api";
import { headerOf, json, mockFetch } from "./helpers";

const assign = vi.fn();

beforeEach(() => {
  assign.mockClear();
  Object.defineProperty(window, "location", { configurable: true, value: { pathname: "/leads", search: "?tier=HOT", assign } });
});
afterEach(() => vi.unstubAllGlobals());

describe("fetchApi", () => {
  it("calls the same-origin proxy with the session cookie, uncached", async () => {
    const { calls } = mockFetch(json({ ok: 1 }));
    expect(await fetchApi("/scoring/runs")).toEqual({ ok: 1 });
    expect(calls[0].url).toBe("/bff/scoring/runs");
    expect(calls[0].init.credentials).toBe("same-origin");
    expect(calls[0].init.cache).toBe("no-store");
  });

  it("adds a JSON content type when there is a body, and not otherwise", async () => {
    const { calls } = mockFetch(json({}));
    await fetchApi("/x", { method: "POST", body: "{}" });
    await fetchApi("/x");
    expect(headerOf(calls[0].init, "content-type")).toBe("application/json");
    expect(headerOf(calls[1].init, "content-type")).toBeUndefined();
  });

  it("keeps a content type the caller chose", async () => {
    const { calls } = mockFetch(json({}));
    await fetchApi("/x", { method: "POST", body: "a=1", headers: { "Content-Type": "text/plain" } });
    expect(headerOf(calls[0].init, "content-type")).toBe("text/plain");
  });

  it("returns undefined for 204", async () => {
    mockFetch(new Response(null, { status: 204 }));
    expect(await fetchApi("/webhooks/1", { method: "DELETE" })).toBeUndefined();
  });

  it("sends an expired session to sign in", async () => {
    mockFetch(json({ detail: "Sign in to continue." }, { status: 401 }));
    await expect(fetchApi("/scoring/runs")).rejects.toMatchObject({ status: 401 });
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fleads%3Ftier%3DHOT");
  });

  it("turns an error response into an ApiError with the API's message", async () => {
    mockFetch(json({ detail: [{ msg: "Field required" }] }, { status: 422 }));
    const error = (await fetchApi("/x").catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.message]).toEqual([422, "Field required"]);
    expect(assign).not.toHaveBeenCalled();
  });

  it("falls back to the status text when the error body is not JSON", async () => {
    mockFetch(new Response("<html>", { status: 502, statusText: "Bad Gateway" }));
    expect(((await fetchApi("/x").catch((e: unknown) => e)) as ApiError).message).toBe("Bad Gateway");
  });

  it("says the request failed when there is no status text either", async () => {
    mockFetch(new Response("<html>", { status: 500 }));
    expect(((await fetchApi("/x").catch((e: unknown) => e)) as ApiError).message).toBe("Request failed");
  });

  it("explains a network failure", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    const error = (await fetchApi("/x").catch((e: unknown) => e)) as ApiError;
    expect([error.status, error.message]).toEqual([0, "Could not reach the server. Check your connection."]);
  });
});

describe("the calls", () => {
  it("getLeads builds the query from what is set", async () => {
    const { calls } = mockFetch(json({ items: [] }));
    await getLeads({ page: 2, page_size: 50, priority_tier: "HOT", min_score: 0, company_id: "c1" });
    await getLeads({});
    expect(calls[0].url).toBe("/bff/scoring/leads?page=2&page_size=50&priority_tier=HOT&min_score=0&company_id=c1");
    expect(calls[1].url).toBe("/bff/scoring/leads?");
  });

  it("getCompanies encodes the search", async () => {
    const { calls } = mockFetch(json({ items: [] }));
    await getCompanies({ search: "R&D / Labs", size_tier: "smb" });
    expect(calls[0].url).toBe("/bff/companies?size_tier=smb&search=R%26D+%2F+Labs");
  });

  it("triggerScoringRun posts the options", async () => {
    const { calls } = mockFetch(json({ id: "run-1" }));
    await triggerScoringRun({ is_shadow: true });
    await triggerScoringRun();
    expect([calls[0].init.method, calls[0].init.body]).toEqual(["POST", '{"is_shadow":true}']);
    expect(calls[1].init.body).toBe("{}");
  });

  it("getRun encodes the id so it cannot change the path", async () => {
    const { calls } = mockFetch(json({}));
    await getRun("a/b?c");
    expect(calls[0].url).toBe("/bff/scoring/runs/a%2Fb%3Fc");
  });

  it("simulateScore posts the features", async () => {
    const { calls } = mockFetch(json({ lead_score: 40 }));
    await simulateScore({ api_calls_7d: 5 } as never);
    expect([calls[0].url, calls[0].init.method, calls[0].init.body]).toEqual(["/bff/scoring/simulate", "POST", '{"api_calls_7d":5}']);
  });

  it("signOut posts to the session route", async () => {
    const { calls } = mockFetch(json({ ok: true }));
    await signOut();
    expect([calls[0].url, calls[0].init.method, calls[0].init.credentials]).toEqual(["/session/logout", "POST", "same-origin"]);
  });
});
