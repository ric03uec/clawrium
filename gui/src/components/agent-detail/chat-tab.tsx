"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ChatMessage } from "@/lib/types";
import { Button } from "@/components/ui/button";

interface ChatTabProps {
  agentKey: string;
  agentName: string;
}

export function ChatTab({ agentKey, agentName }: ChatTabProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [thinkingElapsed, setThinkingElapsed] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const { data: chatInfo } = useQuery({
    queryKey: ["chat-info", agentKey],
    queryFn: () => api.getChatInfo(agentKey),
  });

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Elapsed-time ticker while sending
  useEffect(() => {
    if (!sending) {
      setThinkingElapsed(0);
      return;
    }
    const id = setInterval(() => {
      setThinkingElapsed((t) => t + 1);
    }, 1000);
    return () => clearInterval(id);
  }, [sending]);

  // Auto-resize textarea (1–8 rows)
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  const focusTextarea = useCallback(() => textareaRef.current?.focus(), []);

  const handleStop = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
  }, []);

  const handleSend = useCallback(async () => {
    if (!input.trim() || sending) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: input.trim(),
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);
    focusTextarea();

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await api.sendChatMessage(agentKey, userMsg.content, {
        signal: controller.signal,
      });
      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: response,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        // Append stopped marker to partial message — but since we haven't
        // started streaming partials yet (Phase 1), just note it.
        const stoppedMsg: ChatMessage = {
          role: "assistant",
          content: "_Stopped by user._",
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, stoppedMsg]);
      } else {
        const errorMsg: ChatMessage = {
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : "Failed to get response"}`,
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, errorMsg]);
      }
    } finally {
      setSending(false);
      abortRef.current = null;
      focusTextarea();
    }
  }, [input, sending, agentKey, focusTextarea]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      const isEnter = e.key === "Enter";
      const isShift = e.shiftKey;

      // Enter submits; Shift+Enter inserts newline
      if (isEnter && !isShift) {
        e.preventDefault();
        handleSend();
      }
      // Shift+Enter falls through — browser inserts newline naturally
    },
    [handleSend],
  );

  if (chatInfo && !chatInfo.supported) {
    return (
      <div className="flex items-center justify-center h-64 text-muted">
        Chat is not supported for this agent type.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-20rem)] min-h-[400px]">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-muted text-sm">
            Start a conversation with {agentName}
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[75%] rounded-lg px-4 py-2.5 text-sm ${
                msg.role === "user"
                  ? "bg-primary text-white"
                  : "bg-surface border border-default text-primary-text"
              }`}
            >
              <pre className="whitespace-pre-wrap font-sans">{msg.content}</pre>
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="bg-surface border border-default rounded-lg px-4 py-2.5 text-sm text-muted">
              <span className="inline-flex items-center gap-2">
                <span className="inline-flex gap-0.5">
                  <span className="w-1.5 h-1.5 bg-current rounded-full animate-pulse" />
                  <span className="w-1.5 h-1.5 bg-current rounded-full animate-pulse [animation-delay:200ms]" />
                  <span className="w-1.5 h-1.5 bg-current rounded-full animate-pulse [animation-delay:400ms]" />
                </span>
                Thinking… {thinkingElapsed}s
              </span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-default p-4">
        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message..."
            rows={1}
            className="flex-1 rounded-lg border border-default px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary resize-none overflow-y-auto max-h-[234px] min-h-[24px]"
          />
          {sending ? (
            <Button
              variant="danger"
              size="md"
              onClick={handleStop}
              type="button"
            >
              Stop
            </Button>
          ) : (
            <Button
              variant="primary"
              size="md"
              onClick={() => {
                if (input.trim() && !sending) handleSend();
              }}
              disabled={!input.trim()}
              type="button"
            >
              Send
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
