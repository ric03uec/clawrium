import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useAgent(key: string) {
  return useQuery({
    queryKey: ["agent", key],
    queryFn: () => api.getAgent(key),
    enabled: !!key,
    refetchInterval: 10_000,
  });
}

export const WEB_UI_AGENT_TYPES = new Set(["hermes", "zeroclaw"]);

export function useAgentWebUI(key: string, agentType: string, status: string) {
  return useQuery({
    queryKey: ["agent-web-ui", key, status],
    queryFn: () => api.getAgentWebUI(key),
    // Allowlist of agent types whose manifest declares `features.web_ui`.
    // Other types return available=false from the backend, but we skip the
    // fetch to avoid a useless round-trip per detail page view. Keep this
    // in sync with the agent manifests under
    // src/clawrium/platform/registry/<type>/manifest.yaml.
    enabled: !!key && WEB_UI_AGENT_TYPES.has(agentType),
    // Retry an unavailable tunnel every 30s so a transient failure clears
    // itself once the host is reachable again. We stop retrying as soon as
    // the tunnel is up to keep the reaper map quiet.
    refetchInterval: (query) =>
      query.state.data?.available ? false : 30_000,
  });
}

export function useAgentActions(key: string) {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["agent", key] });
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
