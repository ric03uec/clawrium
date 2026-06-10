"use client";

import { useState } from "react";
import { PageHeader } from "@/components/layout";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import {
  ProvidersTable,
  AddProviderModal,
  EditProviderModal,
  ModelCatalog,
} from "@/components/providers";
import {
  useProviders,
  useProviderTypes,
  useCreateProvider,
  useUpdateProvider,
  useDeleteProvider,
} from "@/hooks/use-providers";
import { useFleet } from "@/hooks/use-fleet";
import type { Provider, ProviderCreate, ProviderUpdate } from "@/lib/types";

type TabId = "configured" | "registry";

export default function ProvidersPage() {
  const { data: providers, isLoading } = useProviders();
  const { data: providerTypes } = useProviderTypes();
  const { data: fleet } = useFleet();
  const createMutation = useCreateProvider();
  const updateMutation = useUpdateProvider();
  const deleteMutation = useDeleteProvider();

  const [tab, setTab] = useState<TabId>("configured");
  const [showAdd, setShowAdd] = useState(false);
  const [editProvider, setEditProvider] = useState<Provider | null>(null);
  const [removeProvider, setRemoveProvider] = useState<Provider | null>(null);

  // Build a map of provider name -> agent names using it
  const providerUsage: Record<string, string[]> = {};
  if (fleet?.agents) {
    for (const agent of fleet.agents) {
      if (agent.provider) {
        if (!providerUsage[agent.provider]) {
          providerUsage[agent.provider] = [];
        }
        providerUsage[agent.provider].push(agent.agent_name);
      }
    }
  }

  function handleCreate(data: ProviderCreate) {
    createMutation.mutate(data, {
      onSuccess: () => setShowAdd(false),
    });
  }

  function handleUpdate(data: ProviderUpdate) {
    if (!editProvider) return;
    updateMutation.mutate(
      { name: editProvider.name, data },
      { onSuccess: () => setEditProvider(null) }
    );
  }

  function handleDelete() {
    if (!removeProvider) return;
    deleteMutation.mutate(removeProvider.name, {
      onSuccess: () => setRemoveProvider(null),
    });
  }

  const providerCount = providers?.length ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Providers"
        description="Configure LLM providers once, apply them across your fleet. Each provider can power multiple agents."
      />

      <div className="bg-surface rounded-xl border border-default">
        <div className="flex items-center justify-between border-b border-default px-2">
          <nav className="flex" aria-label="Providers tabs">
            <TabButton
              active={tab === "configured"}
              onClick={() => setTab("configured")}
            >
              Configured {providerCount > 0 ? `(${providerCount})` : ""}
            </TabButton>
            <TabButton
              active={tab === "registry"}
              onClick={() => setTab("registry")}
            >
              Registry
            </TabButton>
          </nav>
          {tab === "configured" && (
            <Button variant="primary" onClick={() => setShowAdd(true)}>
              + Add Provider
            </Button>
          )}
        </div>

        <div className="p-4">
          {tab === "configured" ? (
            isLoading ? (
              <div className="p-8 text-center text-muted text-sm">
                Loading providers...
              </div>
            ) : providers && providers.length > 0 ? (
              <ProvidersTable
                providers={providers}
                usage={providerUsage}
                onEdit={setEditProvider}
                onRemove={setRemoveProvider}
              />
            ) : (
              <div className="p-12 text-center">
                <p className="text-sm text-muted mb-3">
                  No providers configured yet — add one or browse the Registry
                  tab.
                </p>
                <Button variant="primary" onClick={() => setShowAdd(true)}>
                  + Add your first provider
                </Button>
              </div>
            )
          ) : (
            <ModelCatalog />
          )}
        </div>
      </div>

      {/* Add Provider Modal — conditionally mounted so closing the modal
          discards any partially-entered AWS credentials and starts fresh
          on the next open. */}
      {showAdd && providerTypes && (
        <AddProviderModal
          open={showAdd}
          onClose={() => setShowAdd(false)}
          onSave={handleCreate}
          providerTypes={providerTypes}
          saving={createMutation.isPending}
        />
      )}

      {/* Edit Provider Modal */}
      {editProvider && providerTypes && (
        <EditProviderModal
          open={!!editProvider}
          onClose={() => setEditProvider(null)}
          onSave={handleUpdate}
          provider={editProvider}
          providerTypes={providerTypes}
          saving={updateMutation.isPending}
        />
      )}

      {/* Remove Confirmation Modal */}
      <Modal
        open={!!removeProvider}
        onClose={() => setRemoveProvider(null)}
        title="Remove Provider"
      >
        <div className="space-y-4">
          <p className="text-sm text-secondary">
            Are you sure you want to remove <strong>{removeProvider?.name}</strong>?
            This will also remove its stored credentials.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setRemoveProvider(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "Removing..." : "Remove"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function TabButton({ active, onClick, children }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
        active
          ? "border-primary text-primary"
          : "border-transparent text-muted hover:text-secondary hover:border-gray-300"
      }`}
    >
      {children}
    </button>
  );
}
