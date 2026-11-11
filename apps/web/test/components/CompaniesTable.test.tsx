// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CompaniesTable } from "@/components/companies/CompaniesTable";
import type { Company, PaginatedResponse } from "@/lib/types";
import { json, mockFetch } from "../helpers";

const company = (n: number): Company => ({ id: `id${n}`, name: `Company ${n}`, domain: `c${n}.test`, industry: "Software", employee_count: 50 * n, size_tier: "smb", source_system: "hubspot", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" });
const page = (items: Company[]): PaginatedResponse<Company> => ({ items, total: items.length, page: 1, page_size: 50, pages: 1 });

afterEach(() => vi.unstubAllGlobals());

describe("CompaniesTable", () => {
  it("shows the companies it was given", () => {
    render(<CompaniesTable initialData={page([company(1), company(2)])} />);
    expect(screen.getByText("Company 2")).toBeInTheDocument();
    expect(screen.getByText("2 companies")).toBeInTheDocument();
  });

  it("labels the size filters and tiers readably", () => {
    render(<CompaniesTable initialData={page([company(1)])} />);
    for (const label of ["SMB", "Mid-market", "Enterprise"]) expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    expect(screen.getAllByText("SMB").length).toBeGreaterThan(1); // the filter and the row's tier
  });

  it("searches through the proxy", async () => {
    const { calls } = mockFetch(json(page([company(7)])));
    render(<CompaniesTable initialData={page([company(1)])} />);
    await userEvent.setup().type(screen.getByPlaceholderText("Search companies…"), "a");
    expect(await screen.findByText("Company 7")).toBeInTheDocument();
    expect(calls[0].url).toBe("/bff/companies?page=1&page_size=50&search=a");
  });

  it("only the newest search may change the table, whatever order the answers come in", async () => {
    const resolvers: Array<(r: Response) => void> = [];
    mockFetch(() => new Promise<Response>((resolve) => resolvers.push(resolve)));
    render(<CompaniesTable initialData={page([company(1)])} />);
    await userEvent.setup().type(screen.getByPlaceholderText("Search companies…"), "ab"); // two requests, one per keystroke
    expect(resolvers).toHaveLength(2);
    resolvers[1](json(page([company(22)]))); // the newest answers first
    expect(await screen.findByText("Company 22")).toBeInTheDocument();
    resolvers[0](json(page([company(11)]))); // the stale one arrives late
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("Company 11")).not.toBeInTheDocument();
    expect(screen.getByText("Company 22")).toBeInTheDocument();
  });

  it("keeps the rows and shows the reason when loading fails", async () => {
    mockFetch(json({ detail: "Too many requests" }, { status: 429 }));
    render(<CompaniesTable initialData={page([company(1)])} />);
    await userEvent.setup().type(screen.getByPlaceholderText("Search companies…"), "x");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Too many requests"));
    expect(screen.getByText("Company 1")).toBeInTheDocument();
  });
});
