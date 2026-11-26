"use client";

import { useState, useCallback, useRef } from "react";
import { Button, Input } from "@/design-system";

interface ExecResult {
  stdout: string;
  stderr: string;
  return_code: number;
  command: string;
  timestamp: string;
}

interface ExecTabProps {
  agentKey: string;
}

export function ExecTab({ agentKey }: ExecTabProps) {
  const [command, setCommand] = useState("");
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<ExecResult[]>([]);
  const outputRef = useRef<HTMLDivElement>(null);

  const handleExec = useCallback(async () => {
    const trimmed = command.trim();
    if (!trimmed || running) return;

    setRunning(true);
    try {
      const argv = trimmed.split(/\s+/);
      const resp = await fetch(`/api/agents/${agentKey}/exec`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: argv, timeout: 30 }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: "Request failed" }));
        setHistory((prev) => [
          {
            stdout: "",
            stderr: err.detail || `HTTP ${resp.status}`,
            return_code: -1,
            command: trimmed,
            timestamp: new Date().toLocaleTimeString(),
          },
          ...prev,
        ]);
        return;
      }

      const data = await resp.json();
      setHistory((prev) => [
        {
          stdout: data.stdout,
          stderr: data.stderr,
          return_code: data.return_code,
          command: trimmed,
          timestamp: new Date().toLocaleTimeString(),
        },
        ...prev,
      ]);
      setCommand("");
    } finally {
      setRunning(false);
    }
  }, [agentKey, command, running]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleExec();
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-surface rounded-xl border border-default p-4 space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-primary-text mb-1">
            Run Command
          </h3>
          <p className="text-xs text-muted">
            Execute commands via the agent&apos;s native CLI on its host.
            Equivalent to{" "}
            <code className="bg-panel px-1 py-0.5 rounded">
              clawctl agent exec {agentKey} -- &lt;args&gt;
            </code>
          </p>
        </div>

        <div className="flex gap-2">
          <Input trackingId="agent-detail.exec.command" size="sm"
            type="text"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="e.g. --version, config show, status"
            className="flex-1 text-sm border border-default rounded px-3 py-2 bg-white text-primary-text font-mono placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary"
            disabled={running}
            aria-label="Command to execute"
          />
          <Button trackingId="agent-detail.exec.run"
            size="sm"
            disabled={!command.trim() || running}
            onClick={handleExec}
          >
            {running ? "Running..." : "Run"}
          </Button>
        </div>
      </div>

      {/* Command history */}
      <div ref={outputRef} className="space-y-2">
        {history.length === 0 ? (
          <div className="bg-surface rounded-xl border border-default p-8 text-center text-muted text-sm">
            No commands executed yet. Type a command above and press Enter.
          </div>
        ) : (
          history.map((result, idx) => (
            <div
              key={`${result.timestamp}-${idx}`}
              className="bg-surface rounded-xl border border-default p-3 space-y-2"
            >
              <div className="flex items-center justify-between">
                <code className="text-xs font-mono text-primary-text">
                  $ {result.command}
                </code>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted">
                    {result.timestamp}
                  </span>
                  <span
                    className={`text-xs px-1.5 py-0.5 rounded font-mono ${
                      result.return_code === 0
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-red-50 text-red-700"
                    }`}
                  >
                    rc={result.return_code}
                  </span>
                </div>
              </div>
              {result.stdout ? (
                <pre className="text-xs font-mono text-secondary whitespace-pre-wrap bg-panel rounded p-2 max-h-48 overflow-auto">
                  {result.stdout}
                </pre>
              ) : null}
              {result.stderr ? (
                <pre className="text-xs font-mono text-status-warning-text whitespace-pre-wrap bg-panel rounded p-2 max-h-48 overflow-auto">
                  {result.stderr}
                </pre>
              ) : null}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
