"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import {
  useAgentSkills,
  useInstallAgentSkill,
  useRemoveAgentSkill,
  useAddAgentSkill,
  useEditAgentSkill,
  useRemoveLocalAgentSkill,
} from "@/hooks";
import type { AgentSkillRow, SkillOrigin } from "@/lib/types";

interface SkillsTabProps {
  agentKey: string;
}

const REGISTRY_BADGES: Record<string, { label: string; color: string }> = {
  clawrium: { label: "CLW", color: "bg-blue-100 text-blue-700" },
  openclaw: { label: "OC", color: "bg-emerald-100 text-emerald-700" },
  hermes: { label: "HE", color: "bg-violet-100 text-violet-700" },
  zeroclaw: { label: "ZC", color: "bg-amber-100 text-amber-700" },
};

const ORIGIN_CHIPS: Record<SkillOrigin, { label: string; color: string }> = {
  local: { label: "LOCAL", color: "bg-gray-100 text-gray-600" },
  bundled: { label: "BUNDLED", color: "bg-blue-50 text-blue-600" },
  overlay: { label: "OVERLAY", color: "bg-purple-50 text-purple-600" },
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

function OriginChip({ origin }: { origin?: SkillOrigin }) {
  const chip = origin ? ORIGIN_CHIPS[origin] : ORIGIN_CHIPS.local;
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide ${chip.color}`}
    >
      {chip.label}
    </span>
  );
}

type AddTab = "template" | "file" | "inline";

function AddSkillModal({
  open,
  onClose,
  agentKey,
  agentName,
  agentType,
  installable,
  installMutation,
  addMutation,
}: {
  open: boolean;
  onClose: () => void;
  agentKey: string;
  agentName: string;
  agentType: string;
  installable: AgentSkillRow[];
  installMutation: ReturnType<typeof useInstallAgentSkill>;
  addMutation: ReturnType<typeof useAddAgentSkill>;
}) {
  const [tab, setTab] = useState<AddTab>("template");
  const [fileContent, setFileContent] = useState("");
  const [inlineName, setInlineName] = useState("");
  const [inlineDesc, setInlineDesc] = useState("");
  const [inlineBody, setInlineBody] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const isPending = installMutation.isPending || addMutation.isPending;

  const handleClose = () => {
    setTab("template");
    setFileContent("");
    setInlineName("");
    setInlineDesc("");
    setInlineBody("");
    setLocalError(null);
    onClose();
  };

  const handleInstallTemplate = async (registry: string, name: string) => {
    setLocalError(null);
    try {
      await installMutation.mutateAsync({ agentKey, registry, name });
      handleClose();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Install failed");
    }
  };

  const handleAddFile = async () => {
    setLocalError(null);
    if (!fileContent.trim()) {
      setLocalError("Paste the SKILL.md content above.");
      return;
    }
    try {
      await addMutation.mutateAsync({
        agentKey,
        payload: { input_mode: "file", content: fileContent },
      });
      handleClose();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Add failed");
    }
  };

  const handleAddInline = async () => {
    setLocalError(null);
    if (!inlineName.trim()) {
      setLocalError("Skill name is required.");
      return;
    }
    try {
      await addMutation.mutateAsync({
        agentKey,
        payload: {
          input_mode: "inline",
          name: inlineName.trim(),
          description: inlineDesc.trim(),
          body: inlineBody,
        },
      });
      handleClose();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Add failed");
    }
  };

  const TABS: { id: AddTab; label: string }[] = [
    { id: "template", label: "From catalog" },
    { id: "file", label: "From file" },
    { id: "inline", label: "Inline" },
  ];

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={`Add skill to ${agentName}`}
      footer={
        <div className="flex items-center justify-between w-full">
          <p className="text-xs text-muted">
            Run{" "}
            <code className="bg-surface px-1 rounded">
              clawctl agent sync {agentKey}
            </code>{" "}
            to apply.
          </p>
          <Button variant="secondary" onClick={handleClose}>
            Close
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {localError ? (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {localError}
          </div>
        ) : null}

        <div
          className="flex border-b border-default"
          role="tablist"
          aria-label="Add skill mode"
        >
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => {
                setTab(t.id);
                setLocalError(null);
              }}
              className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t.id
                  ? "border-accent text-accent"
                  : "border-transparent text-muted hover:text-primary-text"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "template" && (
          <SkillPicker
            installable={installable}
            onPick={handleInstallTemplate}
            pending={isPending}
          />
        )}

        {tab === "file" && (
          <div className="space-y-3">
            <p className="text-xs text-muted">
              Paste the full contents of a{" "}
              <code className="bg-surface px-1 rounded">SKILL.md</code> file.
              The skill name is read from the frontmatter{" "}
              <code className="bg-surface px-1 rounded">name:</code> field.
            </p>
            <textarea
              className="w-full h-48 rounded-lg border border-default bg-surface p-3 text-sm font-mono text-primary-text resize-y focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="---&#10;name: my-skill&#10;description: What this skill does&#10;---&#10;&#10;# My Skill&#10;..."
              value={fileContent}
              onChange={(e) => setFileContent(e.target.value)}
              aria-label="SKILL.md content"
            />
            <Button
              variant="primary"
              size="sm"
              onClick={handleAddFile}
              disabled={isPending || !fileContent.trim()}
            >
              {isPending ? "Adding…" : "Add skill"}
            </Button>
          </div>
        )}

        {tab === "inline" && (
          <div className="space-y-3">
            <p className="text-xs text-muted">
              Create a new skill directly. The skill targets{" "}
              <strong>{agentType}</strong>. Sync to deploy to the agent host.
            </p>
            <div>
              <label
                className="block text-xs font-medium text-secondary mb-1"
                htmlFor="inline-name"
              >
                Name <span className="text-red-500">*</span>
              </label>
              <input
                id="inline-name"
                type="text"
                className="w-full rounded-lg border border-default bg-surface px-3 py-2 text-sm text-primary-text focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder="my-skill"
                value={inlineName}
                onChange={(e) => setInlineName(e.target.value)}
              />
            </div>
            <div>
              <label
                className="block text-xs font-medium text-secondary mb-1"
                htmlFor="inline-desc"
              >
                Description
              </label>
              <input
                id="inline-desc"
                type="text"
                className="w-full rounded-lg border border-default bg-surface px-3 py-2 text-sm text-primary-text focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder="What this skill does"
                value={inlineDesc}
                onChange={(e) => setInlineDesc(e.target.value)}
              />
            </div>
            <div>
              <label
                className="block text-xs font-medium text-secondary mb-1"
                htmlFor="inline-body"
              >
                Skill body (markdown)
              </label>
              <textarea
                id="inline-body"
                className="w-full h-32 rounded-lg border border-default bg-surface p-3 text-sm font-mono text-primary-text resize-y focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder="# My Skill&#10;&#10;Instructions for the agent..."
                value={inlineBody}
                onChange={(e) => setInlineBody(e.target.value)}
              />
            </div>
            <Button
              variant="primary"
              size="sm"
              onClick={handleAddInline}
              disabled={isPending || !inlineName.trim()}
            >
              {isPending ? "Adding…" : "Add skill"}
            </Button>
          </div>
        )}
      </div>
    </Modal>
  );
}

function EditSkillModal({
  open,
  skillName,
  initialContent,
  agentKey,
  onClose,
  editMutation,
}: {
  open: boolean;
  skillName: string;
  initialContent: string;
  agentKey: string;
  onClose: () => void;
  editMutation: ReturnType<typeof useEditAgentSkill>;
}) {
  const [content, setContent] = useState(initialContent);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setContent(initialContent);
      setLocalError(null);
    }
  }, [open, initialContent]);

  const handleSave = async () => {
    setLocalError(null);
    try {
      await editMutation.mutateAsync({ agentKey, name: skillName, content });
      onClose();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Save failed");
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Edit skill: ${skillName}`}
      footer={
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={handleSave}
            disabled={editMutation.isPending}
          >
            {editMutation.isPending ? "Saving…" : "Save"}
          </Button>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        {localError ? (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {localError}
          </div>
        ) : null}
        <p className="text-xs text-muted">
          Edit the raw <code className="bg-surface px-1 rounded">SKILL.md</code>{" "}
          content. Run{" "}
          <code className="bg-surface px-1 rounded">
            clawctl agent sync {agentKey}
          </code>{" "}
          to apply changes on the host.
        </p>
        <textarea
          className="w-full h-64 rounded-lg border border-default bg-surface p-3 text-sm font-mono text-primary-text resize-y focus:outline-none focus:ring-2 focus:ring-accent"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          aria-label="SKILL.md content"
        />
      </div>
    </Modal>
  );
}

export function SkillsTab({ agentKey }: SkillsTabProps) {
  const { data, isLoading, error, refetch } = useAgentSkills(agentKey);
  const installMutation = useInstallAgentSkill();
  const removeMutation = useRemoveAgentSkill();
  const addMutation = useAddAgentSkill();
  const editMutation = useEditAgentSkill();
  const removeLocalMutation = useRemoveLocalAgentSkill();

  const [addOpen, setAddOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<AgentSkillRow | null>(null);
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

  const anyPending =
    removeMutation.isPending ||
    installMutation.isPending ||
    addMutation.isPending ||
    removeLocalMutation.isPending;

  const handleRemoveCatalog = async (registry: string, name: string) => {
    setActionError(null);
    try {
      await removeMutation.mutateAsync({ agentKey, registry, name });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Remove failed");
    }
  };

  const handleRemoveLocal = async (name: string) => {
    setActionError(null);
    try {
      await removeLocalMutation.mutateAsync({ agentKey, name });
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
            onClick={() => setAddOpen(true)}
          >
            Add skill
          </Button>
        </div>

        {data.installed.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted">
            No skills installed yet. Click{" "}
            <span className="font-medium">Add skill</span> to add one.
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
                onRemoveCatalog={handleRemoveCatalog}
                onRemoveLocal={handleRemoveLocal}
                onEdit={() => setEditingSkill(row)}
                disabled={anyPending}
              />
            ))}
          </ul>
        )}
      </Card>

      <AddSkillModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        agentKey={agentKey}
        agentName={data.agent_name}
        agentType={data.agent_type}
        installable={installable}
        installMutation={installMutation}
        addMutation={addMutation}
      />

      {editingSkill?.name ? (
        <EditSkillModal
          open={!!editingSkill}
          skillName={editingSkill.name}
          initialContent={`---\nname: ${editingSkill.name}\ndescription: ${editingSkill.description ?? ""}\n---\n\n`}
          agentKey={agentKey}
          onClose={() => setEditingSkill(null)}
          editMutation={editMutation}
        />
      ) : null}
    </div>
  );
}

function InstalledRow({
  row,
  onRemoveCatalog,
  onRemoveLocal,
  onEdit,
  disabled,
}: {
  row: AgentSkillRow;
  onRemoveCatalog: (registry: string, name: string) => void;
  onRemoveLocal: (name: string) => void;
  onEdit: () => void;
  disabled: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const isLocal = row.origin === "local" || !row.registry;
  const canRemove = isLocal ? !!row.name : !!row.registry && !!row.name;

  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (confirming) confirmRef.current?.focus();
  }, [confirming]);
  useEffect(() => {
    if (disabled && confirming) setConfirming(false);
  }, [disabled, confirming]);

  const handleConfirmRemove = () => {
    if (!canRemove) return;
    setConfirming(false);
    if (isLocal) {
      onRemoveLocal(row.name!);
    } else {
      onRemoveCatalog(row.registry!, row.name!);
    }
  };

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
          <OriginChip origin={row.origin} />
        </div>
        {row.description ? (
          <p className="mt-0.5 text-xs text-secondary line-clamp-2">
            {row.description}
          </p>
        ) : null}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {isLocal && !confirming ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={onEdit}
            disabled={disabled}
            aria-label={`Edit ${row.ref}`}
          >
            Edit
          </Button>
        ) : null}
        {confirming ? (
          <div
            className="flex items-center gap-2"
            role="group"
            aria-label={`Confirm removal of ${row.ref}`}
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
              onClick={handleConfirmRemove}
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
      </div>
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
