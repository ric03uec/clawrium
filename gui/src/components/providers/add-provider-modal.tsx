"use client";

import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import type {
  AcceleratorVendor,
  ProviderTypesMap,
  ProviderCreate,
} from "@/lib/types";

interface AddProviderModalProps {
  open: boolean;
  onClose: () => void;
  onSave: (data: ProviderCreate) => void;
  providerTypes: ProviderTypesMap;
  saving?: boolean;
}

export function AddProviderModal({
  open,
  onClose,
  onSave,
  providerTypes,
  saving,
}: AddProviderModalProps) {
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [acceleratorVendor, setAcceleratorVendor] =
    useState<AcceleratorVendor>("nvidia");

  const typeInfo = type ? providerTypes[type] : null;
  const availableModels = typeInfo?.models || [];
  const autoEndpoint = typeInfo?.endpoint || "";

  function handleTypeChange(newType: string) {
    setType(newType);
    setModel("");
    const info = providerTypes[newType];
    if (info?.endpoint) {
      setEndpoint(info.endpoint);
    } else {
      setEndpoint("");
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !type) return;
    onSave({
      name: name.trim(),
      type,
      default_model: model || undefined,
      api_key: apiKey || undefined,
      endpoint: endpoint || autoEndpoint || undefined,
      accelerator_vendor: type === "ollama" ? acceleratorVendor : undefined,
    });
  }

  function handleClose() {
    setName("");
    setType("");
    setModel("");
    setApiKey("");
    setEndpoint("");
    setShowKey(false);
    setAcceleratorVendor("nvidia");
    onClose();
  }

  return (
    <Modal open={open} onClose={handleClose} title="Add Provider">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Name */}
        <div>
          <label className="block text-xs font-medium text-secondary mb-1">
            Provider Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-provider"
            className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            required
          />
        </div>

        {/* Type */}
        <div>
          <label className="block text-xs font-medium text-secondary mb-1">
            Type
          </label>
          <select
            value={type}
            onChange={(e) => handleTypeChange(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            required
          >
            <option value="">Select provider type...</option>
            {Object.keys(providerTypes).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        {/* Accelerator (local-inference only) */}
        {type === "ollama" && (
          <div>
            <label className="block text-xs font-medium text-secondary mb-1">
              Accelerator
            </label>
            <div className="flex items-center gap-4">
              {(["nvidia", "amd"] as const).map((vendor) => (
                <label
                  key={vendor}
                  className="flex items-center gap-2 text-sm text-primary-text cursor-pointer"
                >
                  <input
                    type="radio"
                    name="accelerator-vendor"
                    value={vendor}
                    checked={acceleratorVendor === vendor}
                    onChange={() => setAcceleratorVendor(vendor)}
                    className="text-primary focus:ring-primary/30"
                  />
                  <span className="uppercase tracking-wide text-xs font-semibold">
                    {vendor}
                  </span>
                </label>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-muted">
              Used by the topology view to display the correct local-GPU brand.
            </p>
          </div>
        )}

        {/* Default Model */}
        {availableModels && availableModels.length > 0 && (
          <div>
            <label className="block text-xs font-medium text-secondary mb-1">
              Default Model
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            >
              <option value="">Select model...</option>
              {availableModels.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* API Key */}
        {typeInfo?.requires_api_key && (
          <div>
            <label className="block text-xs font-medium text-secondary mb-1">
              API Key
            </label>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full px-3 py-2 pr-10 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary font-mono"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-secondary text-xs"
              >
                {showKey ? "hide" : "show"}
              </button>
            </div>
          </div>
        )}

        {/* Endpoint */}
        {(typeInfo?.requires_endpoint || type === "ollama") && (
          <div>
            <label className="block text-xs font-medium text-secondary mb-1">
              Endpoint
            </label>
            <input
              type="text"
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="http://192.168.1.10:11434"
              className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary font-mono"
              required={typeInfo?.requires_endpoint}
            />
          </div>
        )}

        {/* Auto-filled endpoint note */}
        {autoEndpoint && !typeInfo?.requires_endpoint && type !== "ollama" && (
          <div className="text-xs text-muted">
            Endpoint: <span className="font-mono">{autoEndpoint}</span> (auto-configured)
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" type="button" onClick={handleClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" disabled={!name.trim() || !type || saving}>
            {saving ? "Saving..." : "Save"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
