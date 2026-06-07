import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { SkillCreateInput, SkillUpdateInput } from "@/lib/types";

const SKILLS_STALE_MS = 5 * 60 * 1000;

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: api.getSkills,
    staleTime: SKILLS_STALE_MS,
  });
}

export function useSkill(source: string | null, name: string | null) {
  return useQuery({
    queryKey: ["skill", source, name],
    queryFn: () => api.getSkill(source!, name!),
    enabled: !!source && !!name,
    staleTime: SKILLS_STALE_MS,
  });
}

export function useCreateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SkillCreateInput) => api.createSkill(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

interface UpdateSkillVars {
  name: string;
  input: SkillUpdateInput;
}

export function useUpdateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, input }: UpdateSkillVars) =>
      api.updateSkill(name, input),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["skills"] });
      queryClient.invalidateQueries({ queryKey: ["skill", "local", vars.name] });
    },
  });
}

export function useDeleteSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.deleteSkill(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
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
  source: string;
  name: string;
}

export function useInstallAgentSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentKey, source, name }: AgentSkillMutationVars) =>
      api.installAgentSkill(agentKey, source, name),
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
    mutationFn: ({ agentKey, source, name }: AgentSkillMutationVars) =>
      api.removeAgentSkill(agentKey, source, name),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({
        queryKey: ["agent-skills", vars.agentKey],
      });
    },
  });
}
