"use client";

import { useId, useState } from "react";
import { AgentDetail, AgentDetailHealth, AgentStatus } from "@/lib/types";
import { StatusDot } from "@/components/ui/status-dot";
import { OSIcon } from "@/components/ui/os-icon";
import { Button } from "@/components/ui/button";
import {
  PAIRING_AGENT_TYPES,
  TOKEN_REVEAL_AGENT_TYPES,
  useAgentActions,
  useAgentConnectionToken,
  useAgentPairingCode,
  useAgentWebUI,
} from "@/hooks";

interface AgentHeaderProps {
  agent: AgentDetail;
  // #758: live runtime fields. Undefined while the probe is in flight;
  // header falls back to the static "checking" status and disables the
  // lifecycle buttons (we don't yet know whether the agent is running).
  health: AgentDetailHealth | undefined;
}

// #870: pure mapping from live status → operator-facing reason a
// lifecycle action is unavailable. Returns "" when the action IS
// available. Kept module-scope so it's unit-testable without React
// and so a future status literal only needs a single edit.
export function lifecycleDisabledReason(
  status: AgentStatus,
  action: "start" | "restart" | "stop",
): string {
  if (status === "install_missing") {
    return "On-host install missing — reinstall required";
  }
  if (status === "checking") {
    return "Waiting for status…";
  }
  if (action === "start") {
    return status === "stopped" ? "" : "Agent is not stopped";
  }
  // restart + stop share the running-required gate
  return status === "running" ? "" : "Agent is not running";
}

export function AgentHeader({ agent, health }: AgentHeaderProps) {
  const { start, stop, restart } = useAgentActions(agent.agent_key);
  // Health-derived: the SSH probe is the source of truth for the
  // lifecycle buttons. Until it lands, status is "checking" and both
  // Start and Restart/Stop are hidden to avoid acting on stale data.
  const liveStatus = health?.status ?? agent.status;
  const isRunning = liveStatus === "running";
  const isInstallMissing = liveStatus === "install_missing";

  // #870: lifecycle buttons render unconditionally with a stable
  // [Start, Restart, Stop] order so state transitions cannot shift a
  // destructive action under the user's cursor. Invalid actions are
  // disabled via aria-disabled + guarded onClick (NOT native
  // `disabled`) so the button stays in the tab order and screen
  // readers announce the reason via aria-describedby — native
  // `disabled` drops focus and native `title` is not reliably
  // exposed to AT or on touch devices.
  const startDisabledReason = lifecycleDisabledReason(liveStatus, "start");
  const restartDisabledReason = lifecycleDisabledReason(liveStatus, "restart");
  const stopDisabledReason = lifecycleDisabledReason(liveStatus, "stop");

  // Per-instance ids so a fleet/list view rendering multiple headers
  // does not collide on the aria-describedby target — AT would
  // otherwise resolve to the first-mounted reason span and announce
  // the wrong agent's status.
  const reactId = useId();
  const startReasonId = `${reactId}-start-reason`;
  const restartReasonId = `${reactId}-restart-reason`;
  const stopReasonId = `${reactId}-stop-reason`;

  // B2 (#560 / #567): backend `/web-ui` returns `available: false` with
  // a `reason` for any agent type whose manifest does not declare
  // `features.web_ui` (see src/clawrium/core/web_ui.py:resolve). There
  // is no client-side agent-type allowlist — the backend is the
  // single gate.
  //
  // Render policy (W1/W3 from ATX round 4):
  //   - data.available === true  → fully enabled button.
  //   - loading / transient error (no data yet, OR available=false with
  //     a transient reason) → disabled button with informative tooltip,
  //     so the user gets feedback that the system is trying.
  //   - permanent no-UI (`reason` says "does not expose") → button is
  //     hidden entirely; rendering a perma-disabled button on every
  //     nemoclaw page was the previous UX regression.
  // Keyed on the live status so the web-ui query re-resolves after a
  // status transition (e.g. start → running flips tunnel availability).
  const webUI = useAgentWebUI(agent.agent_key, liveStatus);
  const webUIPermanentlyUnavailable =
    webUI.data?.available === false &&
    !!webUI.data?.reason &&
    webUI.data.reason.includes("does not expose");
  const showWebUI = !webUIPermanentlyUnavailable;
  const webUIReady = webUI.data?.available === true && !!webUI.data?.local_url;
  const webUITooltip = webUI.isLoading
    ? "Establishing tunnel…"
    : webUI.isError
      ? "Could not reach backend — will retry."
      : webUIReady
        ? "Open the native dashboard in a new tab"
        : webUI.data?.reason || "Native UI not available";

  // Pairing code only meaningful for agent types whose SPA gates on an
  // in-process handshake (zeroclaw). The mint is on-demand: clicking the
  // button issues a fresh code, invalidating any previous one. We surface
  // the most recent successful response inline.
  const showPairing = PAIRING_AGENT_TYPES.has(agent.agent_type);
  const pairing = useAgentPairingCode(agent.agent_key);
  const [copied, setCopied] = useState(false);

  // Connection token only meaningful for agent types whose SPA prompts
  // for a long-lived gateway bearer on first open (openclaw). Unlike
  // the pairing code (one-shot, daemon mint) this is a privileged read
  // of the install-time bearer already in hosts.json — clicking
  // reveals it inline so the user can paste it into the Control UI's
  // login form. Independent copied state so the two Copy buttons do
  // not stomp on each other when both are present (they cannot be on
  // the same agent today, but keeping them independent makes the
  // future-multi-button case behave correctly).
  const showToken = TOKEN_REVEAL_AGENT_TYPES.has(agent.agent_type);
  const token = useAgentConnectionToken(agent.agent_key);
  const [tokenCopied, setTokenCopied] = useState(false);

  return (
    <div className="bg-white rounded-xl border border-default p-6 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <StatusDot status={liveStatus} size="lg" />
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
          {showWebUI && (
            <Button
              variant="secondary"
              size="sm"
              disabled={!webUIReady}
              onClick={() => {
                if (webUI.data?.local_url) {
                  window.open(
                    webUI.data.local_url,
                    "_blank",
                    "noopener,noreferrer",
                  );
                }
              }}
              title={webUITooltip}
              aria-label={webUITooltip}
            >
              {webUI.isLoading ? "Opening…" : "Open Agent UI"}
            </Button>
          )}
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
          {showToken && (
            <Button
              variant="secondary"
              size="sm"
              disabled={token.isPending}
              onClick={() => {
                setTokenCopied(false);
                token.mutate();
              }}
              title="Reveal the gateway bearer token to paste into the Control UI login"
              aria-label="Show connection token"
            >
              {token.isPending ? "Loading..." : "Show Connection Token"}
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              if (startDisabledReason || start.isPending) return;
              start.mutate();
            }}
            aria-disabled={!!startDisabledReason || start.isPending}
            aria-describedby={
              startDisabledReason ? startReasonId : undefined
            }
            title={startDisabledReason || undefined}
            className={
              startDisabledReason || start.isPending
                ? "opacity-50 cursor-not-allowed"
                : ""
            }
            data-testid="action-start"
          >
            {start.isPending ? "Starting..." : "Start"}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              if (restartDisabledReason || restart.isPending) return;
              restart.mutate();
            }}
            aria-disabled={!!restartDisabledReason || restart.isPending}
            aria-describedby={
              restartDisabledReason ? restartReasonId : undefined
            }
            title={restartDisabledReason || undefined}
            className={
              restartDisabledReason || restart.isPending
                ? "opacity-50 cursor-not-allowed"
                : ""
            }
            data-testid="action-restart"
          >
            {restart.isPending ? "Restarting..." : "Restart"}
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => {
              if (stopDisabledReason || stop.isPending) return;
              stop.mutate();
            }}
            aria-disabled={!!stopDisabledReason || stop.isPending}
            aria-describedby={
              stopDisabledReason ? stopReasonId : undefined
            }
            title={stopDisabledReason || undefined}
            className={
              stopDisabledReason || stop.isPending
                ? "opacity-50 cursor-not-allowed"
                : ""
            }
            data-testid="action-stop"
          >
            {stop.isPending ? "Stopping..." : "Stop"}
          </Button>
          {/* Visually-hidden reason spans referenced by aria-describedby
              so screen readers announce WHY each action is unavailable
              — `title` alone is not reliably exposed to AT or on touch. */}
          {startDisabledReason && (
            <span id={startReasonId} className="sr-only">
              {startDisabledReason}
            </span>
          )}
          {restartDisabledReason && (
            <span id={restartReasonId} className="sr-only">
              {restartDisabledReason}
            </span>
          )}
          {stopDisabledReason && (
            <span id={stopReasonId} className="sr-only">
              {stopDisabledReason}
            </span>
          )}
        </div>
      </div>

      {isInstallMissing && (
        // #811: hosts.json claims this agent is installed, but the
        // on-host service-manager artifact and/or home directory are
        // gone. Start/Stop/Restart would all fail at the systemd
        // / launchctl boundary; surface a reinstall hint. #870: the
        // hint moved out of the action-bar row so lifecycle buttons
        // keep a stable position across state transitions.
        // `role="alert"` because the span is conditionally mounted;
        // screen readers don't announce initial mounts of polite
        // (status) live regions but DO announce assertive
        // (alert) ones.
        <div className="mt-2 text-xs text-status-error" role="alert">
          On-host install missing — run{" "}
          <code className="font-mono">
            clawctl agent doctor {agent.agent_name}
          </code>
          , then reinstall via{" "}
          <code className="font-mono">clawctl agent delete</code>
          {" "}+{" "}
          <code className="font-mono">clawctl agent create</code>.
        </div>
      )}

      {(start.isError || stop.isError || restart.isError) && (
        <div className="mt-2 text-xs text-status-error" role="alert">
          {(start.error || stop.error || restart.error)?.message}
        </div>
      )}

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

      {showToken && (token.data || token.isError) && (
        <div className="mt-4 flex items-start gap-3 rounded-md border border-default bg-surface p-3 text-sm">
          {token.data && (
            <>
              <div className="flex-1">
                <div className="font-medium text-primary-text">
                  Connection token
                </div>
                <div className="mt-0.5 text-xs text-muted">
                  Paste into the Control UI&apos;s Gateway Token field. This
                  is the install-time bearer; treat it like a password.
                </div>
              </div>
              <code
                className="select-all rounded bg-white px-2 py-1 font-mono text-xs break-all text-primary-text max-w-md"
                style={{ wordBreak: "break-all" }}
              >
                {token.data.token}
              </code>
              <Button
                variant="secondary"
                size="sm"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(token.data!.token);
                    setTokenCopied(true);
                    setTimeout(() => setTokenCopied(false), 2000);
                  } catch {
                    // Clipboard API can fail in non-secure contexts;
                    // the token is still readable via select-all.
                  }
                }}
                aria-label="Copy connection token to clipboard"
              >
                {tokenCopied ? "Copied" : "Copy"}
              </Button>
            </>
          )}
          {token.isError && !token.data && (
            <div className="flex-1 text-red-600">
              <div className="font-medium">Could not retrieve token</div>
              <div className="mt-0.5 text-xs">
                {token.error instanceof Error
                  ? token.error.message
                  : "Unknown error"}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
