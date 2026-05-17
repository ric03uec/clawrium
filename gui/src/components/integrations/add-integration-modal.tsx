"use client";

import { useMemo, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import type {
  IntegrationCreate,
  IntegrationCredentialDef,
  IntegrationTypesMap,
} from "@/lib/types";

interface AddIntegrationModalProps {
  open: boolean;
  onClose: () => void;
  onSave: (data: IntegrationCreate) => void;
  integrationTypes: IntegrationTypesMap;
  saving?: boolean;
  error?: string | null;
}

const SECRET_KEY_RE = /token|key|secret|password|api/i;

export function isSecretKey(key: string): boolean {
  return SECRET_KEY_RE.test(key);
}

export function AddIntegrationModal({
  open,
  onClose,
  onSave,
  integrationTypes,
  saving,
  error,
}: AddIntegrationModalProps) {
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});

  const credentialDefs = useMemo<IntegrationCredentialDef[]>(() => {
    if (!type) return [];
    return integrationTypes[type]?.credentials ?? [];
  }, [type, integrationTypes]);

  function handleTypeChange(newType: string) {
    setType(newType);
    setValues({});
  }

  function handleClose() {
    setName("");
    setType("");
    setValues({});
    onClose();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !type) return;
    onSave({
      name: name.trim(),
      type,
      credentials: Object.fromEntries(
        Object.entries(values).filter(([, v]) => v.trim() !== ""),
      ),
    });
  }

  const requiredMissing = credentialDefs.some(
    (c) => c.required && !(values[c.key] || "").trim(),
  );

  return (
    <Modal open={open} onClose={handleClose} title="Add Integration">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="integration-name"
            className="block text-xs font-medium text-secondary mb-1"
          >
            Integration name
          </label>
          <input
            id="integration-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-github"
            className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            required
          />
        </div>

        <div>
          <label
            htmlFor="integration-type"
            className="block text-xs font-medium text-secondary mb-1"
          >
            Type
          </label>
          <select
            id="integration-type"
            value={type}
            onChange={(e) => handleTypeChange(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            required
          >
            <option value="">Select integration type...</option>
            {Object.keys(integrationTypes).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          {type && integrationTypes[type]?.description ? (
            <p className="mt-1 text-xs text-muted">
              {integrationTypes[type].description}
            </p>
          ) : null}
        </div>

        {credentialDefs.length > 0 && (
          <div className="space-y-3 pt-2 border-t border-default">
            <p className="text-xs font-medium text-secondary">Credentials</p>
            {credentialDefs.map((c) => {
              const secret = isSecretKey(c.key);
              const fieldId = `integration-cred-${c.key}`;
              return (
                <div key={c.key}>
                  <label
                    htmlFor={fieldId}
                    className="block text-xs font-medium text-secondary mb-1"
                  >
                    {c.key}
                    {c.required ? (
                      <span className="text-status-warning ml-1">*</span>
                    ) : null}
                  </label>
                  <input
                    id={fieldId}
                    type={secret ? "password" : "text"}
                    value={values[c.key] || ""}
                    onChange={(e) =>
                      setValues((prev) => ({
                        ...prev,
                        [c.key]: e.target.value,
                      }))
                    }
                    className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary font-mono"
                    required={c.required}
                  />
                  <p className="mt-0.5 text-[11px] text-muted">
                    {c.description}
                  </p>
                </div>
              );
            })}
          </div>
        )}

        {error ? (
          <p className="text-xs text-status-warning">{error}</p>
        ) : null}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" type="button" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            type="submit"
            disabled={!name.trim() || !type || requiredMissing || saving}
          >
            {saving ? "Saving..." : "Save"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
