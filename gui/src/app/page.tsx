"use client";

import { PageHeader } from "@/components/layout";
import {
  MetricsRow,
  UsageChart,
  StatusChart,
  AgentTable,
} from "@/components/dashboard";

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Dashboard"
        description="Fleet overview and usage metrics"
      />

      {/* Metrics cards row */}
      <MetricsRow />

      {/* Charts row: Usage chart (wider) + Status chart (narrower) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <UsageChart />
        </div>
        <div className="lg:col-span-1">
          <StatusChart />
        </div>
      </div>

      {/* Agent table */}
      <AgentTable />
    </div>
  );
}
