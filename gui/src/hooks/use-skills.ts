import { useQuery } from "@tanstack/react-query";
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
