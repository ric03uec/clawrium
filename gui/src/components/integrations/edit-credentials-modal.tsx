"use client";

import { useMemo, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import type {
  Integration,
  IntegrationCredentialDef,
  IntegrationCredentialsUpdate,
  IntegrationTypesMap,
} from "@/lib/types";
import { isSecretKey } from "./add-integration-modal";

interface EditCredentialsModalProps {
  open: boolean;
  onClose: () => void;
  onSave: (data: IntegrationCredentialsUpdate) => void;
  integration: Integration;
  integrationTypes: IntegrationTypesMap;
  saving?: boolean;
}

export function EditCredentialsModal({
  open,
  onClose,
  onSave,
  integration,
  integrationTypes,
  saving,
}: EditCredentialsModalProps) {
  const [values, setValues] = useState<Record<string, string>>({});

  const credentialDefs = useMemo<IntegrationCredentialDef[]>(
    () => integrationTypes[integration.type]?.credentials ?? [],
    [integration.type, integrationTypes],
  );

  function handleClose() {
    setValues({});
    onClose();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSave({
      credentials: Object.fromEntries(
        Object.entries(values).filter(([, v]) => v.trim() !== ""),
      ),
    });
  }

  const hasInput = Object.values(values).some((v) => v.trim() !== "");

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={`Edit credentials — ${integration.name}`}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-xs text-muted">
          Leave a field blank to keep the existing value.
        </p>

        {credentialDefs.map((c) => {
          const isConfigured = integration.configured_credential_keys.includes(
            c.key,
          );
          const fieldId = `edit-integration-cred-${c.key}`;
          return (
            <div key={c.key}>
              <label
                htmlFor={fieldId}
                className="block text-xs font-medium text-secondary mb-1"
              >
                {c.key}{" "}
                <span className="text-muted">
                  {isConfigured ? "(set)" : "(not set)"}
                </span>
              </label>
              <input
                id={fieldId}
                type={isSecretKey(c.key) ? "password" : "text"}
                value={values[c.key] || ""}
                onChange={(e) =>
                  setValues((prev) => ({
                    ...prev,
                    [c.key]: e.target.value,
                  }))
                }
                className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary font-mono"
              />
              <p className="mt-0.5 text-[11px] text-muted">{c.description}</p>
            </div>
          );
        })}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" type="button" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            type="submit"
            disabled={!hasInput || saving}
          >
            {saving ? "Saving..." : "Update credentials"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
