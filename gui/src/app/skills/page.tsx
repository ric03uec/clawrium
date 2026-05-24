"use client";

import { useMemo, useState } from "react";
import { PageHeader } from "@/components/layout";
import { Modal } from "@/components/ui/modal";
import { SkillCard, SkillDetail } from "@/components/skills";
import { useSkill, useSkills } from "@/hooks";
import type { SkillRegistry, SkillSummary } from "@/lib/types";

const REGISTRY_LABELS: Record<SkillRegistry, string> = {
  clawrium: "Clawrium",
  openclaw: "OpenClaw",
  hermes: "Hermes",
  zeroclaw: "ZeroClaw",
};

export default function SkillsPage() {
  const { data: catalog, isLoading, error } = useSkills();
  const [activeRegistry, setActiveRegistry] = useState<SkillRegistry>(
    "clawrium",
  );
  const [selected, setSelected] = useState<SkillSummary | null>(null);

  const counts = useMemo(() => {
    if (!catalog) return {} as Record<SkillRegistry, number>;
    return Object.fromEntries(
      Object.entries(catalog.skills).map(([registry, list]) => [
        registry,
        list.length,
      ]),
    ) as Record<SkillRegistry, number>;
  }, [catalog]);

  const visibleSkills = catalog?.skills[activeRegistry] ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Skills"
        description="Browse the clawrium-managed skills catalog. Install from the CLI: clawctl agent skill attach <registry>/<name> --agent <agent>."
      />

      {error ? (
        <div
          role="alert"
          className="bg-surface rounded-xl border border-default p-6 text-sm text-status-warning"
        >
          Failed to load skills catalog:{" "}
          {error instanceof Error ? error.message : String(error)}
        </div>
      ) : null}

      {catalog?.error ? (
        <div
          role="alert"
          className="bg-surface rounded-xl border border-default p-4 text-sm text-status-warning"
        >
          Skills catalog is currently unavailable on the server (likely a
          filesystem permission issue). Showing empty tabs as a fallback —
          check the GUI server log for details.
        </div>
      ) : null}

      {isLoading ? (
        <div
          aria-live="polite"
          className="bg-surface rounded-xl border border-default p-8 text-center text-muted text-sm"
        >
          Loading skills catalog...
        </div>
      ) : catalog ? (
        <>
          {/* `role="group"` instead of `<nav>` because these buttons
              filter the page's already-loaded data, they do not
              navigate to new URLs. Using <nav> pollutes the landmark
              menu for AT users with what looks like a navigation
              region. APG's full Tabs Pattern (tablist + tabpanel +
              arrow-key roving tabindex) would also work, but is heavy
              for an in-page filter; `role="group"` carries the same
              semantic intent without the keyboard contract. */}
          <div
            role="group"
            aria-label="Skill registries"
            className="flex gap-1 border-b border-default"
          >
            {catalog.registries.map((registry) => {
              const isActive = registry === activeRegistry;
              const count = counts[registry] ?? 0;
              const label = REGISTRY_LABELS[registry] ?? registry;
              return (
                <button
                  key={registry}
                  type="button"
                  // `aria-current="true"` is the right WAI-ARIA token
                  // for "this filter is selected"; `"page"` is reserved
                  // for routing (selected nav item that matches the
                  // current URL).
                  aria-current={isActive ? "true" : undefined}
                  // Use a comma rather than an em-dash — most screen
                  // readers verbalize U+2014 as "em dash" instead of
                  // pausing, which mangles the spoken count phrasing.
                  aria-label={`${label}, ${count} skill${
                    count === 1 ? "" : "s"
                  }`}
                  onClick={() => setActiveRegistry(registry)}
                  className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                    isActive
                      ? "border-primary text-primary"
                      : "border-transparent text-secondary hover:text-primary"
                  }`}
                >
                  {label}
                  <span aria-hidden="true" className="ml-2 text-xs text-muted">
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          {visibleSkills.length > 0 ? (
            <div className="space-y-3">
              {visibleSkills.map((skill) => (
                <SkillCard
                  key={skill.ref}
                  skill={skill}
                  onSelect={() => setSelected(skill)}
                />
              ))}
            </div>
          ) : (
            <EmptyState registry={activeRegistry} />
          )}
        </>
      ) : null}

      <SkillDetailModal
        skill={selected}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}

function EmptyState({ registry }: { registry: SkillRegistry }) {
  return (
    <div className="bg-surface rounded-xl border border-default p-12 text-center space-y-2">
      <p className="text-sm text-primary-text font-medium">
        No skills registered under{" "}
        <code className="bg-panel text-secondary px-1 py-0.5 rounded">
          {registry}/
        </code>
      </p>
      <p className="text-xs text-muted">
        Add one under{" "}
        <code className="bg-panel text-secondary px-1 py-0.5 rounded">
          skills/{registry}/&lt;name&gt;/
        </code>{" "}
        in the clawrium repo.
      </p>
    </div>
  );
}

function SkillDetailModal({
  skill,
  onClose,
}: {
  skill: SkillSummary | null;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useSkill(
    skill?.registry ?? null,
    skill?.name ?? null,
  );

  return (
    <Modal
      open={!!skill}
      onClose={onClose}
      title={skill ? skill.ref : "Skill detail"}
    >
      {isLoading ? (
        <div
          aria-live="polite"
          className="text-sm text-muted py-6 text-center"
        >
          Loading...
        </div>
      ) : error ? (
        <div role="alert" className="text-sm text-status-warning py-6">
          Failed to load skill:{" "}
          {error instanceof Error ? error.message : String(error)}
        </div>
      ) : data ? (
        <SkillDetail skill={data} />
      ) : null}
    </Modal>
  );
}
