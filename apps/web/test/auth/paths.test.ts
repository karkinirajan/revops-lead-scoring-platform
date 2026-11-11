import { describe, expect, it } from "vitest";
import { isProxyablePath, isPublicPath, safeNext } from "@/lib/auth/paths";

describe("isProxyablePath", () => {
  it.each([
    ["scoring/leads"],
    ["scoring", "runs", "5ab0c4d2-1111-2222-3333-444455556666"],
    ["contacts", "abc", "intelligence"],
    ["contacts", "abc", "intelligence", "sync"],
    ["companies"],
    ["analytics", "model-accuracy"],
    ["analytics", "conversions"],
    ["webhooks", "1", "test"],
    ["models", "champion", "features"],
    ["integrations", "1", "sync-inbound"],
    ["integrations", "salesforce", "oauth", "authorize"],
    ["leads", "search"],
    ["auth", "me"],
    ["system", "config"],
  ])("lets %j through", (...segments) => {
    expect(isProxyablePath(segments.flatMap((s) => s.split("/")))).toBe(true);
  });

  it.each([
    [[]],
    [["auth", "login"]],
    [["auth", "refresh"]],
    [["auth", "users"]],
    [["auth"]],
    [["ingest"]],
    [["ingest", "batch"]],
    [["analytics", "conversions", "hubspot"]],
    [["health"]],
    [["system"]],
    [["system", "config", "extra"]],
    [["system", "secrets"]],
    [["metrics"]],
    [["admin"]],
    [["scoring2"]],
    [["scoringleads"]],
  ])("refuses %j", (segments) => {
    expect(isProxyablePath(segments)).toBe(false);
  });

  it.each([[["scoring", "..", "auth", "login"]], [["scoring", "."]], [["scoring", "a/b"]], [["scoring", "a%2Fb"]], [["scoring", "a b"]], [["scoring", "a\nb"]], [["scoring", ""]], [["scoring", "a?b=c"]], [["scoring", "a#b"]], [["scoring", "\\x"]]])(
    "refuses path tricks %j",
    (segments) => expect(isProxyablePath(segments)).toBe(false),
  );
});

describe("safeNext", () => {
  it("keeps a local path with its query and fragment", () => {
    expect(safeNext("/leads?tier=HOT&page=2")).toBe("/leads?tier=HOT&page=2");
    expect(safeNext("/dashboard")).toBe("/dashboard");
    expect(safeNext("/companies?search=a%20b#top")).toBe("/companies?search=a%20b#top");
  });

  it.each([
    undefined, null, "", "dashboard", "leads?x=1", "https://evil.test", "http://evil.test/x", "//evil.test", "///evil.test", "/\\evil.test", "javascript:alert(1)", " /dashboard",
  ])("falls back for %j", (value) => {
    expect(safeNext(value as string | null | undefined)).toBe("/dashboard");
  });

  it.each([
    ["a tab", "/\t/evil.test"],
    ["a line feed", "/\n/evil.test"],
    ["a carriage return", "/\r/evil.test"],
    ["a tab inside a plain path", "/lea\tds"],
    ["a NUL", "/\u0000/evil.test"],
    ["DEL", "/\u007f/evil.test"],
    ["a backslash inside a path", "/a\\b"],
    ["a backslash before the host", "/\\/evil.test"],
  ])("refuses %s, which a URL parser would not read as typed", (_name, value) => {
    expect(safeNext(value)).toBe("/dashboard");
  });

  it.each([
    ["/..//evil.test"],
    ["/a/..//evil.test"],
    ["/./..//evil.test"],
    ["/a/../..//evil.test"],
  ])("refuses %s, which resolves to a protocol-relative URL", (value) => {
    expect(safeNext(value)).toBe("/dashboard");
  });

  it("returns the path as the browser will resolve it, with its dot-segments gone", () => {
    expect(safeNext("/leads/../companies?x=1#h")).toBe("/companies?x=1#h");
    expect(safeNext("/a/./b")).toBe("/a/b");
  });

  it.each(["/login", "/login?next=/leads", "/login#x", "/session/login", "/session/logout", "/bff/scoring/leads", "/bff", "/a/../login", "/leads/../../session/logout"])(
    "never returns to %s",
    (value) => expect(safeNext(value)).toBe("/dashboard"),
  );

  it("allows paths that merely start with the same letters", () => {
    expect(safeNext("/loginfo")).toBe("/loginfo");
    expect(safeNext("/sessions")).toBe("/sessions");
    expect(safeNext("/bffx")).toBe("/bffx");
  });

  it("does not let an encoded slash or a percent sign change what site it is", () => {
    expect(safeNext("/%2f/evil.test")).toBe("/%2f/evil.test"); // still a path on this site: %2f is not a separator
    expect(safeNext("/%09/evil.test")).toBe("/%09/evil.test");
  });
});

describe("isPublicPath", () => {
  it.each(["/login", "/login/", "/session/login", "/session/logout", "/session", "/bff", "/bff/scoring/leads"])("%s is public", (path) => expect(isPublicPath(path)).toBe(true));
  it.each(["/", "/dashboard", "/sessions", "/login-help", "/loginfo", "/bffx", "/a/login", "/leads/bff", "/Login"])("%s is not", (path) => expect(isPublicPath(path)).toBe(false));
});
