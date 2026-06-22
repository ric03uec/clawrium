"use client";

import { useState } from "react";
import { PageHeader } from "@/components/layout";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import {
  AddIntegrationModal,
  EditCredentialsModal,
  IntegrationCard,
} from "@/components/integrations";
import {
  useCreateIntegration,
  useDeleteIntegration,
  useIntegration,
  useIntegrationTypes,
  useIntegrations,
  useUpdateIntegrationCredentials,
} from "@/hooks";
import type {
  Integration,
  IntegrationCreate,
  IntegrationCredentialsUpdate,
} from "@/lib/types";

export default function IntegrationsPage() {
  const { data: integrations, isLoading } = useIntegrations();
  const { data: integrationTypes } = useIntegrationTypes();
  const createMutation = useCreateIntegration();
  const deleteMutation = useDeleteIntegration();
  const updateMutation = useUpdateIntegrationCredentials();

  const [showAdd, setShowAdd] = useState(false);
  const [editTarget, setEditTarget] = useState<Integration | null>(null);
  const [removeTarget, setRemoveTarget] = useState<Integration | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  // Pull detail (agents_using) for the row being removed so the
  // confirmation modal can show the blocking references.
  const { data: removeDetail, isLoading: removeDetailLoading } = useIntegration(
    removeTarget?.name ?? null,
  );

  function handleCreate(data: IntegrationCreate) {
    setAddError(null);
    createMutation.mutate(data, {
      onSuccess: () => setShowAdd(false),
      onError: (err) => {
        setAddError(err instanceof Error ? err.message : "Failed to add");
      },
    });
  }

  function handleUpdate(data: IntegrationCredentialsUpdate) {
    if (!editTarget) return;
    updateMutation.mutate(
      { name: editTarget.name, data },
      { onSuccess: () => setEditTarget(null) },
    );
  }

  function handleDelete() {
    if (!removeTarget) return;
    setRemoveError(null);
    deleteMutation.mutate(removeTarget.name, {
      onSuccess: () => setRemoveTarget(null),
      onError: (err) => {
        setRemoveError(
          err instanceof Error
            ? err.message
            : "Failed to remove integration",
        );
      },
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Integrations"
        description="Connect external services once, share them across your fleet. Agents inherit credentials automatically."
      />

      {isLoading ? (
        <div className="bg-surface rounded-xl border border-default p-8 text-center text-muted text-sm">
          Loading integrations...
        </div>
      ) : integrations && integrations.length > 0 ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-primary-text">
              Configured Integrations ({integrations.length})
            </h2>
            <Button variant="primary" onClick={() => setShowAdd(true)}>
              + Add Integration
            </Button>
          </div>
          {integrations.map((i) => (
            <IntegrationCard
              key={i.name}
              integration={i}
              agentsUsing={i.agent_count}
              onEdit={() => setEditTarget(i)}
              onRemove={() => {
                setRemoveError(null);
                setRemoveTarget(i);
              }}
            />
          ))}
        </div>
      ) : (
        <div className="bg-surface rounded-xl border border-default p-12 text-center space-y-3">
          <p className="text-sm text-primary-text font-medium">
            No integrations configured yet.
          </p>
          <p className="text-xs text-muted">
            Connect GitHub, GitLab, Atlassian, Linear, or Notion — then
            assign them to any agent in your fleet.
          </p>
          <Button variant="primary" onClick={() => setShowAdd(true)}>
            + Add your first integration
          </Button>
        </div>
      )}

      {integrationTypes && (
        <AddIntegrationModal
          open={showAdd}
          onClose={() => {
            setShowAdd(false);
            setAddError(null);
          }}
          onSave={handleCreate}
          integrationTypes={integrationTypes}
          saving={createMutation.isPending}
          error={addError}
        />
      )}

      {editTarget && integrationTypes && (
        <EditCredentialsModal
          open={!!editTarget}
          onClose={() => setEditTarget(null)}
          onSave={handleUpdate}
          integration={editTarget}
          integrationTypes={integrationTypes}
          saving={updateMutation.isPending}
        />
      )}

      <Modal
        open={!!removeTarget}
        onClose={() => {
          setRemoveTarget(null);
          setRemoveError(null);
        }}
        title="Remove Integration"
      >
        <div className="space-y-4">
          <p className="text-sm text-secondary">
            Are you sure you want to remove{" "}
            <strong>{removeTarget?.name}</strong>? This will also delete its
            stored credentials.
          </p>
          {removeDetail && removeDetail.agents_using.length > 0 ? (
            <div className="rounded border border-default bg-panel p-3 text-xs text-secondary">
              <p className="font-medium text-status-warning mb-1">
                In use by {removeDetail.agents_using.length} agent
                {removeDetail.agents_using.length === 1 ? "" : "s"}:
              </p>
              <ul className="list-disc list-inside">
                {removeDetail.agents_using.map((a) => (
                  <li key={`${a.hostname}:${a.agent_key}`}>
                    <code>{a.hostname}</code>:<code>{a.agent_key}</code>
                  </li>
                ))}
              </ul>
              <p className="mt-2">
                Remove the assignment from those agents first.
              </p>
            </div>
          ) : null}
          {removeError ? (
            <p className="text-xs text-status-warning">{removeError}</p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                setRemoveTarget(null);
                setRemoveError(null);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleDelete}
              disabled={deleteMutation.isPending || removeDetailLoading}
            >
              {deleteMutation.isPending
                ? "Removing..."
                : removeDetailLoading
                  ? "Checking..."
                  : "Remove"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
