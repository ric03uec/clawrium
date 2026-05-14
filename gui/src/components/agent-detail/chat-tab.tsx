"use client";

import { useState, useRef, useEffect } from "react";
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
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { data: chatInfo } = useQuery({
    queryKey: ["chat-info", agentKey],
    queryFn: () => api.getChatInfo(agentKey),
  });

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (chatInfo && !chatInfo.supported) {
    return (
      <div className="flex items-center justify-center h-64 text-muted">
        Chat is not supported for this agent type.
      </div>
    );
  }

  const handleSend = async () => {
    if (!input.trim() || sending) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: input.trim(),
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);

    try {
      const response = await api.sendChatMessage(agentKey, userMsg.content);
      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: response,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errorMsg: ChatMessage = {
        role: "assistant",
        content: `Error: ${err instanceof Error ? err.message : "Failed to get response"}`,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex flex-col h-[500px]">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
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
              <span className="animate-pulse">Thinking...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-default p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex gap-2"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message..."
            disabled={sending}
            className="flex-1 rounded-lg border border-default px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary disabled:opacity-50"
          />
          <Button
            variant="primary"
            size="md"
            type="submit"
            disabled={!input.trim() || sending}
          >
            Send
          </Button>
        </form>
      </div>
    </div>
  );
}
