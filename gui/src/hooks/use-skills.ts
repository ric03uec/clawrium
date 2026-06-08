import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// Skills catalog is read from the in-repo filesystem and only changes
// across a `clm` upgrade. 5 minutes is plenty for a single session and
// suppresses background refetches on every window focus / modal open.
const SKILLS_STALE_MS = 5 * 60 * 1000;

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: api.getSkills,
    staleTime: SKILLS_STALE_MS,
  });
}

export function useSkill(registry: string | null, name: string | null) {
  return useQuery({
    queryKey: ["skill", registry, name],
    queryFn: () => api.getSkill(registry!, name!),
    enabled: !!registry && !!name,
    staleTime: SKILLS_STALE_MS,
  });
}

export function useAgentSkills(agentKey: string | null) {
  return useQuery({
    queryKey: ["agent-skills", agentKey],
    queryFn: () => api.getAgentSkills(agentKey as string),
    enabled: !!agentKey,
  });
}

interface AgentSkillMutationVars {
  agentKey: string;
  registry: string;
  name: string;
}

export function useInstallAgentSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentKey, registry, name }: AgentSkillMutationVars) =>
      api.installAgentSkill(agentKey, registry, name),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({
        queryKey: ["agent-skills", vars.agentKey],
      });
    },
  });
}

export function useRemoveAgentSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentKey, registry, name }: AgentSkillMutationVars) =>
      api.removeAgentSkill(agentKey, registry, name),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({
        queryKey: ["agent-skills", vars.agentKey],
      });
    },
  });
}

export function useAddAgentSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      agentKey,
      payload,
    }: {
      agentKey: string;
      payload: Parameters<typeof api.addAgentSkill>[1];
    }) => api.addAgentSkill(agentKey, payload),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({
        queryKey: ["agent-skills", vars.agentKey],
      });
    },
  });
}

export function useEditAgentSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      agentKey,
      name,
      content,
    }: {
      agentKey: string;
      name: string;
      content: string;
    }) => api.editAgentSkill(agentKey, name, content),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({
        queryKey: ["agent-skills", vars.agentKey],
      });
    },
  });
}

export function useRemoveLocalAgentSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentKey, name }: { agentKey: string; name: string }) =>
      api.removeLocalAgentSkill(agentKey, name),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({
        queryKey: ["agent-skills", vars.agentKey],
      });
    },
  });
}

export function useAddOverlaySkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      registry,
      name,
      content,
    }: {
      registry: string;
      name: string;
      content: string;
    }) => api.addOverlaySkill(registry, name, content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}
