"use client";

import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import type { Provider, ProviderTypesMap, ProviderUpdate } from "@/lib/types";

interface EditProviderModalProps {
  open: boolean;
  onClose: () => void;
  onSave: (data: ProviderUpdate) => void;
  provider: Provider;
  providerTypes: ProviderTypesMap;
  saving?: boolean;
}

export function EditProviderModal({
  open,
  onClose,
  onSave,
  provider,
  providerTypes,
  saving,
}: EditProviderModalProps) {
  const [model, setModel] = useState(provider.default_model || "");
  const [endpoint, setEndpoint] = useState(provider.endpoint || "");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);

  const typeInfo = providerTypes[provider.type];
  const availableModels = typeInfo?.models || provider.available_models || [];

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const update: ProviderUpdate = {};
    if (model !== (provider.default_model || "")) update.default_model = model;
    if (endpoint !== (provider.endpoint || "")) update.endpoint = endpoint;
    if (apiKey) update.api_key = apiKey;
    onSave(update);
  }

  function handleClose() {
    setModel(provider.default_model || "");
    setEndpoint(provider.endpoint || "");
    setApiKey("");
    setShowKey(false);
    onClose();
  }

  return (
    <Modal open={open} onClose={handleClose} title={`Edit: ${provider.name}`}>
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Type (read-only) */}
        <div>
          <label className="block text-xs font-medium text-secondary mb-1">
            Type
          </label>
          <div className="px-3 py-2 text-sm border border-default rounded-lg bg-panel text-muted">
            {provider.type}
          </div>
        </div>

        {/* Default Model */}
        {availableModels && availableModels.length > 0 ? (
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
        ) : (
          <div>
            <label className="block text-xs font-medium text-secondary mb-1">
              Default Model
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="model-name"
              className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            />
          </div>
        )}

        {/* Endpoint */}
        <div>
          <label className="block text-xs font-medium text-secondary mb-1">
            Endpoint
          </label>
          <input
            type="text"
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            placeholder="https://..."
            className="w-full px-3 py-2 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary font-mono"
          />
        </div>

        {/* API Key */}
        {typeInfo?.requires_api_key && (
          <div>
            <label className="block text-xs font-medium text-secondary mb-1">
              API Key {provider.has_api_key && <span className="text-muted">(leave blank to keep current)</span>}
            </label>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={provider.has_api_key ? "••••••••••" : "sk-..."}
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

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" type="button" onClick={handleClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" disabled={saving}>
            {saving ? "Saving..." : "Save Changes"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
