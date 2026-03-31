"use client";

import { useAuth } from "@/lib/auth-context";
import { chat as chatApi, conversations as convApi, type ToolUsed, DEFAULT_PREFS } from "@/lib/api";
import ChatSidebar from "@/components/chat-sidebar";
import ChatMessageComponent from "@/components/chat-message";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Menu, Send, Zap, BookOpen, Image as ImageIcon, X } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  images?: string[];
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
  const [pendingImages, setPendingImages] = useState<string[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Redirect if not logged in
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  // Refresh sidebar when the tab regains focus (picks up fire-and-forget completions)
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") setSidebarRefresh((n) => n + 1);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  // Load conversation when selected
  useEffect(() => {
    if (!conversationId) return;
    convApi.get(conversationId).then((data) => {
      setMessages(
        data.messages.map((m) => ({
          role: m.role as "user" | "assistant",
          content: m.content,
          images: m.images?.length ? m.images : undefined,
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

  const readFileAsDataUrl = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result;
        if (typeof result !== "string" || !result.includes(",")) {
          reject(new Error("Unexpected FileReader result format"));
          return;
        }
        resolve(result);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

  const addImages = async (files: FileList | File[]) => {
    const imageFiles = Array.from(files).filter((f) => f.type.startsWith("image/"));
    if (imageFiles.length === 0) return;
    const dataUrls = await Promise.all(imageFiles.map(readFileAsDataUrl));
    setPendingImages((prev) => [...prev, ...dataUrls]);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files.length > 0) {
      await addImages(e.dataTransfer.files).catch(console.error);
    }
  };

  const prefs = (user?.preferences || {}) as Record<string, unknown>;

  const handleSend = async () => {
    if ((!input.trim() && pendingImages.length === 0) || sending || !user) return;
    const msg = input.trim();
    const imageDataUrls = pendingImages.length > 0 ? [...pendingImages] : undefined;
    // Strip data URL prefix for the API — Ollama expects raw base64
    const apiImages = imageDataUrls?.map((url) => url.split(",")[1]);
    setInput("");
    setPendingImages([]);
    if (inputRef.current) inputRef.current.style.height = "auto";

    setMessages((prev) => [...prev, { role: "user", content: msg, images: imageDataUrls }]);
    setSending(true);

    // Create an AbortController so navigating away can disconnect the
    // SSE stream without blocking the UI.  The server-side generation
    // continues via fire-and-forget.
    const controller = new AbortController();
    abortRef.current = controller;

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
        images: apiImages,
      };

      setStreamingContent("");

      const result = await chatApi.sendStream(
        params,
        (event) => setStatusText(event.detail || event.status),
        (token) => {
          setStatusText("");
          setStreamingContent((prev) => prev + token);
        },
        controller.signal,
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
      // AbortError is expected when navigating to a new chat — don't show it
      if (err instanceof DOMException && err.name === "AbortError") return;
      setStatusText("");
      setStreamingContent("");
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${err instanceof Error ? err.message : "Something went wrong"}` },
      ]);
    } finally {
      abortRef.current = null;
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const handleNewChat = (id: string | null) => {
    const wasStreaming = !!abortRef.current;
    // Abort in-flight stream — server continues via fire-and-forget
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setSending(false);
    setStreamingContent("");
    setStatusText("");
    setRagEnabled(null);
    setToolsEnabled(null);
    setPendingImages([]);
    setMessages([]);
    setConversationId(id);
    if (!id) {
      setSidebarRefresh((n) => n + 1);
      // If we aborted a generation, it's still finishing server-side.
      // Poll a few times so the conversation appears once persisted.
      if (wasStreaming) {
        setTimeout(() => setSidebarRefresh((n) => n + 1), 3000);
        setTimeout(() => setSidebarRefresh((n) => n + 1), 8000);
      }
    }
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
                  images={m.images}
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

            {/* Image previews */}
            {pendingImages.length > 0 && (
              <div className="flex gap-2 mb-2 flex-wrap">
                {pendingImages.map((img, i) => (
                  <div key={i} className="relative group">
                    <img
                      src={img}
                      alt={`Attachment ${i + 1}`}
                      className="h-16 w-16 object-cover rounded-lg border border-[var(--color-border)]"
                    />
                    <button
                      onClick={() => setPendingImages((prev) => prev.filter((_, j) => j !== i))}
                      className="absolute -top-1.5 -right-1.5 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <X size={10} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Text input + send */}
            <div
              className="relative"
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={(e) => { if (e.target.files) void addImages(e.target.files).catch(console.error); e.target.value = ""; }}
              />
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
                onPaste={(e) => {
                  const files = Array.from(e.clipboardData.items)
                    .filter((item) => item.type.startsWith("image/"))
                    .map((item) => item.getAsFile())
                    .filter((f): f is File => f !== null);
                  if (files.length > 0) {
                    e.preventDefault();
                    void addImages(files).catch(console.error);
                  }
                }}
                placeholder={pendingImages.length > 0 ? "Add a message about this image..." : "Type your message..."}
                rows={1}
                className="w-full resize-none bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-2xl px-11 py-3 pr-12 text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-border-light)] transition-colors"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="absolute left-3 bottom-3 p-1.5 rounded-lg text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
                title="Attach image"
              >
                <ImageIcon size={16} />
              </button>
              <button
                onClick={handleSend}
                disabled={(!input.trim() && pendingImages.length === 0) || sending}
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
