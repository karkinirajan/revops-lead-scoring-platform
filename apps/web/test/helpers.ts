import { vi } from "vitest";

/** A JWT-shaped string whose payload says it expires at `exp` (seconds). Not signed: nothing in the web app checks signatures. */
export function jwt(exp: number | undefined, extra: Record<string, unknown> = {}): string {
  const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: "user-1", jti: crypto.randomUUID(), ...(exp === undefined ? {} : { exp }), ...extra })}.signature`;
}

export const inOneHour = () => Math.floor(Date.now() / 1000) + 3600;
export const anHourAgo = () => Math.floor(Date.now() / 1000) - 3600;

export function tokenPair(overrides: Partial<{ access_token: string; refresh_token: string; expires_in: number }> = {}) {
  return { access_token: jwt(inOneHour()), refresh_token: jwt(inOneHour() + 86400 * 7, { type: "refresh" }), expires_in: 3600, ...overrides };
}

export function json(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" }, ...init });
}

/** Replace `fetch` with a function that answers from a queue (or a function) and records its calls. */
export function mockFetch(...answers: Array<Response | Error | ((url: string, init: RequestInit) => Response | Promise<Response>)>) {
  const queue = [...answers];
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const fake = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    calls.push({ url, init });
    const next = queue.length > 1 ? queue.shift()! : queue[0];
    if (next instanceof Error) throw next;
    return typeof next === "function" ? next(url, init) : next.clone();
  });
  vi.stubGlobal("fetch", fake);
  return { fake, calls };
}

export function headerOf(init: RequestInit, name: string): string | undefined {
  const headers = new Headers(init.headers);
  return headers.get(name) ?? undefined;
}

/**
 * Replace `fetch` with answers chosen by URL, each URL with its own queue of answers (the last one repeats).
 * A request to a URL with no route fails the test, so a component cannot quietly make a call the test did not expect.
 */
export function routeFetch(routes: Record<string, Array<Response | Error>>) {
  const queues = new Map(Object.entries(routes).map(([url, answers]) => [url, [...answers]]));
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const fake = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    calls.push({ url, init });
    const queue = queues.get(url);
    if (!queue) throw new Error(`routeFetch: unexpected request to ${url}`);
    const next = queue.length > 1 ? queue.shift()! : queue[0];
    if (next instanceof Error) throw next;
    return next.clone();
  });
  vi.stubGlobal("fetch", fake);
  return { fake, calls };
}
