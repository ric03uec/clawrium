"use client";

import { useState } from "react";
import { PageHeader } from "@/components/layout";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import {
  ProviderCard,
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

export default function ProvidersPage() {
  const { data: providers, isLoading } = useProviders();
  const { data: providerTypes } = useProviderTypes();
  const { data: fleet } = useFleet();
  const createMutation = useCreateProvider();
  const updateMutation = useUpdateProvider();
  const deleteMutation = useDeleteProvider();

  const [showAdd, setShowAdd] = useState(false);
  const [editProvider, setEditProvider] = useState<Provider | null>(null);
  const [removeProvider, setRemoveProvider] = useState<Provider | null>(null);

  // Build a map of provider name -> agent names using it
  const providerUsage: Record<string, string[]> = {};
  if (fleet?.agents) {
    for (const agent of fleet.agents) {
      // The fleet agent data doesn't directly expose provider_name at summary level,
      // but we can check from the config in agent detail. For now, we leave it empty
      // since the summary API doesn't include provider_name.
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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Providers"
        description="Manage LLM provider configurations"
        actions={
          <Button variant="primary" onClick={() => setShowAdd(true)}>
            + Add Provider
          </Button>
        }
      />

      {/* Provider list */}
      {isLoading ? (
        <div className="bg-surface rounded-xl border border-default p-8 text-center text-muted text-sm">
          Loading providers...
        </div>
      ) : providers && providers.length > 0 ? (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-primary-text">
            Configured Providers ({providers.length})
          </h2>
          {providers.map((p) => (
            <ProviderCard
              key={p.name}
              provider={p}
              usedBy={providerUsage[p.name] || []}
              onEdit={() => setEditProvider(p)}
              onRemove={() => setRemoveProvider(p)}
            />
          ))}
        </div>
      ) : (
        <div className="bg-surface rounded-xl border border-default p-12 text-center">
          <p className="text-sm text-muted mb-3">No providers configured yet</p>
          <Button variant="primary" onClick={() => setShowAdd(true)}>
            + Add your first provider
          </Button>
        </div>
      )}

      {/* Model Catalog */}
      <ModelCatalog />

      {/* Add Provider Modal */}
      {providerTypes && (
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
            This will also remove its stored API key.
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
