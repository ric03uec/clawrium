"use client";

import { useState } from "react";
import { AgentDetail } from "@/lib/types";
import { StatusDot } from "@/components/ui/status-dot";
import { OSIcon } from "@/components/ui/os-icon";
import { Button } from "@/components/ui/button";
import {
  PAIRING_AGENT_TYPES,
  WEB_UI_AGENT_TYPES,
  useAgentActions,
  useAgentPairingCode,
  useAgentWebUI,
} from "@/hooks";

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

  // Pairing code only meaningful for agent types whose SPA gates on an
  // in-process handshake (zeroclaw). The mint is on-demand: clicking the
  // button issues a fresh code, invalidating any previous one. We surface
  // the most recent successful response inline.
  const showPairing = PAIRING_AGENT_TYPES.has(agent.agent_type);
  const pairing = useAgentPairingCode(agent.agent_key);
  const [copied, setCopied] = useState(false);

  return (
    <div className="bg-white rounded-xl border border-default p-6 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <StatusDot status={agent.status} size="lg" />
          <div>
            <h1 className="text-xl font-semibold text-primary-text">
              {agent.agent_name}
            </h1>
            <p className="text-sm text-muted flex items-center gap-1.5 flex-wrap">
              <span>{agent.agent_type} v{agent.version}</span>
              <span aria-hidden="true">·</span>
              <span>Host: {agent.host_alias || agent.host}</span>
              <OSIcon os={agent.host_os_family} variant="chip" />
              {agent.model && (
                <>
                  <span aria-hidden="true">·</span>
                  <span>Model: {agent.model}</span>
                </>
              )}
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
          {showPairing && (
            <Button
              variant="secondary"
              size="sm"
              disabled={pairing.isPending || !isRunning}
              onClick={() => {
                setCopied(false);
                pairing.mutate();
              }}
              title={
                !isRunning
                  ? "Start the agent to mint a pairing code"
                  : "Mint a fresh pairing code (overwrites any previous code)"
              }
              aria-label="Generate pairing code"
            >
              {pairing.isPending ? "Generating..." : "Get Pairing Code"}
            </Button>
          )}
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

      {showPairing && (pairing.data || pairing.isError) && (
        <div className="mt-4 flex items-start gap-3 rounded-md border border-default bg-surface p-3 text-sm">
          {pairing.data && (
            <>
              <div className="flex-1">
                <div className="font-medium text-primary-text">
                  Pairing code
                </div>
                <div className="mt-0.5 text-xs text-muted">
                  Paste this into the dashboard prompt. The code is one-shot;
                  the next mint replaces it.
                </div>
              </div>
              <code className="select-all rounded bg-white px-2 py-1 font-mono text-base tracking-widest text-primary-text">
                {pairing.data.pairing_code}
              </code>
              <Button
                variant="secondary"
                size="sm"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(
                      pairing.data!.pairing_code,
                    );
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  } catch {
                    // Clipboard API can fail in non-secure contexts;
                    // the code is still readable via select-all.
                  }
                }}
                aria-label="Copy pairing code to clipboard"
              >
                {copied ? "Copied" : "Copy"}
              </Button>
            </>
          )}
          {pairing.isError && !pairing.data && (
            <div className="flex-1 text-red-600">
              <div className="font-medium">Could not mint a pairing code</div>
              <div className="mt-0.5 text-xs">
                {pairing.error instanceof Error
                  ? pairing.error.message
                  : "Unknown error"}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
