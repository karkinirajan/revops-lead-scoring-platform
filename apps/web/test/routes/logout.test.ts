import { describe, expect, it } from "vitest";
import { POST } from "@/app/session/logout/route";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/config";

const post = (headers: Record<string, string>) => POST(new Request("https://app.example.com/session/logout", { method: "POST", headers }));

describe("POST /session/logout", () => {
  it("expires both cookies", async () => {
    const response = await post({ origin: "https://app.example.com", host: "app.example.com" });
    expect(response.status).toBe(200);
    const cookies = response.headers.getSetCookie();
    expect(cookies).toHaveLength(2);
    for (const name of [ACCESS_COOKIE, REFRESH_COOKIE]) {
      const cookie = cookies.find((c) => c.startsWith(`${name}=`))!;
      expect(cookie).toMatch(/Max-Age=0/i);
      expect(cookie).toMatch(/HttpOnly/i);
    }
  });

  it("cannot be triggered from another site", async () => {
    const response = await post({ origin: "https://evil.example", host: "app.example.com" });
    expect(response.status).toBe(403);
    expect(response.headers.getSetCookie()).toEqual([]);
  });
});
