// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "@/app/(app)/settings/page";
import { json, routeFetch } from "../helpers";

const webhook = (overrides = {}) => ({ id: "w1", name: "Slack bridge", url: "https://hooks.example.com/x", events: "tier_crossed", tier_filter: null, status: "active", total_deliveries: 2, successful_deliveries: 2, failed_deliveries: 0, last_triggered_at: null, created_at: "2026-01-01T00:00:00Z", ...overrides });

const CONFIG = {
  hubspot_access_token_set: true, hubspot_portal_id_set: true, hubspot_webhook_secret_set: true, hubspot_batch_size: 100, hubspot_rate_limit_per_second: 10,
  anthropic_api_key_set: true, ai_model: "claude-sonnet-5-5", ai_cache_ttl_seconds: 21600, ai_rate_limit_per_minute: 10,
  scoring_hot_threshold: 75, scoring_warm_threshold: 50, scoring_cool_threshold: 25,
};

afterEach(() => vi.unstubAllGlobals());

/** The General tab is the first one shown, so every test of another tab also gets the configuration request. */
async function openTab(tab: RegExp, routes: Parameters<typeof routeFetch>[0]) {
  const mocked = routeFetch({ "/bff/system/config": [json(CONFIG)], ...routes });
  render(<SettingsPage />);
  await userEvent.setup().click(screen.getByRole("button", { name: tab }));
  return mocked;
}
const openWebhooks = (routes: Parameters<typeof routeFetch>[0]) => openTab(/webhooks/i, routes);

describe("Settings → General", () => {
  it("shows what the server reports, from the proxy", async () => {
    const { calls } = routeFetch({ "/bff/system/config": [json({ ...CONFIG, ai_model: "claude-haiku-5-5", ai_cache_ttl_seconds: 600, hubspot_batch_size: 25, hubspot_rate_limit_per_second: 4, ai_rate_limit_per_minute: 3 })] });
    render(<SettingsPage />);
    expect(await screen.findByText("Anthropic Claude (claude-haiku-5-5)")).toBeInTheDocument();
    expect(screen.getByText("10 minutes (Redis)")).toBeInTheDocument();
    expect(screen.getByText("25 contacts per API call")).toBeInTheDocument();
    expect(screen.getByText("4 req/s")).toBeInTheDocument();
    expect(screen.getByText("3 requests/min per user")).toBeInTheDocument();
    expect(calls[0].url).toBe("/bff/system/config");
  });

  it("shows the tier boundaries the server uses, not fixed ones", async () => {
    routeFetch({ "/bff/system/config": [json({ ...CONFIG, scoring_hot_threshold: 90, scoring_warm_threshold: 60, scoring_cool_threshold: 30 })] });
    render(<SettingsPage />);
    expect(await screen.findByText("≥ 90")).toBeInTheDocument();
    expect(screen.getByText("≥ 60")).toBeInTheDocument();
    expect(screen.getByText("≥ 30")).toBeInTheDocument();
    expect(screen.queryByText("≥ 75")).not.toBeInTheDocument();
  });

  it("says a secret is set, without showing it", async () => {
    routeFetch({ "/bff/system/config": [json(CONFIG)] });
    render(<SettingsPage />);
    await screen.findByText("Anthropic Claude (claude-sonnet-5-5)");
    expect(screen.getAllByText("Set")).toHaveLength(4);
    expect(screen.queryByText(/Not set/)).not.toBeInTheDocument();
  });

  it("says which secret is not set and what to configure", async () => {
    routeFetch({ "/bff/system/config": [json({ ...CONFIG, anthropic_api_key_set: false, hubspot_webhook_secret_set: false })] });
    render(<SettingsPage />);
    expect(await screen.findByText("Not set — configure ANTHROPIC_API_KEY")).toBeInTheDocument();
    expect(screen.getByText("Not set — configure HUBSPOT_WEBHOOK_SECRET")).toBeInTheDocument();
    expect(screen.getAllByText("Set")).toHaveLength(2);
  });

  it("says it is loading, then shows no stale claims if the request fails", async () => {
    routeFetch({ "/bff/system/config": [json({ detail: "The API is unreachable." }, { status: 502 })] });
    render(<SettingsPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading configuration");
    expect(await screen.findByRole("alert")).toHaveTextContent("The API is unreachable.");
    expect(screen.queryByText(/Anthropic Claude/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Configured via/)).not.toBeInTheDocument();
  });

  it("describes the fixed parts of the system as the code has them", async () => {
    routeFetch({ "/bff/system/config": [json(CONFIG)] });
    render(<SettingsPage />);
    await screen.findByText("Anthropic Claude (claude-sonnet-5-5)");
    expect(screen.getByText("Every 7 days")).toBeInTheDocument(); // the retrain schedule is 604800 seconds, with no weekday
    expect(screen.queryByText(/Sunday/)).not.toBeInTheDocument();
  });
});

describe("Settings → Webhooks", () => {
  it("lists the webhooks, fetched through the proxy", async () => {
    const { calls } = await openWebhooks({ "/bff/webhooks": [json([webhook()])] });
    expect(await screen.findByText("Slack bridge")).toBeInTheDocument();
    const list = calls.find((c) => c.url === "/bff/webhooks")!;
    expect(JSON.stringify(list.init)).not.toMatch(/authorization|bearer|localStorage/i);
  });

  it("shows why the list could not be loaded", async () => {
    await openWebhooks({ "/bff/webhooks": [json({ detail: "The API is unreachable." }, { status: 502 })] });
    expect(await screen.findByRole("alert")).toHaveTextContent("The API is unreachable.");
  });

  it("shows the signing secret of a new webhook once, and not in the list", async () => {
    const created = { ...webhook({ id: "w2", name: "New hook" }), secret: "s3cr3t-signing-value-123" };
    const { calls } = await openWebhooks({ "/bff/webhooks": [json([]), json(created, { status: 201 })] });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Add Webhook/ }));
    const inputs = screen.getAllByRole("textbox");
    await user.type(inputs[0], "New hook");
    await user.type(inputs[1], "https://hooks.example.com/new");
    await user.click(screen.getByRole("button", { name: /^(Save|Create|Add)/ }));
    expect(await screen.findByText("s3cr3t-signing-value-123")).toBeInTheDocument();
    expect(screen.getByText(/shown once/)).toBeInTheDocument();
    expect(screen.getByText("New hook")).toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/bff/webhooks").map((c) => c.init.method ?? "GET")).toEqual(["GET", "POST"]);
    await user.click(screen.getByRole("button", { name: "I have copied it" }));
    expect(screen.queryByText("s3cr3t-signing-value-123")).not.toBeInTheDocument();
    expect(screen.getByText("New hook")).toBeInTheDocument();
  });

  it("shows why a webhook could not be saved, and keeps the form", async () => {
    await openWebhooks({ "/bff/webhooks": [json([]), json({ detail: "Invalid webhook URL: the host resolves to a private, loopback, link-local or otherwise non-public address" }, { status: 422 })] });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Add Webhook/ }));
    const inputs = screen.getAllByRole("textbox");
    await user.type(inputs[0], "Bad");
    await user.type(inputs[1], "https://internal.example.com");
    await user.click(screen.getByRole("button", { name: /^(Save|Create|Add)/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("non-public address");
    expect(screen.getAllByRole("textbox")[0]).toHaveValue("Bad");
  });

  it("reports whether a test ping was delivered", async () => {
    await openWebhooks({
      "/bff/webhooks": [json([webhook()])],
      "/bff/webhooks/w1/test": [json({ status: "sent", delivered_to: 1, delivery_id: "d1", delivery_status: "success" }), json({ status: "sent", delivered_to: 0, delivery_id: "d2", delivery_status: "failed" })],
    });
    const user = userEvent.setup();
    const row = (await screen.findByText("Slack bridge")).closest("div")!.parentElement!.parentElement!;
    const test = within(row).getByRole("button", { name: /test/i });
    await user.click(test);
    expect(await screen.findByRole("status")).toHaveTextContent("Test ping delivered");
    await user.click(within(row).getByRole("button", { name: /test/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("not delivered"));
  });

  it("deletes and removes the row; if the API refuses, says so and keeps it", async () => {
    await openWebhooks({ "/bff/webhooks": [json([webhook()])], "/bff/webhooks/w1": [json({ detail: "Insufficient permissions" }, { status: 403 }), new Response(null, { status: 204 })] });
    const user = userEvent.setup();
    await screen.findByText("Slack bridge");
    const remove = () => screen.getByRole("button", { name: /delete|remove/i });
    await user.click(remove());
    expect(await screen.findByRole("alert")).toHaveTextContent("Insufficient permissions");
    expect(screen.getByText("Slack bridge")).toBeInTheDocument();
    await user.click(remove());
    await waitFor(() => expect(screen.queryByText("Slack bridge")).not.toBeInTheDocument());
  });
});

describe("Settings → Models", () => {
  const model = (overrides = {}) => ({ id: "m1", version: "2.0.1", stage: "shadow", roc_auc: 0.812, precision_hot: 0.6, training_rows: 1200, ...overrides });

  it("lists models and promotes a shadow model, refreshing the list", async () => {
    const mocked = routeFetch({ "/bff/system/config": [json(CONFIG)], "/bff/models": [json([model()]), json([model({ stage: "champion" })])], "/bff/models/m1/promote": [json({ status: "promoted" })] });
    render(<SettingsPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /models/i }));
    expect(await screen.findByText("v2.0.1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /promote/i }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /promote/i })).not.toBeInTheDocument());
    expect(mocked.calls.filter((c) => c.url.includes("/models")).map((c) => [c.url, c.init.method ?? "GET"])).toEqual([["/bff/models", "GET"], ["/bff/models/m1/promote", "POST"], ["/bff/models", "GET"]]);
  });

  it("says when promotion is refused", async () => {
    routeFetch({ "/bff/system/config": [json(CONFIG)], "/bff/models": [json([model()])], "/bff/models/m1/promote": [json({ detail: "Insufficient permissions" }, { status: 403 })] });
    render(<SettingsPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /models/i }));
    await user.click(await screen.findByRole("button", { name: /promote/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Insufficient permissions");
  });
});
