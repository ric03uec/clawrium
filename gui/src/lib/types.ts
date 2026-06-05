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

export interface AgentHealth {
  agent_key: string;
  status: AgentStatus;
  process_running: boolean | null;
  health_error: string | null;
  cpu_count: number | null;
  memory_total_mb: number | null;
  missing_secrets: string[] | null;
}

export interface FleetHealthResponse {
  summary: FleetSummary;
  agents: AgentHealth[];
}

export type OSFamily = "linux" | "darwin";

export interface AgentSummary {
  agent_key: string;
  agent_name: string;
  agent_type: string;
  host: string;
  host_alias: string;
  /** Host OS family from hosts.json, surfaced for OS icon rendering (#469). */
  host_os_family: OSFamily | null;
  status: AgentStatus;
  model: string;
  uptime: string;
  gateway_url: string | null;
  provider: string;
  provider_type: string;
  // Health fields merged in by useFleetHealth; null until the probe lands.
  process_running?: boolean | null;
  health_error?: string | null;
  cpu_count?: number | null;
  memory_total_mb?: number | null;
  missing_secrets?: string[] | null;
}

export type AgentStatus =
  | "running"
  | "stopped"
  | "degraded"
  | "not_installed"
  | "pending_onboard"
  | "onboarding"
  | "ready"
  | "checking"
  | "unknown";

export interface AgentDetail extends AgentSummary {
  version: string;
  device_id: string;
  onboarding_step: string;
  gateway_port: number | null;
  // Max manifest version compatible with this host's hardware. `null`
  // when the host's os/arch has no matching platform entry. Issue #592.
  latest_supported_version: string | null;
}

export interface ActionResponse {
  success: boolean;
  operation: string;
  agent: string;
}

export interface WebUIResponse {
  available: boolean;
  local_url: string | null;
  reason: string | null;
}

// Response from POST /fleet/agents/{key}/pairing-code. Returned only by
// agent types whose web dashboard requires an in-browser pairing
// handshake (zeroclaw). The code is one-shot: a successful pair on the
// daemon consumes it; another mint call overwrites it.
export interface PairingCodeResponse {
  pairing_code: string;
}

// Response from POST /fleet/agents/{key}/connection-token. Returned only
// by agent types whose dashboard SPA prompts for a long-lived gateway
// bearer on first open (openclaw). The token is the same install-time
// bearer persisted in hosts.json — revealing it does not mutate state
// on either the GUI server or the agent daemon.
export interface ConnectionTokenResponse {
  token: string;
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
  hardware?: HostHardware | null;
  /** OS family for the host; null on hosts created before the field
   * was added. Used by the topology agent node to render an OS icon. */
  os_family?: OSFamily | null;
}

export interface HostHardwareGpu {
  present: boolean;
  vendor: string | null;
  error?: string | null;
}

export interface HostHardware {
  architecture: string | null;
  cores: number | null;
  memtotal_mb: number | null;
  gpu: HostHardwareGpu;
  product_name: string | null;
  system_vendor: string | null;
}

export type AcceleratorVendor = "nvidia" | "amd";

export interface TopologyAgent {
  agent_key: string;
  agent_name: string;
  agent_type: string;
  status: AgentStatus;
  model: string;
  version: string;
  uptime: string;
  provider: string | null;
  provider_type: string | null;
  provider_endpoint: string | null;
  provider_accelerator_vendor: AcceleratorVendor | null;
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
  endpoint: string | null;
  default_model: string | null;
  available_models: string[] | null;
  has_api_key: boolean;
  accelerator_vendor: AcceleratorVendor | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ModelInfo {
  id: string;
  name: string;
  lab: string;
  context_window: number;
  tags: string[];
}

export interface ProviderTypeInfo {
  endpoint: string | null;
  models: ModelInfo[];
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
  accelerator_vendor?: AcceleratorVendor;
}

export interface ProviderUpdate {
  endpoint?: string;
  default_model?: string;
  api_key?: string;
  accelerator_vendor?: AcceleratorVendor;
}

// Hermes multi-provider attachment row. For singleton agent types the
// attachments list carries plain strings — the modal collapses those
// into stub entries with empty role/model before rendering.
export interface ProviderAttachment {
  name: string;
  role: string;
  model: string;
}

export interface AgentAttachmentsResponse {
  agent: string;
  agent_type: string;
  supports_multi: boolean;
  // Mixed union — hermes returns rich attachment objects, singleton
  // agent types (zeroclaw/openclaw) return plain provider names.
  attachments: (ProviderAttachment | string)[];
  available_roles: string[];
  primary_attached: boolean;
  aux_count: number;
}

export interface AttachmentRequest {
  agent: string;
  role?: string | null;
}

export interface AttachmentResponse {
  success: boolean;
  agent: string;
  name: string;
  role?: string | null;
  already_attached?: boolean;
}

export interface CatalogModel {
  id: string;
  name: string;
  lab: string;
  context_window: number;
  tags: string[];
  provider_type: string;
}

// Integration types
export interface IntegrationCredentialDef {
  key: string;
  description: string;
  required: boolean;
}

export interface IntegrationType {
  description: string;
  credentials: IntegrationCredentialDef[];
}

export type IntegrationTypesMap = Record<string, IntegrationType>;

export interface Integration {
  name: string;
  type: string;
  credential_keys: string[];
  configured_credential_keys: string[];
  agent_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface IntegrationAgentRef {
  hostname: string;
  agent_key: string;
}

export interface IntegrationDetail extends Integration {
  agents_using: IntegrationAgentRef[];
}

export interface IntegrationCreate {
  name: string;
  type: string;
  credentials: Record<string, string>;
}

export interface IntegrationCredentialsUpdate {
  credentials: Record<string, string>;
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

// Skills catalog types
export type SkillRegistry = "clawrium" | "openclaw" | "hermes" | "zeroclaw";

export type SkillCompatibility = Record<
  "openclaw" | "hermes" | "zeroclaw",
  boolean
>;

export interface SkillSummary {
  ref: string;
  registry: SkillRegistry;
  name: string;
  description: string | null;
  version: string | null;
  // True when the backend could load the directory but failed to
  // parse the skill's metadata. Distinguishes a broken catalog
  // entry from a legitimately undescribed skill.
  degraded?: boolean;
}

export interface SkillsCatalog {
  registries: SkillRegistry[];
  skills: Record<SkillRegistry, SkillSummary[]>;
  // Present (with a short reason string) when the backend could not
  // read the catalog directory — e.g. permission denied. The frontend
  // surfaces this as a banner so empty tabs aren't mistaken for an
  // empty repo.
  error?: string;
}

export interface SkillDetail {
  ref: string;
  registry: SkillRegistry;
  name: string;
  metadata: Record<string, unknown>;
  body: string;
  compatibility: SkillCompatibility;
}

// Per-agent skills (Phase 5). Both installed and available rows reuse
// SkillSummary but allow `registry`/`name` to be null on installed rows
// when the state file carries a ref that no longer parses.
export interface AgentSkillRow {
  ref: string;
  registry: SkillRegistry | null;
  name: string | null;
  description: string | null;
  version: string | null;
}

export interface AgentSkills {
  agent_name: string;
  agent_type: string;
  installed: AgentSkillRow[];
  available: AgentSkillRow[];
}

export interface AgentSkillMutationResponse {
  success: boolean;
  agent_name: string;
  ref: string;
  changed: boolean;
  installed: string[];
}
