// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TriggerRunButton } from "@/components/dashboard/TriggerRunButton";
import { json, mockFetch } from "../helpers";

afterEach(() => vi.unstubAllGlobals());

describe("TriggerRunButton", () => {
  it("queues a scoring run and says which one", async () => {
    const { calls } = mockFetch(json({ id: "5ab0c4d2-9999-0000-1111-222233334444" }, { status: 202 }));
    render(<TriggerRunButton />);
    await userEvent.setup().click(screen.getByRole("button", { name: /Run Scoring/ }));
    expect(await screen.findByText("Run 5ab0c4d2 queued")).toBeInTheDocument();
    expect([calls[0].url, calls[0].init.method]).toEqual(["/bff/scoring/runs", "POST"]);
  });

  it("shows the API's reason when it is refused", async () => {
    mockFetch(json({ detail: "Insufficient permissions" }, { status: 403 }));
    render(<TriggerRunButton />);
    await userEvent.setup().click(screen.getByRole("button", { name: /Run Scoring/ }));
    expect(await screen.findByText("Insufficient permissions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run Scoring/ })).toBeEnabled();
  });

  it("cannot be clicked twice while it is working", async () => {
    let finish!: (r: Response) => void;
    const { fake } = mockFetch(() => new Promise<Response>((resolve) => (finish = resolve)));
    render(<TriggerRunButton />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Run Scoring/ }));
    expect(screen.getByRole("button", { name: /Triggering/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Triggering/ }));
    expect(fake).toHaveBeenCalledTimes(1);
    finish(json({ id: "abcdef12-0" }));
    expect(await screen.findByText(/queued/)).toBeInTheDocument();
  });
});
