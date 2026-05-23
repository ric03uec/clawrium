"use client";

import { AgentDetail } from "@/lib/types";
import { StatusDot } from "@/components/ui/status-dot";
import { Button } from "@/components/ui/button";
import { useAgentActions, useAgentWebUI, WEB_UI_AGENT_TYPES } from "@/hooks";

interface AgentHeaderProps {
  agent: AgentDetail;
}

export function AgentHeader({ agent }: AgentHeaderProps) {
  const { start, stop, restart } = useAgentActions(agent.agent_key);
  const isRunning = agent.status === "running";
  const isStopped = agent.status === "stopped";

  // Native UI button shows for any agent type whose manifest declares
  // `features.web_ui`. Allowlist lives in the hook so the fetch and the
  // render decision stay in sync.
  const showWebUI = WEB_UI_AGENT_TYPES.has(agent.agent_type);
  const webUI = useAgentWebUI(agent.agent_key, agent.agent_type, agent.status);

  return (
    <div className="bg-white rounded-xl border border-default p-6 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <StatusDot status={agent.status} size="lg" />
          <div>
            <h1 className="text-xl font-semibold text-primary-text">
              {agent.agent_name}
            </h1>
            <p className="text-sm text-muted">
              {agent.agent_type} v{agent.version} &middot; Host: {agent.host_alias || agent.host}
              {agent.model && ` · Model: ${agent.model}`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {showWebUI && (() => {
            const tooltip = webUI.isLoading
              ? "Establishing tunnel..."
              : webUI.isError
                ? "Could not reach backend — will retry."
                : webUI.data?.available
                  ? "Open the native dashboard in a new tab"
                  : webUI.data?.reason || "Native UI not available";
            return (
              <Button
                variant="secondary"
                size="sm"
                disabled={
                  webUI.isLoading ||
                  webUI.isError ||
                  !webUI.data?.available ||
                  !webUI.data?.local_url
                }
                onClick={() => {
                  if (webUI.data?.local_url) {
                    window.open(
                      webUI.data.local_url,
                      "_blank",
                      "noopener,noreferrer",
                    );
                  }
                }}
                title={tooltip}
                aria-label={tooltip}
              >
                {webUI.isLoading ? "Opening..." : "Open Agent UI"}
              </Button>
            );
          })()}
          {isStopped && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => start.mutate()}
              disabled={start.isPending}
            >
              {start.isPending ? "Starting..." : "Start"}
            </Button>
          )}
          {isRunning && (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => restart.mutate()}
                disabled={restart.isPending}
              >
                {restart.isPending ? "Restarting..." : "Restart"}
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={() => stop.mutate()}
                disabled={stop.isPending}
              >
                {stop.isPending ? "Stopping..." : "Stop"}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
