// Fleet types
export interface FleetResponse {
  agents: AgentSummary[];
  summary: FleetSummary;
}

export interface FleetSummary {
  total: number;
  running: number;
  provisioning: number;
  hosts: number;
}

export interface AgentSummary {
  agent_key: string;
  agent_name: string;
  agent_type: string;
  host: string;
  host_alias: string;
  status: AgentStatus;
  model: string;
  uptime: string;
  gateway_url: string;
}

export type AgentStatus =
  | "running"
  | "stopped"
  | "degraded"
  | "not_installed"
  | "pending_onboard"
  | "onboarding"
  | "ready"
  | "unknown";

export interface AgentDetail extends AgentSummary {
  version: string;
  device_id: string;
  provider: string;
  provider_type: string;
  onboarding_step: string;
  gateway_port: number | null;
}

export interface ActionResponse {
  success: boolean;
  operation: string;
  agent: string;
}

// Topology types
export interface TopologyResponse {
  control: TopologyControl;
  hosts: TopologyHost[];
  connections: TopologyConnection[];
  summary: TopologySummary;
}

export interface TopologySummary {
  total_agents: number;
  running: number;
  total_hosts: number;
}

export interface TopologyControl {
  label: string;
  description: string;
}

export interface TopologyAddress {
  address: string;
  is_primary: boolean;
  label: string | null;
}

export interface TopologyHost {
  hostname: string;
  alias: string;
  user: string;
  addresses: TopologyAddress[];
  has_key: boolean;
  agent_count: number;
  agents: TopologyAgent[];
}

export interface TopologyAgent {
  agent_key: string;
  agent_name: string;
  agent_type: string;
  status: AgentStatus;
  model: string;
  version: string;
  uptime: string;
  provider: string;
  provider_type: string;
}

export interface TopologyConnection {
  source: string;
  target: string;
  protocol: string;
}

// Provider types
export interface Provider {
  name: string;
  type: string;
  endpoint: string;
  default_model: string;
  available_models: string[];
  has_api_key: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProviderTypeInfo {
  endpoint: string | null;
  models: string[] | null;
  requires_api_key: boolean;
  requires_endpoint: boolean;
}

export type ProviderTypesMap = Record<string, ProviderTypeInfo>;

export interface ProviderType {
  type: string;
  name: string;
  requires_endpoint: boolean;
  requires_api_key: boolean;
}

export interface ProviderCreate {
  name: string;
  type: string;
  endpoint?: string;
  default_model?: string;
  api_key?: string;
}

export interface ProviderUpdate {
  endpoint?: string;
  default_model?: string;
  api_key?: string;
}

export interface CatalogModel {
  id: string;
  name: string;
  lab: string;
  context_window: number;
  tags: string[];
  provider_type: string;
}

// Usage types
export interface UsageSummary {
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost: number;
  total_requests: number;
  period_days: number;
}

export interface UsageHistory {
  period: string;
  tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  requests: number;
}

export interface AgentUsage {
  agent_key: string;
  agent_name: string;
  tokens: number;
  cost: number;
  requests: number;
}

// Settings types
export interface Settings {
  config_dir: string;
  hosts_file: string;
  providers_file: string;
  secrets_file: string;
  usage_db: string;
}

export interface VersionInfo {
  version: string;
  platform: string;
  python_version: string;
  arch: string;
}

// Memory types
export interface MemoryInfo {
  supported: boolean;
  workspace_path: string;
  files: MemoryFile[];
  error?: string;
}

export interface MemoryFile {
  name: string;
  exists: boolean;
  size_bytes: number;
  relative_path: string;
}

export interface MemoryFileContent {
  filename: string;
  content: string;
}

// Chat types
export interface ChatInfo {
  supported: boolean;
  type: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

// Logs types
export interface LogEntry {
  timestamp: string;
  message: string;
  priority: string;
}

export interface LogsResponse {
  logs: LogEntry[];
  error?: string;
}
