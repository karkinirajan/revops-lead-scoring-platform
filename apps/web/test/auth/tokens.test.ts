import { describe, expect, it } from "vitest";
import { expiresWithin, isTokenPair, tokenExpiry } from "@/lib/auth/tokens";
import { anHourAgo, inOneHour, jwt } from "../helpers";

describe("tokenExpiry", () => {
  it("reads exp from the payload", () => {
    expect(tokenExpiry(jwt(1_800_000_000))).toBe(1_800_000_000);
  });

  it.each([undefined, null, "", "abc", "a.b", "a.b.c.d", "a.!!!.c", `a.${Buffer.from("not json").toString("base64url")}.c`])("is null for %j", (value) => {
    expect(tokenExpiry(value as string | undefined)).toBeNull();
  });

  it.each([["a string", "soon"], ["null", null], ["a float NaN", Number.NaN], ["Infinity", Number.POSITIVE_INFINITY]])("is null when exp is %s", (_name, exp) => {
    const payload = Buffer.from(JSON.stringify({ exp })).toString("base64url");
    expect(tokenExpiry(`h.${payload}.s`)).toBeNull();
  });

  it("is null for anything but three parts, even with a valid payload where it would be read", () => {
    const payload = Buffer.from(JSON.stringify({ exp: 1_800_000_000 })).toString("base64url");
    expect(tokenExpiry(`h.${payload}`)).toBeNull();
    expect(tokenExpiry(`h.${payload}.s.extra`)).toBeNull();
    expect(tokenExpiry(`h.${payload}.s`)).toBe(1_800_000_000);
  });

  it("is null when exp is a number JSON can write but no clock can use", () => {
    expect(tokenExpiry(`h.${Buffer.from('{"exp":1e999}').toString("base64url")}.s`)).toBeNull(); // parses to Infinity
  });

  it("is null when there is no exp", () => {
    expect(tokenExpiry(jwt(undefined))).toBeNull();
  });

  it("reads base64url payloads that use - and _", () => {
    const payload = Buffer.from(JSON.stringify({ exp: 1_800_000_000, note: "??>>~~" })).toString("base64url");
    expect(payload).toMatch(/[-_]/);
    expect(tokenExpiry(`h.${payload}.s`)).toBe(1_800_000_000);
  });
});

describe("expiresWithin", () => {
  const now = 1_700_000_000_000;
  it("is false for a token with plenty of time", () => {
    expect(expiresWithin(jwt(now / 1000 + 600), 30, now)).toBe(false);
  });
  it("is true inside the margin, at it, and after it", () => {
    expect(expiresWithin(jwt(now / 1000 + 29), 30, now)).toBe(true);
    expect(expiresWithin(jwt(now / 1000 + 30), 30, now)).toBe(true);
    expect(expiresWithin(jwt(now / 1000 + 31), 30, now)).toBe(false);
    expect(expiresWithin(jwt(now / 1000 - 5), 30, now)).toBe(true);
  });
  it("is true when there is no usable token", () => {
    expect(expiresWithin(undefined)).toBe(true);
    expect(expiresWithin("garbage")).toBe(true);
  });
  it("uses the clock and a 30 second margin by default", () => {
    expect(expiresWithin(jwt(inOneHour()))).toBe(false);
    expect(expiresWithin(jwt(anHourAgo()))).toBe(true);
    expect(expiresWithin(jwt(Math.floor(Date.now() / 1000) + 10))).toBe(true);
  });
});

describe("isTokenPair", () => {
  const good = { access_token: "a", refresh_token: "r", expires_in: 3600 };
  it("accepts a complete pair", () => expect(isTokenPair(good)).toBe(true));
  it.each([null, undefined, "x", 5, [], {}, { ...good, access_token: "" }, { ...good, refresh_token: "" }, { ...good, access_token: 5 }, { ...good, expires_in: "3600" }, { ...good, expires_in: 0 }, { ...good, expires_in: -1 }])(
    "rejects %j",
    (value) => expect(isTokenPair(value)).toBe(false),
  );
});
