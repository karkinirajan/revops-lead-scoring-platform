import { NextResponse } from "next/server";
import { describe, expect, it } from "vitest";
import { clearSession, clientAddress, setSession } from "@/lib/server/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/config";
import { tokenPair } from "./helpers";

const request = (headers: Record<string, string>) => new Request("https://app.example.com/x", { headers });

describe("clientAddress", () => {
  it("is the address the reverse proxy reported", () => expect(clientAddress(request({ "x-forwarded-for": "203.0.113.9" }))).toBe("203.0.113.9"));
  it("is the last of several: the one the nearest proxy added", () => expect(clientAddress(request({ "x-forwarded-for": "203.0.113.9, 10.0.0.1, 10.0.0.2" }))).toBe("10.0.0.2"));
  it("is not the address a client put in front of it", () => expect(clientAddress(request({ "x-forwarded-for": "6.6.6.6, 203.0.113.9" }))).toBe("203.0.113.9"));
  it("ignores spaces around it", () => expect(clientAddress(request({ "x-forwarded-for": "6.6.6.6,   203.0.113.9  " }))).toBe("203.0.113.9"));
  it("is null when there is no header", () => expect(clientAddress(request({}))).toBeNull());
  it("is null, not an empty string, when the last entry is empty", () => expect(clientAddress(request({ "x-forwarded-for": "10.0.0.1, " }))).toBeNull());
});

describe("setSession and clearSession", () => {
  it("sets both cookies on the response, and returns it", () => {
    const response = NextResponse.json({});
    const pair = tokenPair();
    expect(setSession(response, pair)).toBe(response);
    expect(response.cookies.get(ACCESS_COOKIE)?.value).toBe(pair.access_token);
    expect(response.cookies.get(REFRESH_COOKIE)?.value).toBe(pair.refresh_token);
  });

  it("clears both, and returns the response", () => {
    const response = setSession(NextResponse.json({}), tokenPair());
    expect(clearSession(response)).toBe(response);
    expect(response.cookies.get(ACCESS_COOKIE)?.value).toBe("");
    expect(response.cookies.get(REFRESH_COOKIE)?.value).toBe("");
    expect(response.headers.getSetCookie().every((c) => /Max-Age=0/i.test(c))).toBe(true);
  });
});
