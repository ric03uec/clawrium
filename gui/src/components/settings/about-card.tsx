"use client";

import { Card } from "@/components/ui";
import { Settings, VersionInfo } from "@/lib/types";

interface AboutCardProps {
  settings: Settings | undefined;
  version: VersionInfo | undefined;
}

export function AboutCard({ settings, version }: AboutCardProps) {
  return (
    <Card>
      <h2 className="text-lg font-semibold text-primary mb-4">About</h2>
      <div className="grid grid-cols-[140px_1fr] gap-y-3 text-sm">
        <span className="text-muted">Version</span>
        <span className="font-mono">{version?.version ?? "—"}</span>

        <span className="text-muted">Config Dir</span>
        <span className="font-mono text-xs break-all">
          {settings?.config_dir ?? "—"}
        </span>

        <span className="text-muted">Python</span>
        <span className="font-mono">{version?.python_version ?? "—"}</span>

        <span className="text-muted">Platform</span>
        <span className="font-mono">
          {version ? `${version.platform} ${version.arch}` : "—"}
        </span>
      </div>
    </Card>
  );
}
