"use client";

import { type ToolUsed } from "@/lib/api";
import { Wrench, ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";

interface Props {
  role: "user" | "assistant";
  content: string;
  toolsUsed?: ToolUsed[];
  isStreaming?: boolean;
}

export default function ChatMessage({ role, content, toolsUsed, isStreaming }: Props) {
  const [toolsOpen, setToolsOpen] = useState(false);

  return (
    <div className={`animate-fade-in ${role === "user" ? "flex justify-end" : ""}`}>
      <div
        className={`max-w-2xl ${
          role === "user"
            ? "bg-[var(--color-user-bubble)] rounded-2xl rounded-br-md px-4 py-3"
            : "py-3"
        }`}
      >
        {/* Tool usage indicator */}
        {toolsUsed && toolsUsed.length > 0 && (
          <div className="mb-3">
            <button
              onClick={() => setToolsOpen(!toolsOpen)}
              className="flex items-center gap-2 text-xs text-[var(--color-accent)] hover:text-[var(--color-accent-hover)] transition-colors"
            >
              <Wrench size={12} />
              Used {toolsUsed.length} tool{toolsUsed.length > 1 ? "s" : ""}
              {toolsOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
            {toolsOpen && (
              <div className="mt-2 space-y-2 animate-fade-in">
                {toolsUsed.map((t, i) => (
                  <div key={i} className="bg-[var(--color-bg-tertiary)] rounded-lg p-3 text-xs border border-[var(--color-border)]">
                    <div className="font-medium text-[var(--color-accent)] mb-1">
                      {t.name}({Object.entries(t.arguments).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})
                    </div>
                    <pre className="text-[var(--color-text-secondary)] whitespace-pre-wrap font-[var(--font-mono)] overflow-x-auto">
                      {t.result.slice(0, 500)}{t.result.length > 500 ? "..." : ""}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Message content */}
        <div className="message-content text-[0.9375rem] leading-relaxed">
          {content}
        </div>

        {/* Streaming indicator */}
        {isStreaming && (
          <div className="flex gap-1 mt-2">
            <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-text-muted)]" />
            <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-text-muted)]" />
            <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-text-muted)]" />
          </div>
        )}
      </div>
    </div>
  );
}
