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

export function useAgentActions(key: string) {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["agent", key] });
    queryClient.invalidateQueries({ queryKey: ["fleet"] });
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
