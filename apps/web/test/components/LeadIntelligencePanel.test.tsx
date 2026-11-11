// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LeadIntelligencePanel } from "@/components/leads/LeadIntelligencePanel";
import { json, mockFetch } from "../helpers";

const assign = vi.fn();
beforeEach(() => {
  assign.mockClear();
  Object.defineProperty(window, "location", { configurable: true, value: { pathname: "/leads", search: "", assign } });
});
afterEach(() => vi.unstubAllGlobals());

function sse(...events: string[]) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({ start(controller) { for (const e of events) controller.enqueue(encoder.encode(e)); controller.close(); } }), { headers: { "Content-Type": "text/event-stream" } });
}

const open = async () => userEvent.setup().click(screen.getByRole("button", { name: /AI Intel/ }));

describe("LeadIntelligencePanel", () => {
  it("asks for the report through the proxy with the session cookie", async () => {
    const { calls } = mockFetch(sse("data: [DONE]\n\n"));
    render(<LeadIntelligencePanel contactId="abc-123" contactName="Ada" />);
    await open();
    expect(calls[0].url).toBe("/bff/contacts/abc-123/intelligence");
    expect(calls[0].init.credentials).toBe("same-origin");
    expect(JSON.stringify(calls[0].init)).not.toMatch(/authorization|bearer/i);
  });

  it("builds the report from the streamed chunks, newlines included", async () => {
    mockFetch(sse('data: {"chunk": "Why this lead is HOT\\n"}\n\n', 'data: {"chunk": "Demo requested."}\n\n', "data: [DONE]\n\n"));
    render(<LeadIntelligencePanel contactId="c1" contactName="Ada" />);
    await open();
    const report = await screen.findByText(/Why this lead is HOT/);
    expect(report.textContent).toBe("Why this lead is HOT\nDemo requested.");
    expect(screen.getByText(/AI Intelligence — Ada/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Regenerate" })).toBeInTheDocument();
  });

  it("copes with an event split across reads", async () => {
    mockFetch(sse('data: {"chu', 'nk": "Hel', 'lo"}\n', "\ndata: [DONE]\n\n"));
    render(<LeadIntelligencePanel contactId="c1" contactName="Ada" />);
    await open();
    expect(await screen.findByText("Hello")).toBeInTheDocument();
  });

  it("shows an error sent in the stream and stops there", async () => {
    mockFetch(sse('data: {"chunk": "partial"}\n\n', 'data: {"error": "The AI service could not complete this request. Try again later."}\n\n', 'data: {"chunk": "never shown"}\n\n'));
    render(<LeadIntelligencePanel contactId="c1" contactName="Ada" />);
    await open();
    expect(await screen.findByText(/could not complete this request/)).toBeInTheDocument();
    expect(screen.queryByText(/never shown/)).not.toBeInTheDocument();
  });

  it("shows why the API refused", async () => {
    mockFetch(json({ detail: "AI intelligence not configured. Set ANTHROPIC_API_KEY environment variable." }, { status: 503 }));
    render(<LeadIntelligencePanel contactId="c1" contactName="Ada" />);
    await open();
    expect(await screen.findByText(/ANTHROPIC_API_KEY/)).toBeInTheDocument();
  });

  it("sends an expired session to sign in", async () => {
    mockFetch(json({ detail: "Sign in to continue." }, { status: 401 }));
    render(<LeadIntelligencePanel contactId="c1" contactName="Ada" />);
    await open();
    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith("/login?next=%2Fleads"));
  });

  it("reports a connection failure", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    render(<LeadIntelligencePanel contactId="c1" contactName="Ada" />);
    await open();
    expect(await screen.findByText("Failed to connect to AI service")).toBeInTheDocument();
  });

  it("encodes the contact id in the path", async () => {
    const { calls } = mockFetch(sse("data: [DONE]\n\n"));
    render(<LeadIntelligencePanel contactId="a/b?c" contactName="Ada" />);
    await open();
    expect(calls[0].url).toBe("/bff/contacts/a%2Fb%3Fc/intelligence");
  });

  it("closes", async () => {
    mockFetch(sse("data: [DONE]\n\n"));
    render(<LeadIntelligencePanel contactId="c1" contactName="Ada" />);
    await open();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Close AI intelligence" }));
    expect(screen.getByRole("button", { name: /AI Intel/ })).toBeInTheDocument();
  });
});
