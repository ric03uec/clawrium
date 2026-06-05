"use client";

import { AgentDetail } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { useAgentSkills } from "@/hooks";
import { AgentAttachmentsCard } from "@/components/providers";

interface OverviewTabProps {
  agent: AgentDetail;
  agentKey: string;
}

export function OverviewTab({ agent, agentKey }: OverviewTabProps) {
  const { data: skillsData } = useAgentSkills(agentKey);

  const installedSkills = skillsData?.installed ?? [];

  return (
    <div className="space-y-4 p-4">
      {/* Provider attachments — actionable list with attach/detach */}
      <AgentAttachmentsCard agentName={agent.agent_name} />

      {/* Provider attachment summary (legacy single-provider snapshot) */}
      <Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-primary-text">
            Provider
          </h3>
          {agent.provider ? (
            <span className="text-xs bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-full">
              Connected
            </span>
          ) : (
            <span className="text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded-full">
              Not configured
            </span>
          )}
        </div>
        {agent.provider ? (
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div>
              <span className="text-muted text-xs block">Name</span>
              <span className="text-primary-text font-medium">
                {agent.provider}
              </span>
            </div>
            <div>
              <span className="text-muted text-xs block">Type</span>
              <span className="text-primary-text">
                {agent.provider_type}
              </span>
            </div>
            <div>
              <span className="text-muted text-xs block">Model</span>
              <span className="text-primary-text font-mono text-xs">
                {agent.model}
              </span>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted">
            No provider attached. Configure one on the Providers page.
          </p>
        )}
      </Card>

      {/* Installed skills */}
      <Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-primary-text">
            Skills
          </h3>
          <span className="text-xs text-muted">
            {installedSkills.length} installed
          </span>
        </div>
        {installedSkills.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {installedSkills.map((skill) => (
              <span
                key={skill.ref}
                className="inline-flex items-center gap-1.5 text-xs bg-panel border border-default rounded-full px-2.5 py-1"
              >
                <span className="text-primary-text font-medium">
                  {skill.registry}/{skill.name}
                </span>
                {skill.version && (
                  <span className="text-muted">v{skill.version}</span>
                )}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted">
            No skills installed. Add capabilities from the Skills page.
          </p>
        )}
      </Card>

      {/* Agent identity */}
      <Card padding="md">
        <h3 className="text-sm font-semibold text-primary-text mb-3">
          Agent Identity
        </h3>
        <div className="grid grid-cols-2 gap-y-3 gap-x-8 text-sm">
          <InfoRow label="Name" value={agent.agent_name} />
          <InfoRow label="Type" value={agent.agent_type} />
          <InfoRow label="Host" value={agent.host_alias || agent.host} />
          <VersionRow
            version={agent.version}
            latestSupportedVersion={agent.latest_supported_version}
            agentName={agent.agent_name}
          />
          <InfoRow label="Status" value={agent.status} />
          <InfoRow label="Uptime" value={agent.uptime || "—"} />
          {agent.gateway_url && (
            <InfoRow label="Gateway" value={agent.gateway_url} />
          )}
          {agent.device_id && (
            <InfoRow label="Device ID" value={agent.device_id} />
          )}
        </div>
      </Card>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-muted text-xs block">{label}</span>
      <span className="text-primary-text font-mono text-xs">{value}</span>
    </div>
  );
}

function isNewerVersion(latest: string, current: string): boolean {
  const parse = (v: string) => v.replace(/^v/, "").split(".").map((n) => parseInt(n, 10) || 0);
  const a = parse(latest);
  const b = parse(current);
  const len = Math.max(a.length, b.length);
  for (let i = 0; i < len; i++) {
    const ai = a[i] ?? 0;
    const bi = b[i] ?? 0;
    if (ai > bi) return true;
    if (ai < bi) return false;
  }
  return false;
}

function VersionRow({
  version,
  latestSupportedVersion,
  agentName,
}: {
  version: string;
  latestSupportedVersion: string | null;
  agentName: string;
}) {
  // `version === '?'` is the legacy sentinel from `cli/tui/data.py` for
  // agents that have never started — `parseInt('?', 10) || 0` would
  // resolve to 0 and falsely trip the badge for every agent in that
  // state. ATX W2 (issue #592).
  const versionKnown = !!version && version !== "?";
  const upgradeAvailable =
    !!latestSupportedVersion &&
    versionKnown &&
    isNewerVersion(latestSupportedVersion, version);

  return (
    <div data-testid="version-row">
      <span className="text-muted text-xs block">Version</span>
      <span className="text-primary-text font-mono text-xs">
        {version || "—"}
      </span>
      {upgradeAvailable && (
        <div
          data-testid="upgrade-available-badge"
          className="mt-1 inline-flex flex-col gap-0.5"
        >
          <span className="text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded-full font-mono">
            ↑ Upgrade available: {latestSupportedVersion}
          </span>
          <span className="text-xs text-muted font-mono">
            Run: clawctl agent upgrade {agentName}
          </span>
        </div>
      )}
    </div>
  );
}
