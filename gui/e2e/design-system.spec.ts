import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page, type Route } from "@playwright/test";

const evidenceDir = resolve(process.cwd(), "../.itx/1075/evidence/browser");
const recordEvidence = process.env.E2E_RECORD_EVIDENCE === "1";

const fleet = {
  agents: [
    {
      agent_key: "lab:alpha",
      agent_name: "Alpha",
      agent_type: "openclaw",
      host: "lab.example",
      host_alias: "Lab host",
      host_os_family: "linux",
      status: "running",
      model: "gpt-4.1",
      uptime: "2h 14m",
      gateway_url: "http://127.0.0.1:41001",
      provider: "openai-main",
      provider_type: "openai",
    },
    {
      agent_key: "studio:beta",
      agent_name: "Beta",
      agent_type: "hermes",
      host: "studio.example",
      host_alias: "Studio Mac",
      host_os_family: "darwin",
      status: "stopped",
      model: "claude-sonnet-4-6",
      uptime: "—",
      gateway_url: null,
      provider: "anthropic-main",
      provider_type: "anthropic",
    },
  ],
  summary: { total: 2, running: 1, provisioning: 0, hosts: 2 },
};

const topology = {
  control: { label: "Control", description: "clawctl CLI" },
  summary: { total_agents: 2, running: 1, total_hosts: 2 },
  connections: [],
  hosts: [
    {
      hostname: "lab.example",
      alias: "Lab host",
      user: "xclm",
      addresses: ["192.0.2.10"],
      has_key: true,
      agent_count: 1,
      agents: [{
        ...fleet.agents[0],
        version: "1.0.0",
        provider_endpoint: "https://api.openai.com/v1",
        provider_accelerator_vendor: null,
      }],
    },
    {
      hostname: "studio.example",
      alias: "Studio Mac",
      user: "xclm",
      addresses: ["192.0.2.11"],
      has_key: true,
      agent_count: 1,
      agents: [{
        ...fleet.agents[1],
        version: "1.0.0",
        provider_endpoint: "https://api.anthropic.com",
        provider_accelerator_vendor: null,
      }],
    },
  ],
};

const providers = [
  {
    name: "openai-main",
    type: "openai",
    endpoint: "https://api.openai.com/v1",
    default_model: "gpt-4.1",
    available_models: ["gpt-4.1", "gpt-4.1-mini"],
    has_api_key: true,
    accelerator_vendor: null,
    created_at: "2026-05-01T12:00:00Z",
    updated_at: "2026-05-01T12:00:00Z",
  },
  {
    name: "anthropic-main",
    type: "anthropic",
    endpoint: "https://api.anthropic.com",
    default_model: "claude-sonnet-4-6",
    available_models: ["claude-sonnet-4-6"],
    has_api_key: true,
    accelerator_vendor: null,
    created_at: "2026-05-02T12:00:00Z",
    updated_at: "2026-05-02T12:00:00Z",
  },
];

const integrations = [
  {
    name: "github-main",
    type: "github",
    credential_keys: ["GITHUB_TOKEN"],
    configured_credential_keys: ["GITHUB_TOKEN"],
    agent_count: 2,
    created_at: "2026-05-03T12:00:00Z",
    updated_at: "2026-05-03T12:00:00Z",
  },
  {
    name: "linear-team",
    type: "linear",
    credential_keys: ["LINEAR_API_KEY"],
    configured_credential_keys: [],
    agent_count: 0,
    created_at: "2026-05-04T12:00:00Z",
    updated_at: "2026-05-04T12:00:00Z",
  },
];

const providerTypes = {
  openai: {
    endpoint: "https://api.openai.com/v1",
    models: [{ id: "gpt-4.1", name: "GPT-4.1", lab: "OpenAI", context_window: 128000, tags: [] }],
    requires_api_key: true,
    requires_endpoint: false,
  },
  anthropic: {
    endpoint: "https://api.anthropic.com",
    models: [{ id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6", lab: "Anthropic", context_window: 200000, tags: [] }],
    requires_api_key: true,
    requires_endpoint: false,
  },
};

const integrationTypes = {
  github: {
    description: "GitHub repositories and issues",
    credentials: [{ key: "GITHUB_TOKEN", description: "Personal access token", required: true }],
  },
  linear: {
    description: "Linear issues",
    credentials: [{ key: "LINEAR_API_KEY", description: "Linear API key", required: true }],
  },
};

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function installApiFixtures(page: Page) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path === "/api/settings/version") return fulfillJson(route, { version: "26.8.1" });
    if (path === "/api/fleet") return fulfillJson(route, fleet);
    if (path === "/api/fleet/topology") return fulfillJson(route, topology);
    if (path === "/api/fleet/health") {
      return fulfillJson(route, {
        summary: fleet.summary,
        agents: fleet.agents.map((agent) => ({
          agent_key: agent.agent_key,
          status: agent.status,
          process_running: agent.status === "running",
          health_error: null,
          cpu_count: 8,
          memory_total_mb: 16384,
          missing_secrets: [],
        })),
      });
    }
    if (path === "/api/providers") return fulfillJson(route, { providers });
    if (path === "/api/providers/types") return fulfillJson(route, { types: providerTypes });
    if (path === "/api/providers/catalog") return fulfillJson(route, { models: [] });
    if (path === "/api/integrations") return fulfillJson(route, { integrations });
    if (path === "/api/integrations/types") return fulfillJson(route, { types: integrationTypes });
    if (path.startsWith("/api/integrations/")) {
      const name = decodeURIComponent(path.split("/").at(-1) ?? "");
      const integration = integrations.find((item) => item.name === name) ?? integrations[0];
      return fulfillJson(route, { ...integration, agents_using: [] });
    }
    if (path === "/api/usage/summary") {
      return fulfillJson(route, {
        period_days: 1,
        total_events: 17,
        total_prompt_tokens: 4200,
        total_completion_tokens: 1300,
        total_tokens: 5500,
        total_cost: 0.42,
      });
    }
    if (path.startsWith("/api/fleet/agents/") && path.endsWith("/health")) {
      return fulfillJson(route, {
        agent_key: "lab:alpha",
        status: "running",
        process_running: true,
        health_error: null,
        cpu_count: 8,
        memory_total_mb: 16384,
        missing_secrets: [],
        onboarding_step: "complete",
        latest_supported_version: "1.0.0",
      });
    }
    if (path.startsWith("/api/fleet/agents/") && path.endsWith("/web-ui")) {
      return fulfillJson(route, {
        available: false,
        local_url: null,
        reason: "Test fixture does not expose a native UI",
      });
    }
    if (path.startsWith("/api/fleet/agents/")) {
      return fulfillJson(route, {
        ...fleet.agents[0],
        version: "1.0.0",
        device_id: "fixture-device",
        onboarding_step: "complete",
        gateway_port: 41001,
      });
    }

    return fulfillJson(route, {});
  });
}

async function assertNoDocumentOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
}

async function evidence(page: Page, name: string, fullPage = false) {
  if (!recordEvidence) return;
  mkdirSync(evidenceDir, { recursive: true });
  await page.screenshot({ path: resolve(evidenceDir, name), fullPage, animations: "disabled" });
}

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test("every primary sidebar route resolves with its heading and active item", async ({ page }) => {
  const routes = [
    ["/", "Dashboard"],
    ["/agents", "Agents"],
    ["/hosts", "Hosts"],
    ["/providers", "Providers"],
    ["/integrations", "Integrations"],
    ["/mcp-servers", "MCP servers"],
  ] as const;

  for (const [path, heading] of routes) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await expect(page.getByRole("link", { name: heading, exact: true })).toHaveAttribute("aria-current", "page");
    await assertNoDocumentOverflow(page);
  }
});

test("desktop shell collapse keeps icon navigation accessible", async ({ page }) => {
  await page.goto("/agents");
  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toHaveAttribute("href", "#main-content");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  await evidence(page, "desktop-shell-expanded.png");

  const toggle = page.getByRole("button", { name: "Collapse sidebar" });
  await toggle.click();
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Agents", exact: true })).toBeVisible();
  await expect(page.locator(".ds-app-sidebar-card-text").first()).toBeHidden();

  await page.getByRole("link", { name: "Dashboard", exact: true }).focus();
  await expect(page.getByRole("link", { name: "Dashboard", exact: true })).toBeFocused();
  await assertNoDocumentOverflow(page);
  await evidence(page, "desktop-shell-collapsed.png");
});

test("MCP preview is explicit follow-up scope without CRUD or a modal", async ({ page }) => {
  await page.goto("/mcp-servers");
  await expect(page.getByText(/scoped for a follow-up milestone/i)).toBeVisible();
  await expect(page.getByText(/No create, edit, or delete actions/i)).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /create|add|edit|delete/i })).toHaveCount(0);
  await evidence(page, "desktop-mcp-placeholder.png");

  await page.goto("/hosts");
  await expect(page.getByText(/planned for a later delivery step/i)).toBeVisible();
  await evidence(page, "desktop-hosts-placeholder.png");
});

test("Agents DataTable renders fixtures and exposes keyboard-operable agent links", async ({ page }) => {
  await page.goto("/agents");
  const table = page.locator('[data-i7n-name="dashboard.agents.table-card"]');
  await expect(table).toContainText("2 agents");
  await expect(table.getByRole("row", { name: /Alpha/ })).toBeVisible();
  await expect(table.getByRole("row", { name: /Beta/ })).toBeVisible();

  const alphaRow = table.getByRole("row", { name: /Alpha/ });
  await expect(alphaRow).not.toHaveAttribute("tabindex");
  const alphaLink = alphaRow.getByRole("link", { name: "Open agent Alpha" });
  await alphaLink.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/agents\?key=lab(?::|%3A)alpha$/);
  await expect(page.getByRole("heading", { level: 1, name: "Alpha" })).toBeVisible();
  const overviewTab = page.getByRole("tab", { name: "Overview" });
  await expect(overviewTab).toHaveAttribute("tabindex", "0");
  const overviewPanelId = await overviewTab.getAttribute("aria-controls");
  await expect(page.locator(`#${overviewPanelId}`)).toHaveAttribute("aria-labelledby", await overviewTab.getAttribute("id") ?? "");
  await overviewTab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Chat" })).toBeFocused();
  await expect(page.getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");

  await page.goto("/agents");
  await expect(table.getByRole("row", { name: /Alpha/ })).toBeVisible();
  await evidence(page, "desktop-agents-table.png");
});

test("Agents view exposes reusable List and Graph tabs", async ({ page }) => {
  await page.goto("/agents");
  const listTab = page.getByRole("tab", { name: "List" });
  const graphTab = page.getByRole("tab", { name: "Graph" });
  await expect(listTab).toHaveAttribute("aria-selected", "true");
  await graphTab.click();
  await expect(graphTab).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".react-flow")).toBeVisible();
  await evidence(page, "desktop-agents-graph.png");
  await listTab.click();
  await expect(page.getByRole("table")).toBeVisible();
});

test("Providers DataTable actions are keyboard operable and modal closes with Escape", async ({ page }) => {
  await page.goto("/providers");
  const table = page.locator('[data-i7n-name="providers.configured.table"]');
  await expect(table).toContainText("2 providers");
  await expect(table).toContainText("openai-main");

  const configuredTab = page.getByRole("tab", { name: /Configured/ });
  await configuredTab.focus();
  await page.keyboard.press("ArrowRight");
  const registryTab = page.getByRole("tab", { name: "Registry" });
  await expect(registryTab).toBeFocused();
  await expect(registryTab).toHaveAttribute("aria-selected", "true");
  const registryPanelId = await registryTab.getAttribute("aria-controls");
  await expect(page.locator(`#${registryPanelId}`)).toHaveAttribute("aria-labelledby", await registryTab.getAttribute("id") ?? "");
  await page.keyboard.press("ArrowLeft");
  await expect(configuredTab).toHaveAttribute("aria-selected", "true");

  const expandButton = table.getByRole("button", { name: "Expand details for openai-main" });
  await expandButton.focus();
  await page.keyboard.press("Enter");
  await expect(table.getByText("API key")).toBeVisible();
  await evidence(page, "desktop-providers-table.png");

  const editButton = table.getByRole("button", { name: "Edit", exact: true }).first();
  await editButton.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Edit: openai-main" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Edit: openai-main" })).toHaveCount(0);
});

test("Integrations DataTable exposes named identity and nested action buttons", async ({ page }) => {
  await page.goto("/integrations");
  const table = page.locator('[data-i7n-name="integrations.configured.table"]');
  await expect(table).toContainText("2 integrations");
  const githubRow = table.getByRole("row", { name: /github-main/ });
  await expect(githubRow).not.toHaveAttribute("tabindex");
  const identityButton = githubRow.getByRole("button", { name: "Edit credentials for github-main" });
  await identityButton.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: /Edit credentials — github-main/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: /Edit credentials — github-main/ })).toHaveCount(0);
  await expect(identityButton).toBeFocused();

  const removeButton = githubRow.getByRole("button", { name: "Remove" });
  await removeButton.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Remove Integration" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Remove Integration" })).toHaveCount(0);
  await expect(removeButton).toBeFocused();
  await evidence(page, "desktop-integrations-table.png");
});

test("mobile shell exposes navigation and a contained DataTable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/agents");
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Agents", exact: true })).toHaveAttribute("aria-current", "page");
  const mobileToggle = page.getByRole("button", { name: "Collapse sidebar" });
  await expect(mobileToggle).toBeVisible();
  await expect(mobileToggle).toBeInViewport();
  await expect(page.locator('[data-i7n-name="dashboard.agents.table-card"]')).toContainText("Alpha");
  await assertNoDocumentOverflow(page);
  await evidence(page, "mobile-navigation-and-agents-table.png", true);

  await mobileToggle.click();
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeHidden();
  await page.getByRole("button", { name: "Expand sidebar" }).click();
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  await assertNoDocumentOverflow(page);
});
