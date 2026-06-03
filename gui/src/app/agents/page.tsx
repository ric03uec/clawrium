"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { Suspense, useState } from "react";
import { useAgent } from "@/hooks";
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

function AgentDetailContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const key = searchParams.get("key");
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  if (!key) {
    return (
      <div className="bg-surface rounded-xl border border-default p-12 text-center text-muted">
        No agent selected. Select an agent from the Dashboard.
      </div>
    );
  }

  return <AgentDetailView agentKey={key} activeTab={activeTab} onTabChange={setActiveTab} />;
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
          onClick={() => router.push("/")}
          className="text-primary hover:underline text-sm"
        >
          Back to Dashboard
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <div className="text-sm text-muted">
        <button onClick={() => router.push("/")} className="hover:text-primary">
          Dashboard
        </button>
        <span className="mx-2">/</span>
        <span className="text-primary-text">{agent.agent_name}</span>
      </div>

      {/* Header — keyed on agent_key so local state (revealed connection
          token, copied flags, pairing-code mutation result) does not leak
          across agents when the user switches via the search-param-only
          route change. */}
      <AgentHeader key={agent.agent_key} agent={agent} />

      {/* Metrics */}
      <AgentMetrics agent={agent} />

      {/* Tab content */}
      <div className="bg-white rounded-xl border border-default shadow-sm overflow-hidden">
        <TabNav active={activeTab} onChange={onTabChange} />
        <div className="min-h-[500px]">
          {activeTab === "overview" && (
            <OverviewTab agent={agent} agentKey={agentKey} />
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

export default function AgentDetailPage() {
  return (
    <Suspense fallback={<div className="text-muted">Loading...</div>}>
      <AgentDetailContent />
    </Suspense>
  );
}
