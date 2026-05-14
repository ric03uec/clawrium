"use client";

import { useState, useMemo } from "react";
import { Card } from "@/components/ui/card";
import { useModelCatalog } from "@/hooks/use-providers";

export function ModelCatalog() {
  const [search, setSearch] = useState("");
  const [filterProvider, setFilterProvider] = useState<string>("");

  // Fetch the catalog with the server-side search when provided
  const { data: models, isLoading } = useModelCatalog(
    filterProvider || undefined,
    search.length >= 2 ? search : undefined
  );

  // Client-side filtering for short search terms
  const filteredModels = useMemo(() => {
    if (!models) return [];
    if (search.length >= 2) return models; // Already filtered server-side
    if (search.length === 1) {
      return models.filter(
        (m) =>
          m.id.toLowerCase().includes(search.toLowerCase()) ||
          m.name.toLowerCase().includes(search.toLowerCase())
      );
    }
    return models;
  }, [models, search]);

  // Get unique providers for filter dropdown
  const providers = useMemo(() => {
    if (!models) return [];
    return [...new Set(models.map((m) => m.provider_type))].sort();
  }, [models]);

  return (
    <Card padding="md">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-primary-text">Model Catalog</h2>
        <div className="flex gap-2">
          <select
            value={filterProvider}
            onChange={(e) => setFilterProvider(e.target.value)}
            className="px-2 py-1.5 text-xs border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30"
          >
            <option value="">All Providers</option>
            {providers.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search models..."
            className="w-48 px-3 py-1.5 text-xs border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-sm text-muted">Loading catalog...</div>
      ) : (
        <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-white">
              <tr className="border-b border-default text-left text-muted">
                <th className="py-2 px-2 font-medium">Provider</th>
                <th className="py-2 px-2 font-medium">Model</th>
                <th className="py-2 px-2 font-medium">Context</th>
                <th className="py-2 px-2 font-medium">Tags</th>
              </tr>
            </thead>
            <tbody>
              {filteredModels.slice(0, 100).map((model) => (
                <tr key={`${model.provider_type}-${model.id}`} className="border-b border-default/50 hover:bg-surface">
                  <td className="py-1.5 px-2 text-secondary">{model.provider_type}</td>
                  <td className="py-1.5 px-2 font-medium text-primary-text font-mono">
                    {model.id}
                  </td>
                  <td className="py-1.5 px-2 text-secondary">
                    {formatContext(model.context_window)}
                  </td>
                  <td className="py-1.5 px-2">
                    <div className="flex gap-1 flex-wrap">
                      {model.tags.map((tag) => (
                        <span
                          key={tag}
                          className="px-1.5 py-0.5 bg-surface text-muted rounded text-[10px]"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
              {filteredModels.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-muted">
                    No models found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {filteredModels.length > 100 && (
            <div className="py-2 text-center text-xs text-muted">
              Showing 100 of {filteredModels.length} models
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function formatContext(windowSize: number): string {
  if (windowSize >= 1000000) return `${(windowSize / 1000000).toFixed(1)}M`;
  if (windowSize >= 1000) return `${Math.round(windowSize / 1000)}K`;
  return String(windowSize);
}
