import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// Static identity + persisted config from hosts.json. Cheap and local;
// the page shell renders as soon as this resolves. Runtime fields
// (status, process counts) come from useAgentHealth below.
//
// #758: polling was previously here at 10s, dragging the slow SSH
// health probe into the foreground every tick. The probe now lives on
// the /health endpoint and useAgentHealth owns the cadence for those
// fields. We keep a 10s refetch here too because the data still
// changes out of band — operator runs `clawctl provider attach` from
// another terminal, gateway port reallocation on upgrade, onboarding
// step transitions, and the uptime string is recomputed each fetch.
// The static endpoint is now just a hosts.json read so the cost is
// negligible (ATX W2 from initial review).
export function useAgent(key: string) {
  return useQuery({
    queryKey: ["agent", key],
    queryFn: () => api.getAgent(key),
    enabled: !!key,
    refetchInterval: 10_000,
  });
}

// Live runtime probe for the agent detail page. Independent loading
// state lets each section show a skeleton while the SSH probe is in
// flight, and a failure here surfaces inline without blanking the
// rest of the page (#758).
export function useAgentHealth(key: string) {
  return useQuery({
    queryKey: ["agent-health", key],
    queryFn: () => api.getAgentHealth(key),
    enabled: !!key,
    refetchInterval: 10_000,
  });
}

// Agent types whose dashboard SPA requires an in-browser pairing
// handshake. Keep in sync with `_PAIRING_AGENT_TYPES` in
// `src/clawrium/gui/routes/fleet.py`. Today only zeroclaw — hermes
// serves its dashboard without an in-process pairing step.
export const PAIRING_AGENT_TYPES = new Set(["zeroclaw"]);

// Agent types whose dashboard SPA prompts the user to paste a
// long-lived gateway bearer token on first open. The token is the same
// install-time bearer persisted in hosts.json under
// `agents.<name>.config.gateway.auth`. Today only openclaw — zeroclaw
// uses the one-shot pairing-code handshake above, and hermes gates on
// the SSH key only. Keep in sync with `_TOKEN_REVEAL_AGENT_TYPES` in
// `src/clawrium/gui/routes/fleet.py`.
export const TOKEN_REVEAL_AGENT_TYPES = new Set(["openclaw"]);

// B2 (#560 / #567): the agent-type allowlist that used to live here
// (`WEB_UI_AGENT_TYPES`) was a client-side duplicate of the backend
// manifest resolver in `src/clawrium/core/web_ui.py:resolve`. Adding
// `features.web_ui` to a new agent's manifest had to also touch this
// file to make the button render — exactly the "single gate" violation
// AGENTS.md explicitly forbids. The hook now always fetches the
// backend `/web-ui` endpoint and the caller renders the button based
// on `data.available`. The backend returns `available: false` with a
// human-readable `reason` for any agent type whose manifest does not
// declare `features.web_ui`, so the network cost is one cheap GET per
// detail-page view (results are tanstack-cached and the response is
// memoized by `query.state.data?.available` for refetch).
export function useAgentWebUI(key: string, status: string) {
  return useQuery({
    queryKey: ["agent-web-ui", key, status],
    queryFn: () => api.getAgentWebUI(key),
    enabled: !!key,
    // Polling policy (W2 from ATX round 4):
    //   - available=true  → stop polling (tunnel is up).
    //   - available=false WITH a reason returned by the backend
    //     (`Agent type 'X' does not expose a native web UI.`) → stop
    //     polling too: agent type is permanently no-UI; no amount of
    //     refetching changes that. The previous unconditional 30s
    //     interval kept hitting the endpoint forever for every
    //     nemoclaw / etc. fleet member.
    //   - available=false with a transient reason (tunnel error,
    //     daemon not reachable, etc.) → keep the 30s retry so a
    //     blip clears itself.
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 30_000;
      if (data.available) return false;
      // Backend reasons that indicate a permanent no-UI verdict for
      // this agent type. Matched as a substring so phrasing tweaks
      // upstream do not silently break polling behavior.
      if (data.reason && data.reason.includes("does not expose")) {
        return false;
      }
      return 30_000;
    },
  });
}

export function useAgentPairingCode(key: string) {
  // Mint-on-demand mutation. Each call overwrites the daemon's
  // in-memory pairing code; the previous code becomes invalid.
  return useMutation({
    mutationFn: () => api.mintAgentPairingCode(key),
  });
}

export function useAgentConnectionToken(key: string) {
  // Reveal-on-demand mutation. The token is static (the same
  // install-time bearer), so this is a privileged read rather than a
  // mutation — modeled as `useMutation` to keep the secret out of the
  // background-refetch query cache and to make the reveal an explicit
  // user gesture.
  return useMutation({
    mutationFn: () => api.getAgentConnectionToken(key),
  });
}

export function useAgentActions(key: string) {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["agent", key] });
    // #758: live status / uptime live on the health query now. Without
    // this invalidation the status pill stays stale until the 10s poll
    // ticks, masking the result of the user's own action.
    queryClient.invalidateQueries({ queryKey: ["agent-health", key] });
    queryClient.invalidateQueries({ queryKey: ["fleet"] });
    // After a restart/stop/start the tunnel state file may point at a
    // process that's about to die. Invalidate the web-ui query so the
    // header re-fetches rather than handing the user a stale local_url.
    queryClient.invalidateQueries({ queryKey: ["agent-web-ui", key] });
  };

  const start = useMutation({
    mutationFn: () => api.startAgent(key),
    onSuccess: invalidate,
  });

  const stop = useMutation({
    mutationFn: () => api.stopAgent(key),
    onSuccess: invalidate,
  });

  const restart = useMutation({
    mutationFn: () => api.restartAgent(key),
    onSuccess: invalidate,
  });

  return { start, stop, restart };
}
