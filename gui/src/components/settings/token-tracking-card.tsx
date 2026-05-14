"use client";

import { useState } from "react";
import { Card, Button } from "@/components/ui";
import { Modal } from "@/components/ui";
import { Settings } from "@/lib/types";
import { api } from "@/lib/api";

interface TokenTrackingCardProps {
  settings: Settings | undefined;
  onClear: () => void;
}

export function TokenTrackingCard({ settings, onClear }: TokenTrackingCardProps) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      await api.exportUsageCsv();
    } catch (e) {
      console.error("Export failed:", e);
    } finally {
      setExporting(false);
    }
  };

  const handleClear = () => {
    onClear();
    setShowConfirm(false);
  };

  return (
    <>
      <Card>
        <h2 className="text-lg font-semibold text-primary mb-4">
          Token Tracking
        </h2>
        <div className="grid grid-cols-[140px_1fr] gap-y-3 text-sm">
          <span className="text-muted">Status</span>
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-status-running" />
            Enabled
          </span>

          <span className="text-muted">Storage</span>
          <span className="font-mono text-xs break-all">
            {settings?.usage_db ?? "—"}
          </span>
        </div>

        <div className="mt-6 flex gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleExport}
            disabled={exporting}
          >
            {exporting ? "Exporting..." : "Export CSV"}
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => setShowConfirm(true)}
          >
            Clear Usage Data
          </Button>
        </div>
      </Card>

      <Modal
        open={showConfirm}
        onClose={() => setShowConfirm(false)}
        title="Clear Usage Data"
      >
        <p className="text-sm text-secondary mb-6">
          This will permanently delete all token usage history. This action
          cannot be undone.
        </p>
        <div className="flex justify-end gap-3">
          <Button variant="secondary" size="sm" onClick={() => setShowConfirm(false)}>
            Cancel
          </Button>
          <Button variant="danger" size="sm" onClick={handleClear}>
            Clear All Data
          </Button>
        </div>
      </Modal>
    </>
  );
}
