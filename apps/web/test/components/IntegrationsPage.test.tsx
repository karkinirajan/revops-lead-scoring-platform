// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import IntegrationsPage from "@/app/(app)/integrations/page";
import { json, mockFetch } from "../helpers";

const connection = (overrides = {}) => ({ id: "conn-1", crm_type: "salesforce", name: "Acme SF", org_id: "00D1", instance_url: "https://acme.my.salesforce.com", is_active: true, sync_direction: "bidirectional", last_inbound_sync_at: null, last_outbound_sync_at: null, last_sync_error: null, total_records_synced: 0, created_at: "2026-01-01T00:00:00Z", ...overrides });

afterEach(() => vi.unstubAllGlobals());

describe("IntegrationsPage", () => {
  it("lists connections through the proxy", async () => {
    const { calls } = mockFetch(json([connection()]));
    render(<IntegrationsPage />);
    expect(await screen.findByText("Acme SF")).toBeInTheDocument();
    expect(calls[0].url).toBe("/bff/integrations");
  });

  it("shows why the list could not be loaded", async () => {
    mockFetch(json({ detail: "Insufficient permissions" }, { status: 403 }));
    render(<IntegrationsPage />);
    expect(await screen.findByText("Insufficient permissions")).toBeInTheDocument();
  });

  it("starts an inbound sync and reports what it did", async () => {
    const { calls } = mockFetch(json([connection()]), json({ direction: "inbound", records_processed: 9, success: 7, failure: 0, duration_seconds: 1.2, synced_at: "2026-01-01T00:00:00Z" }));
    render(<IntegrationsPage />);
    await userEvent.setup().click(await screen.findByRole("button", { name: /inbound|pull/i }));
    expect(calls[1].url).toBe("/bff/integrations/conn-1/sync-inbound");
    expect(calls[1].init.method).toBe("POST");
    expect(await screen.findByText(/7/)).toBeInTheDocument();
  });

  it("shows the reason when a sync fails", async () => {
    mockFetch(json([connection()]), json({ detail: "This connection's instance_url is not usable" }, { status: 409 }));
    render(<IntegrationsPage />);
    await userEvent.setup().click(await screen.findByRole("button", { name: /outbound|push/i }));
    expect(await screen.findByText(/instance_url is not usable/)).toBeInTheDocument();
  });
});
