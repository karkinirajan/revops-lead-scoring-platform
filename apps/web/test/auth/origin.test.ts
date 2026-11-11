import { describe, expect, it } from "vitest";
import { isSameOrigin } from "@/lib/auth/origin";

const request = (method: string, headers: Record<string, string>) => new Request("https://app.example.com/session/login", { method, headers });

describe("isSameOrigin", () => {
  it.each(["GET", "HEAD", "OPTIONS", "get"])("lets %s through without checking", (method) => {
    expect(isSameOrigin(request(method, {}))).toBe(true);
  });

  it.each(["POST", "PATCH", "DELETE", "PUT"])("lets a %s from this site through", (method) => {
    expect(isSameOrigin(request(method, { origin: "https://app.example.com", host: "app.example.com" }))).toBe(true);
  });

  it("refuses a change from another site", () => {
    expect(isSameOrigin(request("POST", { origin: "https://evil.example", host: "app.example.com" }))).toBe(false);
  });

  it("refuses a change that names no origin at all", () => {
    expect(isSameOrigin(request("POST", { host: "app.example.com" }))).toBe(false);
  });

  it("refuses an origin that is not a URL", () => {
    expect(isSameOrigin(request("POST", { origin: "null", host: "app.example.com" }))).toBe(false);
  });

  it("refuses when the request names no host", () => {
    expect(isSameOrigin(request("POST", { origin: "https://app.example.com" }))).toBe(false);
  });

  it("does not accept a look-alike host", () => {
    expect(isSameOrigin(request("POST", { origin: "https://app.example.com.evil.test", host: "app.example.com" }))).toBe(false);
    expect(isSameOrigin(request("POST", { origin: "https://evilapp.example.com", host: "app.example.com" }))).toBe(false);
  });

  it("compares the port too", () => {
    expect(isSameOrigin(request("POST", { origin: "http://localhost:3000", host: "localhost:3000" }))).toBe(true);
    expect(isSameOrigin(request("POST", { origin: "http://localhost:4000", host: "localhost:3000" }))).toBe(false);
  });

  it("behind a proxy, the forwarded host is the one the browser used", () => {
    expect(isSameOrigin(request("POST", { origin: "https://public.example.com", host: "web:3000", "x-forwarded-host": "public.example.com" }))).toBe(true);
    expect(isSameOrigin(request("POST", { origin: "https://web:3000", host: "web:3000", "x-forwarded-host": "public.example.com" }))).toBe(false);
  });
});
