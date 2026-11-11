// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "@/components/layout/Sidebar";
import { json, mockFetch } from "../helpers";

const replace = vi.fn();
const refresh = vi.fn();
let pathname = "/leads";
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, refresh }), usePathname: () => pathname }));

afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockClear();
  refresh.mockClear();
  pathname = "/leads";
});

describe("Sidebar", () => {
  it("links to every page", () => {
    render(<Sidebar user={{ email: "ada@example.com", role: "analyst" }} />);
    for (const name of ["Dashboard", "Leads", "Companies", "Analytics", "Integrations", "Run History", "Simulate", "Settings"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Leads" })).toHaveAttribute("href", "/leads");
  });

  it("shows who is signed in and their role", () => {
    render(<Sidebar user={{ email: "ada@example.com", role: "analyst" }} />);
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText("analyst")).toBeInTheDocument();
  });

  it("signs out: clears the session, then goes to the sign-in page", async () => {
    const { calls } = mockFetch(json({ ok: true }));
    render(<Sidebar user={{ email: "ada@example.com", role: "viewer" }} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(calls[0].url).toBe("/session/logout");
    expect(calls[0].init.method).toBe("POST");
    expect(refresh).toHaveBeenCalled();
  });
});
