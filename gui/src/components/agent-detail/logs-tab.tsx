"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { LogEntry } from "@/lib/types";

interface LogsTabProps {
  agentKey: string;
}

const PRIORITY_LABELS: Record<string, { label: string; color: string }> = {
  "0": { label: "EMERG", color: "text-red-700" },
  "1": { label: "ALERT", color: "text-red-600" },
  "2": { label: "CRIT", color: "text-red-600" },
  "3": { label: "ERR", color: "text-red-500" },
  "4": { label: "WARN", color: "text-amber-600" },
  "5": { label: "NOTICE", color: "text-blue-600" },
  "6": { label: "INFO", color: "text-secondary" },
  "7": { label: "DEBUG", color: "text-muted" },
};

export function LogsTab({ agentKey }: LogsTabProps) {
  const [lines, setLines] = useState(100);
  const [filter, setFilter] = useState("");

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["agent-logs", agentKey, lines],
    queryFn: () => api.getAgentLogs(agentKey, lines),
    refetchInterval: 15_000,
  });

  const logs = data?.logs || [];
  const filteredLogs = filter
    ? logs.filter((l) => l.message.toLowerCase().includes(filter.toLowerCase()))
    : logs;

  return (
    <div className="p-4 h-[500px] flex flex-col">
      {/* Controls */}
      <div className="flex items-center gap-3 mb-3">
        <input
          type="text"
          placeholder="Filter logs..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="flex-1 max-w-xs rounded-lg border border-default px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
        />
        <select
          value={lines}
          onChange={(e) => setLines(Number(e.target.value))}
          className="rounded-lg border border-default px-3 py-1.5 text-sm"
        >
          <option value={50}>50 lines</option>
          <option value={100}>100 lines</option>
          <option value={200}>200 lines</option>
          <option value={500}>500 lines</option>
        </select>
        <Button variant="ghost" size="sm" onClick={() => refetch()}>
          Refresh
        </Button>
      </div>

      {/* Log content */}
      <Card padding="sm" className="flex-1 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center h-full text-muted text-sm">
            Loading logs...
          </div>
        ) : data?.error ? (
          <div className="flex items-center justify-center h-full text-muted text-sm">
            <p>Failed to fetch logs: {data.error}</p>
          </div>
        ) : filteredLogs.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted text-sm">
            {filter ? "No logs match filter" : "No logs available"}
          </div>
        ) : (
          <div className="h-full overflow-y-auto font-mono text-xs">
            {filteredLogs.map((entry, i) => (
              <LogLine key={i} entry={entry} />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function LogLine({ entry }: { entry: LogEntry }) {
  const priority = PRIORITY_LABELS[entry.priority] || PRIORITY_LABELS["6"];
  const timestamp = entry.timestamp
    ? formatTimestamp(entry.timestamp)
    : "";

  return (
    <div className="flex gap-2 py-0.5 hover:bg-surface px-2 rounded">
      {timestamp && (
        <span className="text-muted shrink-0 w-20">{timestamp}</span>
      )}
      <span className={`shrink-0 w-12 ${priority.color}`}>
        [{priority.label}]
      </span>
      <span className="text-primary-text break-all">{entry.message}</span>
    </div>
  );
}

function formatTimestamp(ts: string): string {
  // journalctl __REALTIME_TIMESTAMP is in microseconds
  const num = Number(ts);
  if (num > 0) {
    const date = new Date(num / 1000);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
  return ts.slice(11, 19); // Extract HH:MM:SS from ISO string
}
