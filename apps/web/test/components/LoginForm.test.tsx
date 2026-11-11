// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginForm } from "@/app/login/LoginForm";
import { json, mockFetch } from "../helpers";

const replace = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, refresh }) }));

beforeEach(() => {
  replace.mockClear();
  refresh.mockClear();
});
afterEach(() => vi.unstubAllGlobals());

async function fill(email = "ada@example.com", password = "correct-horse-battery") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginForm", () => {
  it("has labelled email and password fields", () => {
    render(<LoginForm next="/dashboard" />);
    expect(screen.getByLabelText("Email")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("posts the credentials to the session route and goes where the user was headed", async () => {
    const { calls } = mockFetch(json({ ok: true }));
    render(<LoginForm next="/leads?tier=HOT" />);
    await fill();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/leads?tier=HOT"));
    expect(refresh).toHaveBeenCalled();
    expect(calls[0].url).toBe("/session/login");
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].init.credentials).toBe("same-origin");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ email: "ada@example.com", password: "correct-horse-battery" });
  });

  it.each([["", ""], ["ada@example.com", ""], ["", "secret"]])("does not call the server for email %j and password %j", async (email, password) => {
    const { fake } = mockFetch(json({ ok: true }));
    render(<LoginForm next="/dashboard" />);
    const user = userEvent.setup();
    if (email) await user.type(screen.getByLabelText("Email"), email);
    if (password) await user.type(screen.getByLabelText("Password"), password);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter your email and password.");
    expect(fake).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("shows why sign-in failed and stays on the page", async () => {
    mockFetch(json({ detail: "Invalid email or password." }, { status: 401 }));
    render(<LoginForm next="/dashboard" />);
    await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("explains a network failure", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    render(<LoginForm next="/dashboard" />);
    await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
  });

  it("has a message when the error body is unreadable", async () => {
    mockFetch(new Response("<html>", { status: 500 }));
    render(<LoginForm next="/dashboard" />);
    await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not sign in.");
  });

  it("disables the button while signing in", async () => {
    let finish!: (r: Response) => void;
    mockFetch(() => new Promise<Response>((resolve) => (finish = resolve)));
    render(<LoginForm next="/dashboard" />);
    await fill();
    expect(await screen.findByRole("button", { name: "Signing in…" })).toBeDisabled();
    finish(json({ ok: true }));
    await waitFor(() => expect(replace).toHaveBeenCalled());
  });

  it("clears the previous error on the next attempt", async () => {
    mockFetch(json({ detail: "Invalid email or password." }, { status: 401 }), json({ ok: true }));
    render(<LoginForm next="/dashboard" />);
    await fill();
    await screen.findByRole("alert");
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
