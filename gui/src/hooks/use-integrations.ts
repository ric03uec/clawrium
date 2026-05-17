import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  IntegrationCreate,
  IntegrationCredentialsUpdate,
} from "@/lib/types";

export function useIntegrations() {
  return useQuery({
    queryKey: ["integrations"],
    queryFn: api.getIntegrations,
  });
}

export function useIntegrationTypes() {
  return useQuery({
    queryKey: ["integration-types"],
    queryFn: api.getIntegrationTypes,
  });
}

export function useIntegration(name: string | null) {
  return useQuery({
    queryKey: ["integration", name],
    queryFn: () => api.getIntegration(name as string),
    enabled: !!name,
  });
}

export function useCreateIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: IntegrationCreate) => api.createIntegration(data),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });
}

export function useUpdateIntegrationCredentials() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      data,
    }: {
      name: string;
      data: IntegrationCredentialsUpdate;
    }) => api.updateIntegrationCredentials(name, data),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      queryClient.invalidateQueries({ queryKey: ["integration", vars.name] });
    },
  });
}

export function useDeleteIntegration() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.deleteIntegration(name),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });
}
