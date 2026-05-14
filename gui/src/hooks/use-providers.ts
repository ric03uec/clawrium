import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ProviderCreate, ProviderUpdate } from "@/lib/types";

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: api.getProviders,
  });
}

export function useProviderTypes() {
  return useQuery({
    queryKey: ["provider-types"],
    queryFn: api.getProviderTypes,
  });
}

export function useModelCatalog(provider?: string, search?: string) {
  return useQuery({
    queryKey: ["model-catalog", provider, search],
    queryFn: () => api.getModelCatalog(provider, search),
  });
}

export function useCreateProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ProviderCreate) => api.createProvider(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["providers"] }),
  });
}

export function useUpdateProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, data }: { name: string; data: ProviderUpdate }) =>
      api.updateProvider(name, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["providers"] }),
  });
}

export function useDeleteProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.deleteProvider(name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["providers"] }),
  });
}
