import { describe, expect, it, vi } from "vitest";
import { goToLogin, loginUrl } from "@/lib/navigation";

describe("loginUrl", () => {
  it("returns to the given page, encoded", () => {
    expect(loginUrl("/leads?tier=HOT&page=2")).toBe("/login?next=%2Fleads%3Ftier%3DHOT%26page%3D2");
  });
});

describe("goToLogin", () => {
  it("leaves for the sign-in page with a full navigation from the current page", () => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { pathname: "/runs", search: "?limit=5", assign } });
    goToLogin();
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fruns%3Flimit%3D5");
    vi.unstubAllGlobals();
  });
});
