const API_BASE = "/api";

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API error ${res.status}: ${body}`);
  }

  return res.json();
}

// Backend response wrappers
interface ProvidersResponse {
  providers: Provider[];
}

interface ProviderTypesResponse {
  types: ProviderTypesMap;
}

interface CatalogResponse {
  models: CatalogModel[];
}

interface UsageHistoryResponse {
  data: UsageHistory[];
}

interface UsageByAgentResponse {
  data: AgentUsage[];
}

interface UsageSummaryRaw {
  period_days: number;
  total_events: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_cost: number;
}

export const api = {
  // Fleet
  getFleet: () => request<FleetResponse>("/fleet"),
  getAgent: (key: string) => request<AgentDetail>(`/fleet/agents/${key}`),
  startAgent: (key: string) => request<ActionResponse>(`/agents/${key}/start`, { method: "POST" }),
  stopAgent: (key: string) => request<ActionResponse>(`/agents/${key}/stop`, { method: "POST" }),
  restartAgent: (key: string) => request<ActionResponse>(`/agents/${key}/restart`, { method: "POST" }),

  // Topology
  getTopology: () => request<TopologyResponse>("/fleet/topology"),

  // Providers (unwrap from { providers: [...] })
  getProviders: async (): Promise<Provider[]> => {
    const res = await request<ProvidersResponse>("/providers");
    return res.providers;
  },
  getProviderTypes: async (): Promise<ProviderTypesMap> => {
    const res = await request<ProviderTypesResponse>("/providers/types");
    return res.types;
  },
  getModelCatalog: async (provider?: string, search?: string): Promise<CatalogModel[]> => {
    const params = new URLSearchParams();
    if (provider) params.set("provider", provider);
    if (search) params.set("search", search);
    const qs = params.toString();
    const res = await request<CatalogResponse>(`/providers/catalog${qs ? `?${qs}` : ""}`);
    return res.models;
  },
  createProvider: (data: ProviderCreate) =>
    request<{ success: boolean; name: string }>("/providers", { method: "POST", body: JSON.stringify(data) }),
  updateProvider: (name: string, data: ProviderUpdate) =>
    request<{ success: boolean; name: string }>(`/providers/${name}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProvider: (name: string) =>
    request<{ success: boolean; name: string }>(`/providers/${name}`, { method: "DELETE" }),

  // Usage (unwrap from { data: [...] } and normalize field names)
  getUsageSummary: async (days = 30): Promise<UsageSummary> => {
    const raw = await request<UsageSummaryRaw>(`/usage/summary?days=${days}`);
    return {
      total_tokens: raw.total_tokens,
      total_input_tokens: raw.total_prompt_tokens,
      total_output_tokens: raw.total_completion_tokens,
      total_cost: raw.total_cost,
      total_requests: raw.total_events,
      period_days: raw.period_days,
    };
  },
  getUsageHistory: async (days = 7, granularity = "day"): Promise<UsageHistory[]> => {
    const res = await request<UsageHistoryResponse>(
      `/usage/history?days=${days}&granularity=${granularity}`
    );
    return res.data;
  },
  getUsageByAgent: async (days = 30): Promise<AgentUsage[]> => {
    const res = await request<UsageByAgentResponse>(`/usage/by-agent?days=${days}`);
    return res.data;
  },

  // Settings
  getSettings: () => request<Settings>("/settings"),
  getVersion: () => request<VersionInfo>("/settings/version"),

  // Usage management
  clearUsage: () => request<{ success: boolean; deleted: number }>("/usage", { method: "DELETE" }),
  exportUsageCsv: async (): Promise<void> => {
    const res = await fetch(`${API_BASE}/usage/export`);
    if (!res.ok) throw new Error(`Export failed: ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "clawrium-usage.csv";
    a.click();
    URL.revokeObjectURL(url);
  },

  // Agent Memory
  getMemoryFiles: (key: string) => request<MemoryInfo>(`/agents/${key}/memory`),
  getMemoryFile: (key: string, filename: string) =>
    request<MemoryFileContent>(`/agents/${key}/memory/${filename}`),
  updateMemoryFile: (key: string, filename: string, content: string) =>
    request<{ success: boolean }>(`/agents/${key}/memory/${filename}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),

  // Agent Chat
  getChatInfo: (key: string) => request<ChatInfo>(`/agents/${key}/chat/info`),
  sendChatMessage: async (key: string, message: string, session = "main"): Promise<string> => {
    const res = await fetch(`${API_BASE}/agents/${key}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session }),
    });
    if (!res.ok) throw new Error(`Chat error: ${res.status}`);

    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let fullText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ") && line !== "data: [DONE]") {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === "content") fullText = data.text;
            if (data.type === "error") throw new Error(data.message);
          } catch (e) {
            if (e instanceof SyntaxError) continue;
            throw e;
          }
        }
      }
    }
    return fullText;
  },

  // Agent Logs
  getAgentLogs: (key: string, lines = 100) =>
    request<LogsResponse>(`/agents/${key}/logs?lines=${lines}`),
};

// Type imports (re-exported from types.ts for convenience)
import type {
  FleetResponse,
  AgentDetail,
  ActionResponse,
  TopologyResponse,
  Provider,
  ProviderTypesMap,
  ProviderCreate,
  ProviderUpdate,
  CatalogModel,
  UsageSummary,
  UsageHistory,
  AgentUsage,
  Settings,
  VersionInfo,
  MemoryInfo,
  MemoryFileContent,
  ChatInfo,
  LogsResponse,
} from "./types";
