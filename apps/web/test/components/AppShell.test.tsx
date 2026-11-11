// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/layout/AppShell";
import { json, mockFetch } from "../helpers";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, refresh: vi.fn() }), usePathname: () => "/leads/123" }));

// a followed link would make jsdom try to load a new document; React has handled the click by the time it reaches here
const keepOnPage = (event: Event) => {
  if ((event.target as HTMLElement).closest("a")) event.preventDefault();
};
beforeEach(() => document.addEventListener("click", keepOnPage));
afterEach(() => {
  document.removeEventListener("click", keepOnPage);
  vi.unstubAllGlobals();
  replace.mockClear();
});

const shell = () => render(<AppShell user={{ email: "ada@example.com", role: "admin" }}><p>page content</p></AppShell>);
const navigation = () => document.getElementById("app-navigation")!;
// jsdom loads no stylesheet, so "hidden" here is the Tailwind class that display:nones the menu on small screens; the browser run confirms what that looks like
const menuIsHidden = () => navigation().classList.contains("hidden");

describe("AppShell", () => {
  it("shows the page and the navigation links", () => {
    shell();
    expect(screen.getByText("page content")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Leads" })).toBeInTheDocument();
  });

  it("starts with the small-screen menu closed", () => {
    shell();
    const button = screen.getByRole("button", { name: "Open navigation" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-controls", "app-navigation");
    expect(menuIsHidden()).toBe(true);
  });

  it("opens and closes with the menu button, keeping its label and state in step", async () => {
    shell();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(menuIsHidden()).toBe(false);
    const close = screen.getByRole("button", { name: "Close navigation" });
    expect(close).toHaveAttribute("aria-expanded", "true");
    await user.click(close);
    expect(menuIsHidden()).toBe(true);
    expect(screen.getByRole("button", { name: "Open navigation" })).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on Escape", async () => {
    shell();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    await user.keyboard("{Escape}");
    expect(menuIsHidden()).toBe(true);
  });

  it("ignores other keys", async () => {
    shell();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    await user.keyboard("a{ArrowDown}{Tab}"); // Enter would activate the focused menu button, which is the point of it
    expect(menuIsHidden()).toBe(false);
  });

  it("closes when the backdrop is clicked", async () => {
    const { container } = shell();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    await user.click(container.querySelector("[aria-hidden='true'].fixed")!);
    expect(menuIsHidden()).toBe(true);
  });

  it("closes when a link is followed", async () => {
    shell();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    await user.click(screen.getByRole("link", { name: "Companies" }));
    expect(menuIsHidden()).toBe(true);
  });

  it("marks the current page, including a page below it", () => {
    shell();
    expect(screen.getByRole("link", { name: "Leads" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("closes the menu when signing out", async () => {
    mockFetch(json({ ok: true }));
    shell();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(menuIsHidden()).toBe(true);
  });

  it("stops listening for Escape once closed", async () => {
    const remove = vi.spyOn(document, "removeEventListener");
    shell();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    await user.keyboard("{Escape}");
    expect(remove).toHaveBeenCalledWith("keydown", expect.any(Function));
    remove.mockRestore();
  });
});
