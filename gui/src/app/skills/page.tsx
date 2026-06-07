"use client";

import { useState } from "react";
import { PageHeader } from "@/components/layout";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui";
import { SkillCard, SkillDetail, SkillCreateForm } from "@/components/skills";
import {
  useSkill,
  useSkills,
  useCreateSkill,
  useDeleteSkill,
  useInstallAgentSkill,
  useFleet,
} from "@/hooks";
import type { SkillSummary } from "@/lib/types";

export default function SkillsPage() {
  const { data: catalog, isLoading, error } = useSkills();
  const [selected, setSelected] = useState<SkillSummary | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const skills = catalog?.skills ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <PageHeader
          title="Skills"
          description="Browse and install skills onto your agents. Vetted skills ship in the repo; local skills are user-owned."
        />
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          + Create Skill
        </Button>
      </div>

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
          filesystem permission issue). Check the GUI server log for details.
        </div>
      ) : null}

      {isLoading ? (
        <div
          aria-live="polite"
          className="bg-surface rounded-xl border border-default p-8 text-center text-muted text-sm"
        >
          Loading skills catalog...
        </div>
      ) : skills.length > 0 ? (
        <div className="space-y-3">
          {skills.map((skill) => (
            <SkillCard
              key={skill.ref}
              skill={skill}
              onSelect={() => setSelected(skill)}
            />
          ))}
        </div>
      ) : (
        <EmptyState />
      )}

      <SkillDetailModal
        skill={selected}
        onClose={() => setSelected(null)}
      />

      <CreateSkillModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="bg-surface rounded-xl border border-default p-12 text-center space-y-2">
      <p className="text-sm text-primary-text font-medium">
        No skills in the catalog.
      </p>
      <p className="text-xs text-muted">
        Click <strong>+ Create Skill</strong> to author a local skill, or run{" "}
        <code className="bg-panel text-secondary px-1 py-0.5 rounded">
          clawctl skill add local/&lt;name&gt;
        </code>
        .
      </p>
    </div>
  );
}

function CreateSkillModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const createMutation = useCreateSkill();
  const errorMsg =
    createMutation.error instanceof Error
      ? createMutation.error.message
      : null;

  return (
    <Modal open={open} onClose={onClose} title="Create local skill">
      <SkillCreateForm
        isPending={createMutation.isPending}
        serverError={errorMsg}
        onCancel={onClose}
        onSubmit={(input) => {
          createMutation.mutate(input, {
            onSuccess: () => {
              createMutation.reset();
              onClose();
            },
          });
        }}
      />
    </Modal>
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
    skill?.source ?? null,
    skill?.name ?? null,
  );
  const { data: fleet } = useFleet();
  const installMutation = useInstallAgentSkill();
  const deleteMutation = useDeleteSkill();
  const [targetAgent, setTargetAgent] = useState<string>("");
  const [installSuccess, setInstallSuccess] = useState<string | null>(null);

  const agents = fleet?.agents ?? [];

  const handleInstall = () => {
    if (!targetAgent || !skill) return;
    setInstallSuccess(null);
    installMutation.mutate(
      { agentKey: targetAgent, source: skill.source, name: skill.name },
      {
        onSuccess: () => {
          setInstallSuccess(`Installed ${skill.ref} on ${targetAgent}`);
          setTargetAgent("");
        },
      },
    );
  };

  const handleDelete = () => {
    if (!skill || skill.source !== "local") return;
    deleteMutation.mutate(skill.name, {
      onSuccess: () => {
        onClose();
      },
    });
  };

  const isLocal = skill?.source === "local";

  const agentSupports = (agentType: string): boolean => {
    if (!data) return false;
    const flag = data.supported_on[agentType as keyof typeof data.supported_on];
    return Boolean(flag);
  };

  return (
    <Modal
      open={!!skill}
      onClose={() => {
        setInstallSuccess(null);
        setTargetAgent("");
        onClose();
      }}
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
        <>
          <SkillDetail skill={data} />

          <div className="mt-4 pt-4 border-t border-default">
            <h3 className="text-xs font-semibold text-primary-text mb-2">
              Install to Agent
            </h3>
            {agents.length === 0 ? (
              <p className="text-xs text-muted">
                No agents available. Create an agent first.
              </p>
            ) : (
              <div className="flex items-center gap-2">
                <select
                  value={targetAgent}
                  onChange={(e) => setTargetAgent(e.target.value)}
                  className="flex-1 text-sm border border-default rounded px-2 py-1.5 bg-surface text-primary-text"
                  aria-label="Select agent to install skill on"
                >
                  <option value="">Select an agent...</option>
                  {agents.map((agent) => {
                    const supported = agentSupports(agent.agent_type);
                    return (
                      <option
                        key={agent.agent_key}
                        value={agent.agent_key}
                        disabled={!supported}
                      >
                        {agent.agent_name} ({agent.agent_type})
                        {supported ? "" : " — not yet supported"}
                      </option>
                    );
                  })}
                </select>
                <Button
                  size="sm"
                  disabled={
                    !targetAgent ||
                    installMutation.isPending ||
                    !agentSupports(
                      agents.find((a) => a.agent_key === targetAgent)
                        ?.agent_type ?? "",
                    )
                  }
                  onClick={handleInstall}
                  title={
                    !targetAgent
                      ? "Select an agent"
                      : !agentSupports(
                          agents.find((a) => a.agent_key === targetAgent)
                            ?.agent_type ?? "",
                        )
                      ? "Not yet supported on this agent type"
                      : undefined
                  }
                >
                  {installMutation.isPending ? "Installing..." : "Install"}
                </Button>
              </div>
            )}
            {installSuccess ? (
              <p className="mt-2 text-xs text-emerald-600">{installSuccess}</p>
            ) : null}
            {installMutation.isError ? (
              <p className="mt-2 text-xs text-status-warning">
                Install failed:{" "}
                {installMutation.error instanceof Error
                  ? installMutation.error.message
                  : "Unknown error"}
              </p>
            ) : null}
          </div>

          {isLocal ? (
            <div className="mt-4 pt-4 border-t border-default flex items-center justify-between">
              <p className="text-xs text-muted">
                Local skills are user-owned and editable.
              </p>
              <Button
                size="sm"
                variant="ghost"
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending ? "Deleting…" : "Delete"}
              </Button>
            </div>
          ) : (
            <p className="mt-4 pt-4 border-t border-default text-xs text-muted">
              Vetted skills are read-only. Submit a PR to update them.
            </p>
          )}
        </>
      ) : null}
    </Modal>
  );
}
