"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import {
  useAgentSkills,
  useInstallAgentSkill,
  useRemoveAgentSkill,
} from "@/hooks";
import type { AgentSkillRow } from "@/lib/types";

interface SkillsTabProps {
  agentKey: string;
}

const REGISTRY_BADGES: Record<string, { label: string; color: string }> = {
  clawrium: { label: "CLW", color: "bg-blue-100 text-blue-700" },
  openclaw: { label: "OC", color: "bg-emerald-100 text-emerald-700" },
  hermes: { label: "HE", color: "bg-violet-100 text-violet-700" },
  zeroclaw: { label: "ZC", color: "bg-amber-100 text-amber-700" },
};

function RegistryBadge({ registry }: { registry: string | null }) {
  const badge = registry
    ? REGISTRY_BADGES[registry]
    : { label: "??", color: "bg-gray-100 text-gray-700" };
  const safe = badge ?? { label: "??", color: "bg-gray-100 text-gray-700" };
  return (
    <span
      className={`inline-flex items-center justify-center w-10 h-7 rounded text-[10px] font-bold ${safe.color}`}
    >
      {safe.label}
    </span>
  );
}

export function SkillsTab({ agentKey }: SkillsTabProps) {
  const { data, isLoading, error, refetch } = useAgentSkills(agentKey);
  const installMutation = useInstallAgentSkill();
  const removeMutation = useRemoveAgentSkill();

  const [pickerOpen, setPickerOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const installedRefs = useMemo(
    () => new Set((data?.installed ?? []).map((row) => row.ref)),
    [data?.installed],
  );

  const installable = useMemo(
    () =>
      (data?.available ?? []).filter((row) => !installedRefs.has(row.ref)),
    [data?.available, installedRefs],
  );

  // ATX-3 W1: the live region is rendered unconditionally at the
  // SkillsTab root so that the transition from loading → loaded shows
  // up as a DOM *mutation* (which is what NVDA / JAWS / VoiceOver
  // actually announce). When the load completes the text flips from
  // "Loading skills…" to "Skills loaded." once, then clears.
  const [justLoaded, setJustLoaded] = useState(false);
  const wasLoadingRef = useRef(isLoading);
  useEffect(() => {
    if (wasLoadingRef.current && !isLoading && !error) {
      setJustLoaded(true);
      const t = setTimeout(() => setJustLoaded(false), 1500);
      wasLoadingRef.current = false;
      return () => clearTimeout(t);
    }
    if (isLoading) wasLoadingRef.current = true;
  }, [isLoading, error]);

  const liveRegion = (
    <div
      // role=status implies aria-live=polite per WAI-ARIA §5.3.1, so
      // we don't set aria-live explicitly (ATX-3 W2). aria-busy
      // tracks the load state so ATs that honor it can suppress
      // partial reads of the subtree below.
      role="status"
      aria-busy={isLoading}
      aria-label="Skills tab status"
      className="sr-only"
    >
      {isLoading ? "Loading skills…" : justLoaded ? "Skills loaded." : ""}
    </div>
  );

  if (isLoading) {
    return (
      <div className="space-y-3 p-4" data-testid="skills-tab">
        {liveRegion}
        <div
          data-testid="skills-loading"
          aria-hidden="true"
          className="space-y-3"
        >
          <div className="bg-surface rounded-xl border border-default h-20 animate-pulse" />
          <div className="bg-surface rounded-xl border border-default h-20 animate-pulse" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-4" data-testid="skills-tab">
        {liveRegion}
        <Card padding="md">
          <p className="text-sm text-red-600">
            Failed to load skills for this agent.
          </p>
          <p className="mt-2 text-xs text-muted">
            {error instanceof Error ? error.message : "Unknown error."}
          </p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-3"
            onClick={() => refetch()}
          >
            Retry
          </Button>
        </Card>
      </div>
    );
  }

  const handleInstall = async (registry: string, name: string) => {
    setActionError(null);
    try {
      await installMutation.mutateAsync({ agentKey, registry, name });
      setPickerOpen(false);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Install failed");
    }
  };

  const handleRemove = async (registry: string, name: string) => {
    setActionError(null);
    try {
      await removeMutation.mutateAsync({ agentKey, registry, name });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Remove failed");
    }
  };

  return (
    <div className="space-y-6 p-4" data-testid="skills-tab">
      {liveRegion}
      {actionError ? (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {actionError}
        </div>
      ) : null}

      <Card padding="md">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-primary-text">
              Installed Skills
            </h3>
            <p className="mt-1 text-xs text-muted">
              Skills currently installed on{" "}
              <code className="bg-surface px-1 rounded">{data.agent_name}</code>{" "}
              ({data.agent_type}).
            </p>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setPickerOpen(true)}
            disabled={installable.length === 0}
          >
            Install skill
          </Button>
        </div>

        {data.installed.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted">
            No skills installed yet. Click{" "}
            <span className="font-medium">Install skill</span> to add one from
            the catalog.
          </div>
        ) : (
          <ul
            className="divide-y divide-default border border-default rounded-lg overflow-hidden"
            role="list"
            aria-label="Installed skills"
          >
            {data.installed.map((row) => (
              <InstalledRow
                key={row.ref}
                row={row}
                onRemove={handleRemove}
                disabled={removeMutation.isPending || installMutation.isPending}
              />
            ))}
          </ul>
        )}
      </Card>

      <Modal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title={`Install skill on ${data.agent_name}`}
        footer={
          <Button variant="secondary" onClick={() => setPickerOpen(false)}>
            Close
          </Button>
        }
      >
        <SkillPicker
          installable={installable}
          onPick={handleInstall}
          pending={installMutation.isPending}
        />
      </Modal>
    </div>
  );
}

function InstalledRow({
  row,
  onRemove,
  disabled,
}: {
  row: AgentSkillRow;
  onRemove: (registry: string, name: string) => void;
  disabled: boolean;
}) {
  // ATX-1 B2: remove is destructive (re-running install brings the host
  // back in sync, but the desired-state file is mutated immediately).
  // First click arms the confirm/cancel pair instead of firing the
  // mutation directly. Confirm button carries the skill ref in its
  // accessible name so a screen-reader scan can't conflate two rows.
  const [confirming, setConfirming] = useState(false);
  const canRemove = !!row.registry && !!row.name;
  // ATX-2 B2a: focus the Confirm button when the row enters the
  // confirming state — without this a keyboard user has no indication
  // that anything happened on the first click.
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (confirming) confirmRef.current?.focus();
  }, [confirming]);
  // ATX-2 W3: if a concurrent install/remove disables the row while a
  // confirm is open, drop back to the un-armed state so the user
  // doesn't see a stuck/disabled Confirm button.
  useEffect(() => {
    if (disabled && confirming) setConfirming(false);
  }, [disabled, confirming]);

  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <RegistryBadge registry={row.registry} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-primary-text">
            {row.ref}
          </span>
          {row.version ? (
            <span className="text-xs text-muted">v{row.version}</span>
          ) : null}
        </div>
        {row.description ? (
          <p className="mt-0.5 text-xs text-secondary line-clamp-2">
            {row.description}
          </p>
        ) : null}
      </div>
      {confirming ? (
        <div
          className="flex items-center gap-2"
          role="group"
          aria-label={`Confirm removal of ${row.ref}`}
          // ATX-2 B2b + ATX-3 W5: ARIA APG requires confirm patterns
          // to support Escape. The native <dialog> handles this for
          // the picker modal; this inline group needs an explicit
          // handler. preventDefault (not stopPropagation) — we're
          // saying "I handled this Escape" without silencing
          // ancestor JS listeners (toasts, command palettes, etc.).
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              setConfirming(false);
            }
          }}
        >
          <span className="text-xs text-secondary">Remove {row.ref}?</span>
          <Button
            ref={confirmRef}
            variant="danger"
            size="sm"
            // S4: confirming is cleared SYNCHRONOUSLY here (before
            // the async mutation fires), so an Escape key arriving
            // mid-mutation cannot race the removal — the group is
            // already gone. Don't move this to onSettled / onSuccess.
            onClick={() => {
              if (canRemove) {
                setConfirming(false);
                onRemove(row.registry!, row.name!);
              }
            }}
            disabled={disabled || !canRemove}
            aria-label={`Confirm remove ${row.ref}`}
          >
            Confirm
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setConfirming(false)}
            aria-label={`Cancel remove ${row.ref}`}
          >
            Cancel
          </Button>
        </div>
      ) : (
        <Button
          variant="danger"
          size="sm"
          onClick={() => setConfirming(true)}
          disabled={disabled || !canRemove}
          aria-label={`Remove ${row.ref}`}
        >
          Remove
        </Button>
      )}
    </li>
  );
}

function SkillPicker({
  installable,
  onPick,
  pending,
}: {
  installable: AgentSkillRow[];
  onPick: (registry: string, name: string) => void;
  pending: boolean;
}) {
  if (installable.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted">
        No compatible skills available to install. Add one to{" "}
        <code className="bg-surface px-1 rounded">skills/clawrium/</code> or{" "}
        the matching native registry, then refresh.
      </p>
    );
  }
  return (
    <ul
      className="divide-y divide-default border border-default rounded-lg overflow-hidden"
      role="list"
      aria-label="Compatible skills"
    >
      {installable.map((row) => (
        <li
          key={row.ref}
          className="flex items-start gap-3 px-4 py-3"
        >
          <RegistryBadge registry={row.registry} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium text-primary-text">
                {row.ref}
              </span>
              {row.version ? (
                <span className="text-xs text-muted">v{row.version}</span>
              ) : null}
            </div>
            {row.description ? (
              <p className="mt-0.5 text-xs text-secondary line-clamp-2">
                {row.description}
              </p>
            ) : null}
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => row.registry && row.name && onPick(row.registry, row.name)}
            disabled={pending || !row.registry || !row.name}
            aria-label={`Install ${row.ref}`}
          >
            Install
          </Button>
        </li>
      ))}
    </ul>
  );
}
