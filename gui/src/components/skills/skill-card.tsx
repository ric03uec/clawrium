"use client";

import type { SkillSummary } from "@/lib/types";
import { Card } from "@/components/ui/card";

const SOURCE_BADGE: Record<string, { label: string; color: string }> = {
  vetted: { label: "vetted", color: "bg-blue-100 text-blue-700" },
  local: { label: "local", color: "bg-emerald-100 text-emerald-700" },
};

interface SkillCardProps {
  skill: SkillSummary;
  onSelect: () => void;
}

export function SkillCard({ skill, onSelect }: SkillCardProps) {
  const sourceBadge = SOURCE_BADGE[skill.source] ?? {
    label: skill.source,
    color: "bg-gray-100 text-gray-700",
  };

  const supportedClaws = Object.entries(skill.supported_on ?? {})
    .filter(([, ok]) => ok)
    .map(([claw]) => claw);

  return (
    <Card padding="md">
      <button
        type="button"
        onClick={onSelect}
        className="flex items-start gap-4 w-full text-left"
        aria-label={`View skill ${skill.ref}`}
      >
        <div
          className={`px-2 py-1 rounded text-xs font-semibold uppercase ${sourceBadge.color}`}
          aria-label={`Source ${sourceBadge.label}`}
        >
          {sourceBadge.label}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-primary-text">
              {skill.ref}
            </h3>
            {skill.version ? (
              <span className="text-xs text-muted">v{skill.version}</span>
            ) : null}
            {skill.degraded ? (
              <span
                aria-label="metadata failed to load"
                title="Metadata failed to load — check the server log"
                className="text-xs px-1 py-0.5 rounded bg-amber-100 text-amber-700"
              >
                !
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-secondary line-clamp-2">
            {skill.description ?? (
              <span className="text-muted italic">
                {skill.degraded
                  ? "Failed to load skill metadata"
                  : "No description available"}
              </span>
            )}
          </p>
          {supportedClaws.length > 0 ? (
            <p className="mt-1 text-xs text-muted">
              Supported on: {supportedClaws.join(", ")}
            </p>
          ) : null}
        </div>
      </button>
    </Card>
  );
}
