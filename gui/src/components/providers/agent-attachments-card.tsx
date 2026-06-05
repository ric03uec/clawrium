"use client";

// Provider attachments card for the agent detail page. Brings the GUI
// to functional parity with `clawctl agent provider {attach,detach,get}`
// for hermes: shows the role column, surfaces the Attach modal with a
// role selector filtered by what's already filled, and disables the
// primary-detach button while any auxiliary attachments remain.

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { AgentAttachmentsResponse, Provider } from "@/lib/types";
import { AttachProviderModal } from "./attach-provider-modal";

interface AgentAttachmentsCardProps {
  agentName: string;
}

interface RowEntry {
  name: string;
  role: string;
  model: string;
}

function rowsFromAttachments(
  data: AgentAttachmentsResponse | null,
): RowEntry[] {
  if (!data) return [];
  return data.attachments.map((entry) =>
    typeof entry === "string"
      ? { name: entry, role: "", model: "" }
      : { name: entry.name, role: entry.role || "", model: entry.model || "" },
  );
}

export function AgentAttachmentsCard({ agentName }: AgentAttachmentsCardProps) {
  const [data, setData] = useState<AgentAttachmentsResponse | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opError, setOpError] = useState<string | null>(null);
  // Per-row in-flight guard so a double-click can't fire two concurrent
  // DELETEs (and race the subsequent refresh on the first one).
  const [detaching, setDetaching] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const [att, plist] = await Promise.all([
        api.getAgentAttachments(agentName),
        api.getProviders(),
      ]);
      setData(att);
      setProviders(plist);
      setOpError(null);
    } catch (e) {
      setOpError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // refresh is local to the component; agentName is the only input
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentName]);

  async function handleAttach(providerName: string, role: string | null) {
    setSaving(true);
    setError(null);
    try {
      await api.attachProviderToAgent(providerName, {
        agent: agentName,
        role,
      });
      setModalOpen(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDetach(providerName: string) {
    if (detaching) return;
    setOpError(null);
    setDetaching(providerName);
    try {
      await api.detachProviderFromAgent(providerName, agentName);
      await refresh();
    } catch (e) {
      setOpError(e instanceof Error ? e.message : String(e));
    } finally {
      setDetaching(null);
    }
  }

  const rows = rowsFromAttachments(data);
  const supportsMulti = data?.supports_multi ?? false;
  const auxCount = data?.aux_count ?? 0;
  const canAttachMore =
    !!data &&
    (supportsMulti
      ? data.available_roles.length > 0
      : rows.length === 0);

  return (
    <Card padding="md">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-primary-text">
          Provider Attachments
        </h3>
        <Button
          size="sm"
          onClick={() => setModalOpen(true)}
          disabled={loading || !canAttachMore}
        >
          + Attach
        </Button>
      </div>

      {opError && (
        <p className="mb-2 text-xs text-rose-700" role="alert">
          {opError}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted">No provider attached.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted border-b border-default">
              <th className="py-1.5 font-medium">Name</th>
              {supportsMulti && <th className="py-1.5 font-medium">Role</th>}
              {supportsMulti && <th className="py-1.5 font-medium">Model</th>}
              <th className="py-1.5 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isPrimary = supportsMulti && row.role === "primary";
              const detachDisabled = isPrimary && auxCount > 0;
              const detachTitle = detachDisabled
                ? "Detach auxiliary attachments first"
                : `Detach ${row.name}`;
              return (
                <tr
                  key={row.name}
                  className="border-b border-default/50 last:border-0"
                >
                  <td className="py-1.5 text-primary-text">{row.name}</td>
                  {supportsMulti && (
                    <td className="py-1.5 text-secondary font-mono text-xs">
                      {row.role || "—"}
                    </td>
                  )}
                  {supportsMulti && (
                    <td className="py-1.5 text-secondary font-mono text-xs">
                      {row.model || "—"}
                    </td>
                  )}
                  <td className="py-1.5 text-right">
                    {/* Wrap in <span> so the title tooltip stays visible
                        on Firefox/Safari, where disabled buttons swallow
                        the `title` attribute. */}
                    <span title={detachTitle} className="inline-block">
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={detachDisabled || detaching === row.name}
                        onClick={() => void handleDetach(row.name)}
                      >
                        {detaching === row.name ? "Detaching…" : "Detach"}
                      </Button>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <AttachProviderModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setError(null);
        }}
        onSubmit={handleAttach}
        providers={providers}
        attachments={data}
        saving={saving}
        error={error}
      />
    </Card>
  );
}
