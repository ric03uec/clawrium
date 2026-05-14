"use client";

import { Card } from "@/components/ui/card";

interface SkillsTabProps {
  agentKey: string;
}

export function SkillsTab({ agentKey }: SkillsTabProps) {
  // Skills and integrations are not yet exposed via the core API.
  // This tab shows a placeholder until the backend endpoints are added.
  return (
    <div className="space-y-6 p-4">
      <Card padding="md">
        <h3 className="text-sm font-semibold text-primary-text mb-4">
          Installed Skills
        </h3>
        <div className="flex items-center justify-center py-8 text-muted text-sm">
          <p>
            Skill management will be available in a future update.
            <br />
            <span className="text-xs">
              Use <code className="bg-surface px-1 py-0.5 rounded">clm agent skill</code> in the CLI.
            </span>
          </p>
        </div>
      </Card>

      <Card padding="md">
        <h3 className="text-sm font-semibold text-primary-text mb-4">
          Integrations
        </h3>
        <div className="flex items-center justify-center py-8 text-muted text-sm">
          <p>
            Integration management will be available in a future update.
            <br />
            <span className="text-xs">
              Use <code className="bg-surface px-1 py-0.5 rounded">clm agent integration</code> in the CLI.
            </span>
          </p>
        </div>
      </Card>
    </div>
  );
}
