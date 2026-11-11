import { afterEach, describe, expect, it, vi } from "vitest";
import { clearedCookies, sessionCookies } from "@/lib/auth/cookies";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/config";

const pair = { access_token: "access-jwt", refresh_token: "refresh-jwt", expires_in: 1800 };

afterEach(() => vi.unstubAllEnvs());

describe("sessionCookies", () => {
  it("makes an access cookie that lives as long as the token and a refresh cookie that lives seven days", () => {
    const [access, refresh] = sessionCookies(pair);
    expect(access).toMatchObject({ name: ACCESS_COOKIE, value: "access-jwt", maxAge: 1800 });
    expect(refresh).toMatchObject({ name: REFRESH_COOKIE, value: "refresh-jwt", maxAge: 7 * 24 * 3600 });
  });

  it("is httpOnly, SameSite=Lax and site-wide for both", () => {
    for (const cookie of sessionCookies(pair)) expect(cookie).toMatchObject({ httpOnly: true, sameSite: "lax", path: "/" });
  });

  it("is Secure in production", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(sessionCookies(pair).every((c) => c.secure)).toBe(true);
  });

  it("is not Secure in development, where http://localhost is normal", () => {
    vi.stubEnv("NODE_ENV", "development");
    expect(sessionCookies(pair).some((c) => c.secure)).toBe(false);
  });

  it("can be told the deployment serves plain http", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("COOKIE_SECURE", "false");
    expect(sessionCookies(pair).some((c) => c.secure)).toBe(false);
  });

  it("only COOKIE_SECURE=false turns Secure off", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("COOKIE_SECURE", "0");
    expect(sessionCookies(pair).every((c) => c.secure)).toBe(true);
  });
});

describe("clearedCookies", () => {
  it("expires both cookies immediately and carries no token", () => {
    const cleared = clearedCookies();
    expect(cleared.map((c) => c.name)).toEqual([ACCESS_COOKIE, REFRESH_COOKIE]);
    for (const cookie of cleared) expect(cookie).toMatchObject({ value: "", maxAge: 0, httpOnly: true, path: "/" });
  });
});
