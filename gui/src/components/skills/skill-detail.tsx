"use client";

import type { SkillCompatibility, SkillDetail as SkillDetailData } from "@/lib/types";

interface SkillDetailProps {
  skill: SkillDetailData;
}

export function SkillDetail({ skill }: SkillDetailProps) {
  const description =
    typeof skill.metadata.description === "string"
      ? skill.metadata.description
      : null;
  const version =
    typeof skill.metadata.version === "string"
      ? skill.metadata.version
      : skill.metadata.version != null
        ? String(skill.metadata.version)
        : null;
  const license =
    typeof skill.metadata.license === "string" ? skill.metadata.license : null;
  const author =
    typeof skill.metadata.author === "string" ? skill.metadata.author : null;
  const platforms = Array.isArray(skill.metadata.platforms)
    ? (skill.metadata.platforms as unknown[])
        .filter((p): p is string => typeof p === "string")
    : [];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-primary-text">
          {skill.ref}
        </h2>
        {description ? (
          <p className="mt-1 text-sm text-secondary">{description}</p>
        ) : null}
      </div>

      <div className="rounded border border-default bg-panel p-3 text-xs text-secondary">
        <h3 className="font-medium text-primary-text mb-2 text-xs">Metadata</h3>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-muted">registry</dt>
          <dd>
            <code>{skill.registry}</code>
          </dd>
          <dt className="text-muted">name</dt>
          <dd>
            <code>{skill.name}</code>
          </dd>
          {version ? (
            <>
              <dt className="text-muted">version</dt>
              <dd>{version}</dd>
            </>
          ) : null}
          {license ? (
            <>
              <dt className="text-muted">license</dt>
              <dd>{license}</dd>
            </>
          ) : null}
          {author ? (
            <>
              <dt className="text-muted">author</dt>
              <dd>{author}</dd>
            </>
          ) : null}
          {platforms.length > 0 ? (
            <>
              <dt className="text-muted">platforms</dt>
              <dd>{platforms.join(", ")}</dd>
            </>
          ) : null}
          <dt className="text-muted">compatibility</dt>
          <dd>
            <CompatibilityBadges compatibility={skill.compatibility} />
          </dd>
        </dl>
      </div>

      {skill.body.trim() ? (
        <div className="rounded border border-default p-3">
          <h3 className="font-medium text-primary-text mb-2 text-xs">
            SKILL.md
          </h3>
          {/* `tabIndex={0}` makes the scrollable body reachable via
              keyboard (WCAG 2.1.1 Level A). Without it, keyboard-only
              users can't scroll the body when it overflows max-h-96. */}
          <pre
            tabIndex={0}
            aria-label="SKILL.md body, scrollable"
            className="text-xs text-secondary whitespace-pre-wrap font-mono max-h-96 overflow-auto focus:outline-none focus:ring-2 focus:ring-primary"
          >
            {skill.body}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

function CompatibilityBadges({
  compatibility,
}: {
  compatibility: SkillCompatibility;
}) {
  const entries = (Object.entries(compatibility) as [
    keyof SkillCompatibility,
    boolean,
  ][]).sort(([a], [b]) => a.localeCompare(b));
  return (
    <span className="flex flex-wrap gap-1">
      {entries.map(([claw, ok]) => (
        <span
          key={claw}
          // line-through carries the same signal as the aria-label so
          // sighted and screen-reader users agree on compatibility.
          // WCAG 1.4.1 — never rely on visual presentation alone.
          // Comma rather than em-dash: NVDA/JAWS verbalize U+2014 as
          // "em dash" instead of a natural pause.
          aria-label={ok ? `${claw}, compatible` : `${claw}, incompatible`}
          className={`px-1.5 py-0.5 rounded text-xs ${
            ok
              ? "bg-emerald-50 text-emerald-700"
              : "bg-gray-100 text-gray-500 line-through"
          }`}
        >
          {claw}
        </span>
      ))}
    </span>
  );
}
