"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Button, DataTable, PageHeader } from "@/design-system";
import { Modal } from "@/components/ui/modal";
import {
  AddIntegrationModal,
  EditCredentialsModal,
  IntegrationIcon,
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

function credentialsConfigured(integration: Integration): boolean {
  return (
    integration.credential_keys.length > 0 &&
    integration.credential_keys.every((key) =>
      integration.configured_credential_keys.includes(key),
    )
  );
}

function agentCountLabel(count: number): string {
  if (count === 0) return "No agents";
  return `${count} agent${count === 1 ? "" : "s"}`;
}

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

  const columns = useMemo<ColumnDef<Integration, unknown>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Integration",
        cell: ({ row }) => (
          <button
            type="button"
            className="flex min-w-48 items-center gap-3 text-left hover:underline"
            aria-label={`Edit credentials for ${row.original.name}`}
            onClick={() => setEditTarget(row.original)}
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-default bg-white">
              <IntegrationIcon type={row.original.type} size={22} />
            </span>
            <span className="font-medium text-primary-foreground">
              {row.original.name}
            </span>
          </button>
        ),
      },
      {
        accessorKey: "type",
        header: "Type",
        cell: ({ getValue }) => (
          <span className="text-xs uppercase text-secondary">
            {getValue<string>()}
          </span>
        ),
      },
      {
        id: "credentialStatus",
        accessorFn: (integration) =>
          credentialsConfigured(integration)
            ? "credentials configured"
            : "credentials incomplete",
        header: "Credential status",
        cell: ({ row }) => {
          const integration = row.original;
          const configured = credentialsConfigured(integration);
          return (
            <div className="space-y-0.5">
              <span
                className={
                  configured ? "text-status-running-text" : "text-status-warning-text"
                }
              >
                {configured
                  ? "Credentials configured"
                  : "Credentials incomplete"}
              </span>
              <p className="text-xs text-muted">
                {integration.configured_credential_keys.length}/
                {integration.credential_keys.length} set
              </p>
            </div>
          );
        },
      },
      {
        accessorKey: "agent_count",
        header: "Agents using",
        cell: ({ getValue }) => (
          <span className="text-secondary">
            {agentCountLabel(getValue<number>())}
          </span>
        ),
      },
      {
        id: "actions",
        header: "Actions",
        enableSorting: false,
        meta: { align: "right" },
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <Button
              trackingId="integrations.table.edit"
              variant="ghost"
              size="sm"
              onClick={() => setEditTarget(row.original)}
            >
              Edit credentials
            </Button>
            <Button
              trackingId="integrations.table.remove"
              variant="ghost"
              size="sm"
              onClick={() => {
                setRemoveError(null);
                setRemoveTarget(row.original);
              }}
            >
              Remove
            </Button>
          </div>
        ),
      },
    ],
    [],
  );

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

  const addButton = (
    <Button
      trackingId="integrations.page.add"
      variant="primary"
      onClick={() => setShowAdd(true)}
    >
      + Add Integration
    </Button>
  );

  return (
    <div className="space-y-6">
      <PageHeader
        trackingId="integrations.page.header"
        eyebrow="Connections"
        title="Integrations"
        description="Connect external services once, share them across your fleet. Agents inherit credentials automatically."
      />

      {isLoading ? (
        <DataTable
          trackingId="integrations.configured.table"
          title="Configured Integrations"
          columns={columns}
          data={[]}
          getRowId={(integration) => integration.name}
          itemLabel="integration"
          isLoading
          loadingMessage="Loading integrations..."
          enablePagination={false}
        />
      ) : integrations && integrations.length > 0 ? (
        <DataTable
          trackingId="integrations.configured.table"
          title="Configured Integrations"
          columns={columns}
          data={integrations}
          getRowId={(integration) => integration.name}
          itemLabel="integration"
          searchPlaceholder="Search integrations..."
          noResultsMessage="No integrations match your search."
          headerActions={addButton}
          enablePagination={false}
        />
      ) : (
        <div className="bg-surface rounded-xl border border-default p-12 text-center space-y-3">
          <p className="text-sm text-primary-text font-medium">
            No integrations configured yet.
          </p>
          <p className="text-xs text-muted">
            Connect GitHub, GitLab, Atlassian, Linear, or Notion — then
            assign them to any agent in your fleet.
          </p>
          <Button
            trackingId="integrations.page.empty-add"
            variant="primary"
            onClick={() => setShowAdd(true)}
          >
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
              <p className="font-medium text-status-warning-text mb-1">
                In use by {removeDetail.agents_using.length} agent
                {removeDetail.agents_using.length === 1 ? "" : "s"}:
              </p>
              <ul className="list-disc list-inside">
                {removeDetail.agents_using.map((agent) => (
                  <li key={`${agent.hostname}:${agent.agent_key}`}>
                    <code>{agent.hostname}</code>:<code>{agent.agent_key}</code>
                  </li>
                ))}
              </ul>
              <p className="mt-2">
                Remove the assignment from those agents first.
              </p>
            </div>
          ) : null}
          {removeError ? (
            <p className="text-xs text-status-warning-text">{removeError}</p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              trackingId="integrations.remove.cancel"
              variant="secondary"
              onClick={() => {
                setRemoveTarget(null);
                setRemoveError(null);
              }}
            >
              Cancel
            </Button>
            <Button
              trackingId="integrations.remove.confirm"
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
