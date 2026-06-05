"use client";

// Functional parity with `clawctl agent provider attach` for hermes.
// First attach on a hermes agent is forced to `primary`; subsequent
// attaches show only the auxiliary slots that aren't already filled.
// Non-hermes agents hide the role selector entirely — the singleton
// invariant from `core.provider_attachments.validate()` keeps a second
// attach impossible regardless of what the UI sends.

import { useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import type {
  AgentAttachmentsResponse,
  Provider,
} from "@/lib/types";

interface AttachProviderModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (providerName: string, role: string | null) => Promise<void>;
  providers: Provider[];
  attachments: AgentAttachmentsResponse | null;
  saving?: boolean;
  error?: string | null;
}

export function AttachProviderModal({
  open,
  onClose,
  onSubmit,
  providers,
  attachments,
  saving,
  error,
}: AttachProviderModalProps) {
  const [providerName, setProviderName] = useState("");
  const [role, setRole] = useState("");
  const idPrefix = useId();
  const providerId = `${idPrefix}-provider`;
  const roleId = `${idPrefix}-role`;

  const supportsMulti = attachments?.supports_multi ?? false;
  const availableRoles = attachments?.available_roles ?? [];
  const attachedNames = new Set(
    (attachments?.attachments ?? []).map((entry) =>
      typeof entry === "string" ? entry : entry.name,
    ),
  );
  const eligibleProviders = providers.filter(
    (p) => !attachedNames.has(p.name),
  );

  // Auto-pin role when there's only one choice — matches the CLI's
  // first-attach contract where `primary` is the only legal value.
  const effectiveRole =
    supportsMulti && availableRoles.length === 1 ? availableRoles[0] : role;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!providerName) return;
    if (supportsMulti && !effectiveRole) return;
    void onSubmit(providerName, supportsMulti ? effectiveRole : null);
  }

  function handleClose() {
    setProviderName("");
    setRole("");
    onClose();
  }

  const noAvailableRoles = supportsMulti && availableRoles.length === 0;

  return (
    <Modal open={open} onClose={handleClose} title="Attach Provider">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor={providerId}
            className="block text-xs font-medium text-secondary mb-1"
          >
            Provider
          </label>
          <select
            id={providerId}
            value={providerName}
            onChange={(e) => setProviderName(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            required
          >
            <option value="">Select a provider…</option>
            {eligibleProviders.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name} ({p.type})
              </option>
            ))}
          </select>
          {eligibleProviders.length === 0 && (
            <p className="mt-1 text-xs text-muted">
              No unattached providers available.
            </p>
          )}
        </div>

        {supportsMulti && (
          <div>
            <label
              htmlFor={roleId}
              className="block text-xs font-medium text-secondary mb-1"
            >
              Role
            </label>
            {noAvailableRoles ? (
              <p className="text-xs text-amber-700">
                All auxiliary slots are filled. Detach an attachment to free a slot.
              </p>
            ) : (
              <select
                id={roleId}
                value={effectiveRole}
                onChange={(e) => setRole(e.target.value)}
                disabled={availableRoles.length === 1}
                className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary disabled:bg-surface"
                required
              >
                {availableRoles.length > 1 && (
                  <option value="">Select a role…</option>
                )}
                {availableRoles.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            )}
            {availableRoles.length === 1 && !noAvailableRoles && (
              <p className="mt-1 text-xs text-muted">
                Only one role is available — this attach will be locked to{" "}
                <code>{availableRoles[0]}</code>.
              </p>
            )}
          </div>
        )}

        {error && (
          <p className="text-xs text-rose-700" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={
              saving ||
              !providerName ||
              (supportsMulti && (noAvailableRoles || !effectiveRole))
            }
          >
            {saving ? "Attaching…" : "Attach"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
