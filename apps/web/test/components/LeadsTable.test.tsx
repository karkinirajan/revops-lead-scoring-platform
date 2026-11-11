// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LeadsTable } from "@/components/leads/LeadsTable";
import type { PaginatedResponse, RankedLead } from "@/lib/types";
import { json, mockFetch } from "../helpers";

function lead(n: number, overrides: Partial<RankedLead> = {}): RankedLead {
  return {
    contact_id: `c${n}`, email: `lead${n}@example.com`, full_name: `Lead ${n}`, job_title: "CTO", company_id: null, company_name: `Company ${n}`, company_size_tier: "mid_market",
    lead_score: 90 - n, priority_tier: "HOT", score_reason: null, recommended_action: "call_today", model_version: "1.0.0", scored_at: "2026-01-01T00:00:00Z", synced_to_hubspot_at: null, ...overrides,
  };
}
const page = (items: RankedLead[], extra: Partial<PaginatedResponse<RankedLead>> = {}): PaginatedResponse<RankedLead> => ({ items, total: items.length, page: 1, page_size: 50, pages: 1, ...extra });

afterEach(() => vi.unstubAllGlobals());

describe("LeadsTable", () => {
  it("shows the leads it was given", () => {
    render(<LeadsTable initialData={page([lead(1), lead(2)])} />);
    expect(screen.getByText("Lead 1")).toBeInTheDocument();
    expect(screen.getByText("lead2@example.com")).toBeInTheDocument();
    expect(screen.getByText("2 results")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /AI Intel/ })).toHaveLength(2);
  });

  it("says when nothing matches", () => {
    render(<LeadsTable initialData={page([])} />);
    expect(screen.getByText("No leads match the current filters.")).toBeInTheDocument();
  });

  it("shows the filters the list was fetched with as selected", () => {
    render(<LeadsTable initialData={page([lead(1)], { pages: 5, page: 3 })} initialFilters={{ tier: "HOT", minScore: "40", page: 3 }} />);
    expect(screen.getByRole("button", { name: "HOT" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "WARM" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByPlaceholderText("0")).toHaveValue(40);
    expect(screen.getByText("Page 3 of 5")).toBeInTheDocument();
  });

  it("carries those filters into the next request, so paging keeps them", async () => {
    const { calls } = mockFetch(json(page([lead(2)], { page: 4, pages: 5 })));
    render(<LeadsTable initialData={page([lead(1)], { pages: 5, page: 3 })} initialFilters={{ tier: "HOT", minScore: "40", page: 3 }} />);
    await userEvent.setup().click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(calls[0].url).toBe("/bff/scoring/leads?page=4&page_size=50&priority_tier=HOT&min_score=40"));
  });

  it("clicking the selected tier clears it", async () => {
    const { calls } = mockFetch(json(page([lead(1)])));
    render(<LeadsTable initialData={page([lead(1)])} initialFilters={{ tier: "HOT", minScore: "", page: 1 }} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "HOT" }));
    await waitFor(() => expect(calls[0].url).toBe("/bff/scoring/leads?page=1&page_size=50"));
    expect(screen.getByRole("button", { name: "HOT" })).toHaveAttribute("aria-pressed", "false");
  });

  it("filters by tier through the proxy and toggles the filter off again", async () => {
    const { calls } = mockFetch(json(page([lead(3, { priority_tier: "WARM" })])));
    render(<LeadsTable initialData={page([lead(1)])} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "WARM" }));
    expect(await screen.findByText("Lead 3")).toBeInTheDocument();
    expect(calls[0].url).toBe("/bff/scoring/leads?page=1&page_size=50&priority_tier=WARM");
    await user.click(screen.getByRole("button", { name: "WARM" }));
    await waitFor(() => expect(calls[1].url).toBe("/bff/scoring/leads?page=1&page_size=50"));
  });

  it("filters by minimum score", async () => {
    const { calls } = mockFetch(json(page([])));
    render(<LeadsTable initialData={page([lead(1)])} />);
    await userEvent.setup().type(screen.getByPlaceholderText("0"), "7");
    await waitFor(() => expect(calls.at(-1)!.url).toBe("/bff/scoring/leads?page=1&page_size=50&min_score=7"));
  });

  it("pages", async () => {
    const { calls } = mockFetch(json(page([lead(60)], { page: 2, pages: 2 })));
    render(<LeadsTable initialData={page([lead(1)], { pages: 2 })} />);
    expect(screen.getByRole("button", { name: /Prev/ })).toBeDisabled();
    await userEvent.setup().click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText("Lead 60")).toBeInTheDocument();
    expect(calls[0].url).toBe("/bff/scoring/leads?page=2&page_size=50");
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
  });

  it("keeps the rows and shows the reason when loading fails", async () => {
    mockFetch(json({ detail: "The API is unreachable." }, { status: 502 }));
    render(<LeadsTable initialData={page([lead(1)])} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "HOT" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The API is unreachable.");
    expect(screen.getByText("Lead 1")).toBeInTheDocument();
  });

  it("ignores an answer that arrives after a newer request was made", async () => {
    let slow!: (r: Response) => void;
    mockFetch(
      () => new Promise<Response>((resolve) => (slow = resolve)),
      json(page([lead(2, { priority_tier: "COOL" })])),
    );
    render(<LeadsTable initialData={page([lead(1)])} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "HOT" })); // slow
    await user.click(screen.getByRole("button", { name: "COOL" })); // fast, newer
    expect(await screen.findByText("Lead 2")).toBeInTheDocument();
    slow(json(page([lead(9)])));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("Lead 9")).not.toBeInTheDocument();
    expect(screen.getByText("Lead 2")).toBeInTheDocument();
  });

  it("exports a CSV that keeps its columns and does not run formulas", async () => {
    let csv = "";
    vi.stubGlobal("URL", { createObjectURL: (blob: Blob) => { blob.text().then((t) => (csv = t)); return "blob:x"; }, revokeObjectURL: () => {} });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<LeadsTable initialData={page([lead(1, { full_name: "=HYPERLINK(\"http://evil\")", company_name: "Acme, Inc." })])} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Export CSV" }));
    await waitFor(() => expect(csv).not.toBe(""));
    const [header, row] = csv.split("\r\n");
    expect(header).toBe("Email,Name,Company,Score,Tier,Action,Scored At");
    expect(row).toContain(`"'=HYPERLINK(""http://evil"")"`);
    expect(row).toContain('"Acme, Inc."');
    expect(click).toHaveBeenCalled();
    click.mockRestore();
  });

  it("marks leads synced to HubSpot", () => {
    render(<LeadsTable initialData={page([lead(1, { synced_to_hubspot_at: "2026-01-02T00:00:00Z" })])} />);
    expect(within(screen.getAllByRole("row")[1]).getByText("synced")).toBeInTheDocument();
  });
});
