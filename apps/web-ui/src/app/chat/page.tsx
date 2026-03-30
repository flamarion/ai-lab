"use client";

import { useAuth } from "@/lib/auth-context";
import { chat as chatApi, conversations as convApi, type ToolUsed, DEFAULT_PREFS } from "@/lib/api";
import ChatSidebar from "@/components/chat-sidebar";
import ChatMessageComponent from "@/components/chat-message";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Menu, Send, Zap, BookOpen } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  toolsUsed?: ToolUsed[];
  plan?: string;
}

export default function ChatPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [streamingContent, setStreamingContent] = useState("");
  const [sidebarRefresh, setSidebarRefresh] = useState(0);
  // Per-chat overrides (default from user preferences, togglable in input bar)
  const [ragEnabled, setRagEnabled] = useState<boolean | null>(null); // null = use pref default
  const [toolsEnabled, setToolsEnabled] = useState<boolean | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Redirect if not logged in
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  // Load conversation when selected
  useEffect(() => {
    if (!conversationId) return;
    convApi.get(conversationId).then((data) => {
      setMessages(
        data.messages.map((m) => ({
          role: m.role as "user" | "assistant",
          content: m.content,
        }))
      );
    }).catch(() => {});
  }, [conversationId]);

  // Auto-scroll to bottom (instant during streaming to avoid animation jank at high token rates)
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: streamingContent ? "instant" : "smooth" });
  }, [messages, sending, streamingContent]);

  // Auto-resize textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + "px";
  };

  const prefs = (user?.preferences || {}) as Record<string, unknown>;

  const handleSend = async () => {
    if (!input.trim() || sending || !user) return;
    const msg = input.trim();
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";

    setMessages((prev) => [...prev, { role: "user", content: msg }]);
    setSending(true);

    try {
      const savedModel = prefs.model as string | undefined;
      const model = savedModel && savedModel !== "Auto (recommended)" ? savedModel : undefined;

      const params = {
        message: msg,
        model,
        temperature: (prefs.temperature as number) ?? DEFAULT_PREFS.temperature,
        top_p: (prefs.top_p as number) ?? DEFAULT_PREFS.top_p,
        top_k: (prefs.top_k as number) ?? DEFAULT_PREFS.top_k,
        num_predict: (prefs.num_predict as number) ?? DEFAULT_PREFS.num_predict,
        repeat_penalty: (prefs.repeat_penalty as number) ?? DEFAULT_PREFS.repeat_penalty,
        seed: (prefs.seed as number) ?? undefined,
        num_ctx: (prefs.num_ctx as number) ?? undefined,
        system_prompt: (prefs.system_prompt as string) || undefined,
        use_rag: ragEnabled ?? (prefs.use_rag as boolean) ?? DEFAULT_PREFS.use_rag,
        use_tools: toolsEnabled ?? (prefs.use_tools as boolean) ?? DEFAULT_PREFS.use_tools,
        user_id: user.user_id,
        conversation_id: conversationId || undefined,
        history: conversationId ? undefined : messages.map((m) => ({ role: m.role, content: m.content })),
      };

      setStreamingContent("");

      const result = await chatApi.sendStream(
        params,
        (event) => setStatusText(event.detail || event.status),
        (token) => {
          setStatusText("");
          setStreamingContent((prev) => prev + token);
        },
      );

      setStreamingContent("");
      setStatusText("");
      setConversationId(result.conversation_id);
      setSidebarRefresh((n) => n + 1);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: result.response,
          toolsUsed: result.tools_used.length > 0 ? result.tools_used : undefined,
          plan: result.plan || undefined,
        },
      ]);
    } catch (err) {
      setStatusText("");
      setStreamingContent("");
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${err instanceof Error ? err.message : "Something went wrong"}` },
      ]);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const handleNewChat = (id: string | null) => {
    setRagEnabled(null);
    setToolsEnabled(null);
    setMessages([]);
    setConversationId(id);
  };

  const effectiveRag = ragEnabled ?? (prefs.use_rag as boolean) ?? false;
  const effectiveTools = toolsEnabled ?? (prefs.use_tools as boolean) ?? false;

  if (loading || !user) return null;

  return (
    <div className="flex h-screen">
      <ChatSidebar
        currentId={conversationId || undefined}
        onSelect={handleNewChat}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        refreshKey={sidebarRefresh}
      />

      {/* Main chat area */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-border)]">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden p-2 text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
          >
            <Menu size={20} />
          </button>
          <h1
            className="text-lg"
            style={{ fontFamily: "var(--font-display)" }}
          >
            AI Lab
          </h1>
          {effectiveTools && (
            <span className="flex items-center gap-1 text-xs text-[var(--color-accent)] bg-[var(--color-accent-soft)] px-2 py-0.5 rounded-full">
              <Zap size={10} />
              Tools
            </span>
          )}
          {effectiveRag && (
            <span className="flex items-center gap-1 text-xs text-[var(--color-accent)] bg-[var(--color-accent-soft)] px-2 py-0.5 rounded-full">
              <BookOpen size={10} />
              RAG
            </span>
          )}
          <div className="flex-1" />
          <span className="text-xs text-[var(--color-text-muted)]">
            {prefs.model as string || "Auto"}
          </span>
        </header>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center px-4">
              <div className="text-6xl mb-4">🧪</div>
              <h2
                className="text-2xl mb-2"
                style={{ fontFamily: "var(--font-display)" }}
              >
                Hey {user.username}!
              </h2>
              <p className="text-[var(--color-text-muted)] text-sm max-w-md">
                Your personal AI assistant — powered by local models running on your homelab.
              </p>
              <div className="flex flex-wrap justify-center gap-2 mt-6">
                {["Ask me anything", "Help me write", "Explain a concept", "Debug some code"].map((hint) => (
                  <button
                    key={hint}
                    onClick={() => { setInput(hint); inputRef.current?.focus(); }}
                    className="px-4 py-2 rounded-xl text-sm bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-light)] hover:text-[var(--color-text)] transition-colors"
                  >
                    {hint}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
              {messages.map((m, i) => (
                <ChatMessageComponent
                  key={`${conversationId}-${i}-${m.role}`}
                  role={m.role}
                  content={m.content}
                  toolsUsed={m.toolsUsed}
                  plan={m.plan}
                />
              ))}
              {sending && (
                <ChatMessageComponent role="assistant" content={streamingContent} isStreaming statusText={statusText} />
              )}
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-[var(--color-border)] p-4">
          <div className="max-w-3xl mx-auto">
            {/* Per-chat toggles */}
            <div className="flex items-center gap-1 mb-2">
              <button
                onClick={() => setToolsEnabled(!effectiveTools)}
                aria-pressed={effectiveTools}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs transition-colors ${
                  effectiveTools
                    ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)] border border-[var(--color-accent)]"
                    : "bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] border border-[var(--color-border)] hover:border-[var(--color-border-light)]"
                }`}
              >
                <Zap size={10} />
                Tools
              </button>
              <button
                onClick={() => setRagEnabled(!effectiveRag)}
                aria-pressed={effectiveRag}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs transition-colors ${
                  effectiveRag
                    ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)] border border-[var(--color-accent)]"
                    : "bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] border border-[var(--color-border)] hover:border-[var(--color-border-light)]"
                }`}
              >
                <BookOpen size={10} />
                RAG
              </button>
            </div>

            {/* Text input + send */}
            <div className="relative">
              <textarea
                ref={inputRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Type your message..."
                rows={1}
                className="w-full resize-none bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-2xl px-4 py-3 pr-12 text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-border-light)] transition-colors"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || sending}
                className="absolute right-3 bottom-3 p-1.5 rounded-lg bg-[var(--color-accent)] text-[var(--color-bg)] disabled:opacity-30 hover:bg-[var(--color-accent-hover)] transition-colors"
              >
                <Send size={16} />
              </button>
            </div>
          </div>
          <p className="text-center text-xs text-[var(--color-text-muted)] mt-2">
            AI can make mistakes. Verify important information.
          </p>
        </div>
      </main>
    </div>
  );
}
