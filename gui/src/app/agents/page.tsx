"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { Suspense, useState } from "react";
import { useAgent, useAgentHealth } from "@/hooks";
import { PageHeader } from "@/components/layout";
import { AgentTable } from "@/components/dashboard";
import {
  AgentHeader,
  AgentMetrics,
  TabNav,
  TabId,
  OverviewTab,
  ChatTab,
  ExecTab,
  ConfigTab,
  SkillsTab,
  MemoryTab,
  LogsTab,
} from "@/components/agent-detail";

function AgentsRouter() {
  const searchParams = useSearchParams();
  const key = searchParams.get("key");
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  if (!key) return <AgentsListView />;
  return (
    <AgentDetailView
      agentKey={key}
      activeTab={activeTab}
      onTabChange={setActiveTab}
    />
  );
}

function AgentsListView() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Agents"
        description="All agents across your fleet"
      />
      <AgentTable />
    </div>
  );
}

function AgentDetailView({
  agentKey,
  activeTab,
  onTabChange,
}: {
  agentKey: string;
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
}) {
  const { data: agent, isLoading, error } = useAgent(agentKey);
  // #758: health is fetched in parallel and never gates the shell.
  // Children read runtime fields from `health` when present and fall
  // back to the static AgentDetail (which carries status="checking"
  // until the probe lands) so they can render a sensible default.
  const health = useAgentHealth(agentKey);
  const router = useRouter();

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="bg-white rounded-xl border border-default p-6 shadow-sm animate-pulse h-24" />
        <div className="bg-white rounded-xl border border-default p-6 shadow-sm animate-pulse h-16" />
        <div className="bg-white rounded-xl border border-default p-6 shadow-sm animate-pulse h-96" />
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="bg-surface rounded-xl border border-default p-12 text-center text-muted">
        <p className="mb-4">Agent not found or unreachable.</p>
        <button
          onClick={() => router.push("/agents")}
          className="text-primary hover:underline text-sm"
        >
          Back to Agents
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="text-sm text-muted">
        <button onClick={() => router.push("/agents")} className="hover:text-primary">
          Agents
        </button>
        <span className="mx-2">/</span>
        <span className="text-primary-text">{agent.agent_name}</span>
      </div>

      {/* key={agent.agent_key}: prevent local state (revealed token,
          copied flags, pairing-code mutation result) from leaking
          across agents when the user switches via the search-param-only
          route change. AgentMetrics + OverviewTab are keyed too
          (#758 S4) — no local state today, but the key keeps the
          invariant consistent so a future hook inside either component
          does not silently regress. */}
      <AgentHeader key={agent.agent_key} agent={agent} health={health.data} />

      <AgentMetrics key={agent.agent_key} agent={agent} health={health.data} />

      <div className="bg-white rounded-xl border border-default shadow-sm overflow-hidden">
        <TabNav active={activeTab} onChange={onTabChange} />
        <div className="min-h-[500px]">
          {activeTab === "overview" && (
            <OverviewTab
              key={agent.agent_key}
              agent={agent}
              agentKey={agentKey}
              health={health.data}
            />
          )}
          {activeTab === "chat" && (
            <ChatTab agentKey={agentKey} agentName={agent.agent_name} />
          )}
          {activeTab === "exec" && <ExecTab agentKey={agentKey} />}
          {activeTab === "configuration" && <ConfigTab agent={agent} />}
          {activeTab === "skills" && <SkillsTab agentKey={agentKey} />}
          {activeTab === "memory" && <MemoryTab agentKey={agentKey} />}
          {activeTab === "logs" && <LogsTab agentKey={agentKey} />}
        </div>
      </div>
    </div>
  );
}

export default function AgentsPage() {
  return (
    <Suspense fallback={<div className="text-muted">Loading...</div>}>
      <AgentsRouter />
    </Suspense>
  );
}
