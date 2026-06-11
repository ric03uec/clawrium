"use client";

import { useState, useMemo, useEffect } from "react";
import {
  useProviderTypes,
  useModelCatalog,
} from "@/hooks/use-providers";

const PAGE_SIZE = 50;

export function ModelCatalog() {
  const { data: providerTypes, isLoading: typesLoading } = useProviderTypes();
  const [selected, setSelected] = useState<string>("__all__");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const typeEntries = useMemo(() => {
    if (!providerTypes) return [];
    return Object.entries(providerTypes).sort((a, b) =>
      a[0].localeCompare(b[0]),
    );
  }, [providerTypes]);

  const totalAllModels = useMemo(
    () =>
      typeEntries.reduce(
        (sum, [, info]) => sum + (info.models?.length ?? 0),
        0,
      ),
    [typeEntries],
  );

  // Reset page + search when provider changes
  useEffect(() => {
    setPage(1);
    setSearch("");
  }, [selected]);

  const isAll = selected === "__all__";
  const isOllama = selected === "ollama";
  const { data: models, isLoading: modelsLoading } = useModelCatalog(
    isAll || isOllama ? undefined : selected,
    undefined,
    isAll ? 500 : undefined,
  );

  const filtered = useMemo(() => {
    if (!models) return [];
    const q = search.trim().toLowerCase();
    if (!q) return models;
    return models.filter(
      (m) =>
        m.id.toLowerCase().includes(q) ||
        (m.name && m.name.toLowerCase().includes(q)),
    );
  }, [models, search]);

  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const start = (currentPage - 1) * PAGE_SIZE;
  const visible = filtered.slice(start, start + PAGE_SIZE);

  if (typesLoading) {
    return (
      <div className="py-8 text-center text-sm text-muted">
        Loading registry...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="px-3 py-1.5 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="__all__">All providers ({totalAllModels} models)</option>
          {typeEntries.map(([ptype, info]) => {
            const count = info.models?.length ?? 0;
            const countLabel =
              ptype === "ollama"
                ? "per-host"
                : count > 0
                  ? `${count} models`
                  : "—";
            return (
              <option key={ptype} value={ptype}>
                {ptype} ({countLabel})
              </option>
            );
          })}
        </select>
        {!isOllama && (
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="Search models..."
            className="w-64 px-3 py-1.5 text-sm border border-default rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
        )}
      </div>

      {isOllama ? (
        <div className="py-8 text-center text-sm text-muted">
          Models are discovered per-host from the Ollama daemon. See the
          configured Ollama provider in the Configured tab.
        </div>
      ) : modelsLoading ? (
        <div className="py-8 text-center text-sm text-muted">
          Loading models...
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-default text-left">
                  {isAll && (
                    <th className="pb-3 pr-4 font-medium text-muted">Provider</th>
                  )}
                  <th className="pb-3 pr-4 font-medium text-muted">Model</th>
                  <th className="pb-3 pr-4 font-medium text-muted">Context</th>
                  <th className="pb-3 font-medium text-muted">Tags</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((model) => (
                  <tr
                    key={`${model.provider_type}-${model.id}`}
                    className="border-b border-default last:border-0 hover:bg-surface"
                  >
                    {isAll && (
                      <td className="py-3 pr-4 text-secondary">
                        {model.provider_type}
                      </td>
                    )}
                    <td className="py-3 pr-4 font-medium text-primary-text font-mono">
                      {model.id}
                    </td>
                    <td className="py-3 pr-4 text-secondary">
                      {formatContext(model.context_window)}
                    </td>
                    <td className="py-3">
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
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={isAll ? 4 : 3} className="py-6 text-center text-muted">
                      No models found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {total > 0 && (
            <div className="flex items-center justify-between text-xs text-muted">
              <span>
                Showing {start + 1}–{Math.min(start + PAGE_SIZE, total)} of{" "}
                {total}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage <= 1}
                  className="px-2 py-1 border border-default rounded disabled:opacity-40 hover:bg-surface"
                >
                  ‹ Prev
                </button>
                <span>
                  Page {currentPage}/{totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={currentPage >= totalPages}
                  className="px-2 py-1 border border-default rounded disabled:opacity-40 hover:bg-surface"
                >
                  Next ›
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function formatContext(windowSize: number): string {
  if (windowSize >= 1000000) return `${(windowSize / 1000000).toFixed(1)}M`;
  if (windowSize >= 1000) return `${Math.round(windowSize / 1000)}K`;
  return String(windowSize);
}
