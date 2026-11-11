// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SimulateForm } from "@/components/simulate/SimulateForm";
import { json, mockFetch } from "../helpers";

afterEach(() => vi.unstubAllGlobals());

describe("SimulateForm", () => {
  it("names every control by its label", () => {
    render(<SimulateForm />);
    for (const name of ["Pricing page visited", "Demo requested", "Free trial active", "Integration connected"]) {
      expect(screen.getByRole("switch", { name })).toBeInTheDocument();
    }
    for (const control of screen.getAllByRole("spinbutton")) expect(control).toHaveAccessibleName();
  });

  it("toggles report their state, by click and by clicking the label text", async () => {
    render(<SimulateForm />);
    const user = userEvent.setup();
    const demo = screen.getByRole("switch", { name: "Demo requested" });
    expect(demo).toHaveAttribute("aria-checked", "false");
    await user.click(demo);
    expect(demo).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByText("Demo requested"));
    expect(demo).toHaveAttribute("aria-checked", "false");
  });

  it("sends the form to the proxy and shows the score", async () => {
    const { calls } = mockFetch(json({ lead_score: 64, priority_tier: "WARM", recommended_action: "nurture_sequence", score_reason: "Trial active", feature_contributions: { demo_requested: 20, _base: 0 }, model_version: "1.0.0" }));
    render(<SimulateForm />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("switch", { name: "Free trial active" }));
    await user.click(screen.getByRole("button", { name: /Simulate Score/ }));
    expect(await screen.findByText("model v1.0.0")).toBeInTheDocument();
    expect(screen.getAllByText("64").length).toBeGreaterThan(0);
    expect(screen.getByText("Trial active")).toBeInTheDocument();
    expect(screen.getByText("WARM")).toBeInTheDocument();
    expect(calls[0].url).toBe("/bff/scoring/simulate");
    expect(JSON.parse(calls[0].init.body as string)).toMatchObject({ free_trial_active: true, demo_requested: false });
  });

  it("shows why a simulation failed", async () => {
    mockFetch(json({ detail: "Insufficient permissions" }, { status: 403 }));
    render(<SimulateForm />);
    await userEvent.setup().click(screen.getByRole("button", { name: /Simulate Score/ }));
    expect(await screen.findByText("Insufficient permissions")).toBeInTheDocument();
  });
});
