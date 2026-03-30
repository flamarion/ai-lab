"use client";

import { useAuth } from "@/lib/auth-context";
import { type AuthResponse, DEFAULT_PREFS } from "@/lib/api";
import { chat as chatApi, documents as docsApi, auth as authApi, memory as memApi, type Memory } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Upload, Trash2, FileText } from "lucide-react";
import Link from "next/link";

export default function SettingsPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  if (loading || !user) return null;

  // Key on user_id so the form remounts (and re-initializes state) on user switch
  return <SettingsForm key={user.user_id} user={user} />;
}

function SettingsForm({ user }: { user: AuthResponse }) {
  const { updatePreferences } = useAuth();
  const [models, setModels] = useState<string[]>([]);
  const [docs, setDocs] = useState<{ id: string; source: string; num_chunks: number; user_id: string | null; is_private: boolean }[]>([]);
  const [saving, setSaving] = useState(false);
  const [pinSection, setPinSection] = useState({ current: "", new_pin: "", message: "" });

  // Local form state — initialized from user.preferences which is guaranteed
  // to be loaded because this component only mounts after auth completes.
  const prefs = (user.preferences || {}) as Record<string, unknown>;
  const [model, setModel] = useState((prefs.model as string) || "Auto (recommended)");
  const [temperature, setTemperature] = useState((prefs.temperature as number) ?? DEFAULT_PREFS.temperature);
  const [topP, setTopP] = useState((prefs.top_p as number) ?? DEFAULT_PREFS.top_p);
  const [topK, setTopK] = useState((prefs.top_k as number) ?? DEFAULT_PREFS.top_k);
  const [numPredict, setNumPredict] = useState((prefs.num_predict as number) ?? DEFAULT_PREFS.num_predict);
  const [repeatPenalty, setRepeatPenalty] = useState((prefs.repeat_penalty as number) ?? DEFAULT_PREFS.repeat_penalty);
  const [systemPrompt, setSystemPrompt] = useState((prefs.system_prompt as string) || "");
  const [useRag, setUseRag] = useState((prefs.use_rag as boolean) ?? DEFAULT_PREFS.use_rag);
  const [useTools, setUseTools] = useState((prefs.use_tools as boolean) ?? DEFAULT_PREFS.use_tools);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [newMemory, setNewMemory] = useState("");

  useEffect(() => {
    chatApi.models().then((d) => setModels(d.models)).catch(() => {});
    docsApi.list(user.user_id).then((d) => setDocs(d.documents)).catch(() => {});
    memApi.list(user.user_id).then((d) => setMemories(d.memories)).catch(() => {});
  }, [user.user_id]);

  // Auto-save on change (debounced, skips initial mount).
  // Saves are serialized: a new save waits for the previous one to complete,
  // preventing out-of-order PATCHes from overwriting newer values.
  const hasInteracted = useRef(false);
  const pendingSave = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => {
    if (!hasInteracted.current) {
      hasInteracted.current = true;
      return;
    }
    const timeout = setTimeout(() => {
      const prefs = {
        model, temperature, top_p: topP, top_k: topK, num_predict: numPredict,
        repeat_penalty: repeatPenalty, system_prompt: systemPrompt,
        use_rag: useRag, use_tools: useTools,
      };
      setSaving(true);
      pendingSave.current = pendingSave.current
        .then(() => updatePreferences(prefs))
        .catch(() => {})
        .finally(() => setSaving(false));
    }, 500);
    return () => clearTimeout(timeout);
  }, [model, temperature, topP, topK, numPredict, repeatPenalty, systemPrompt, useRag, useTools]); // eslint-disable-line react-hooks/exhaustive-deps

  const [uploadPrivate, setUploadPrivate] = useState(false);

  const handleUpload = async (files: FileList) => {
    for (const file of Array.from(files)) {
      try {
        await docsApi.ingest(file, user.user_id, uploadPrivate);
      } catch {
        alert(`Failed to upload ${file.name}`);
      }
    }
    // Refresh list once after all uploads complete
    docsApi.list(user.user_id).then((d) => setDocs(d.documents)).catch(() => {});
  };

  const handleDeleteDoc = async (id: string) => {
    if (!confirm("Delete this document? This cannot be undone.")) return;
    await docsApi.delete(id, user.user_id).catch(() => {});
    setDocs((prev) => prev.filter((d) => d.id !== id));
  };

  const handleChangePin = async () => {
    if (pinSection.new_pin.length < 4) {
      setPinSection((s) => ({ ...s, message: "PIN must be at least 4 digits" }));
      return;
    }
    try {
      await authApi.changePin(user.user_id, pinSection.current, pinSection.new_pin);
      setPinSection({ current: "", new_pin: "", message: "PIN updated!" });
    } catch (err) {
      setPinSection((s) => ({ ...s, message: err instanceof Error ? err.message : "Failed" }));
    }
  };

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="sticky top-0 z-10 bg-[var(--color-bg)]/80 backdrop-blur border-b border-[var(--color-border)] px-4 py-3">
        <div className="max-w-2xl mx-auto flex items-center gap-3">
          <Link href="/chat" className="p-2 text-[var(--color-text-muted)] hover:text-[var(--color-text)]">
            <ArrowLeft size={20} />
          </Link>
          <h1 className="text-lg font-semibold">Settings</h1>
          <div className="flex-1" />
          {saving && (
            <span className="text-xs text-[var(--color-text-muted)]">Saving...</span>
          )}
        </div>
      </header>

      <div className="max-w-2xl mx-auto px-4 py-8 space-y-8">
        {/* Model */}
        <Section title="Model">
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full px-4 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)]"
          >
            <option>Auto (recommended)</option>
            {models.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
          <p className="text-xs text-[var(--color-text-muted)] mt-1">
            Auto routes code prompts to qwen3.5 and general prompts to mistral.
          </p>
        </Section>

        {/* Temperature */}
        <Section title="Temperature">
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={0} max={1} step={0.1}
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value))}
              className="flex-1 accent-[var(--color-accent)]"
            />
            <span className="text-sm font-mono w-8 text-center">{temperature}</span>
          </div>
          <p className="text-xs text-[var(--color-text-muted)] mt-1">
            Higher = more creative, lower = more focused.
          </p>
        </Section>

        {/* Advanced */}
        <Section title="Advanced">
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-[var(--color-text-secondary)] mb-1">Top P</label>
              <div className="flex items-center gap-4">
                <input type="range" min={0} max={1} step={0.05} value={topP} onChange={(e) => setTopP(parseFloat(e.target.value))} className="flex-1 accent-[var(--color-accent)]" />
                <span className="text-sm font-mono w-8 text-center">{topP}</span>
              </div>
            </div>
            <div>
              <label className="block text-sm text-[var(--color-text-secondary)] mb-1">Top K</label>
              <div className="flex items-center gap-4">
                <input type="range" min={1} max={100} step={1} value={topK} onChange={(e) => setTopK(parseInt(e.target.value))} className="flex-1 accent-[var(--color-accent)]" />
                <span className="text-sm font-mono w-8 text-center">{topK}</span>
              </div>
              <p className="text-xs text-[var(--color-text-muted)] mt-1">
                Limits token selection to top K candidates. Lower = more focused.
              </p>
            </div>
            <div>
              <label className="block text-sm text-[var(--color-text-secondary)] mb-1">Max response length</label>
              <div className="flex items-center gap-4">
                <input type="range" min={64} max={4096} step={64} value={numPredict} onChange={(e) => setNumPredict(parseInt(e.target.value))} className="flex-1 accent-[var(--color-accent)]" />
                <span className="text-sm font-mono w-12 text-center">{numPredict}</span>
              </div>
            </div>
            <div>
              <label className="block text-sm text-[var(--color-text-secondary)] mb-1">Repeat penalty</label>
              <div className="flex items-center gap-4">
                <input type="range" min={0.5} max={2.0} step={0.05} value={repeatPenalty} onChange={(e) => setRepeatPenalty(parseFloat(e.target.value))} className="flex-1 accent-[var(--color-accent)]" />
                <span className="text-sm font-mono w-8 text-center">{repeatPenalty}</span>
              </div>
              <p className="text-xs text-[var(--color-text-muted)] mt-1">
                Penalizes repeated tokens. Higher = less repetition. 1.0 = off.
              </p>
            </div>
            <div>
              <label className="block text-sm text-[var(--color-text-secondary)] mb-1">System prompt</label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={3}
                className="w-full px-4 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text)] text-sm focus:outline-none focus:border-[var(--color-accent)] resize-none"
                placeholder="e.g. You are a helpful cooking assistant"
              />
            </div>
          </div>
        </Section>

        {/* Toggles */}
        <Section title="Features">
          <div className="space-y-3">
            <Toggle label="Use documents (RAG)" description="Ground answers in your uploaded documents" checked={useRag} onChange={setUseRag} />
            <Toggle label="Use tools" description="Calculator, unit converter, web fetch, MCP tools. Requires llama3.1 or qwen3.5." checked={useTools} onChange={setUseTools} />
          </div>
        </Section>

        {/* Memory */}
        <Section title="Memory">
          <p className="text-xs text-[var(--color-text-muted)] mb-3">
            Facts the AI remembers about you across conversations. The AI can also learn new things automatically.
          </p>
          {memories.map((m) => (
            <div key={m.id} className="flex items-start gap-2 px-3 py-2 rounded-lg bg-[var(--color-bg-secondary)] text-sm mb-1.5">
              <span className="flex-1">{m.content}</span>
              <button
                onClick={async () => {
                  if (!confirm("Delete this memory?")) return;
                  await memApi.delete(m.id, user.user_id);
                  setMemories((prev) => prev.filter((x) => x.id !== m.id));
                }}
                className="text-[var(--color-text-muted)] hover:text-[var(--color-error)] shrink-0 mt-0.5"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
          <div className="flex gap-2 mt-2">
            <input
              type="text"
              value={newMemory}
              onChange={(e) => setNewMemory(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newMemory.trim()) {
                  memApi.add(user.user_id, newMemory.trim()).then((r) => {
                    setMemories((prev) => [...prev, { id: r.id, content: newMemory.trim(), created_at: "", updated_at: "" }]);
                    setNewMemory("");
                  });
                }
              }}
              placeholder="e.g. I prefer concise responses"
              className="flex-1 px-3 py-2 rounded-lg bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-sm text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)]"
            />
            <button
              onClick={async () => {
                if (!newMemory.trim()) return;
                const r = await memApi.add(user.user_id, newMemory.trim());
                setMemories((prev) => [...prev, { id: r.id, content: newMemory.trim(), created_at: "", updated_at: "" }]);
                setNewMemory("");
              }}
              disabled={!newMemory.trim()}
              className="px-3 py-2 rounded-lg bg-[var(--color-accent)] text-[var(--color-bg)] text-sm disabled:opacity-30"
            >
              Add
            </button>
          </div>
        </Section>

        {/* Documents */}
        <Section title="Documents">
          <p className="text-xs text-[var(--color-text-muted)] mb-3">
            Upload documents for RAG. Supports PDF, DOCX, XLSX, text, code.
          </p>
          <div className="flex items-center gap-4 mb-2">
            <label className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl border border-dashed border-[var(--color-border)] text-sm text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] transition-colors cursor-pointer">
              <Upload size={16} />
              Upload files
              <input
                type="file"
                multiple
                className="hidden"
                onChange={(e) => e.target.files && handleUpload(e.target.files)}
              />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)] cursor-pointer select-none whitespace-nowrap">
              <input
                type="checkbox"
                checked={uploadPrivate}
                onChange={(e) => setUploadPrivate(e.target.checked)}
                className="accent-[var(--color-accent)]"
              />
              Private
            </label>
          </div>
          {docs.length > 0 && (
            <div className="mt-3 space-y-1">
              {docs.map((d) => (
                <div key={d.id} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--color-bg-secondary)] text-sm">
                  <FileText size={14} className="text-[var(--color-text-muted)]" />
                  <span className="flex-1 truncate">{d.source}</span>
                  {d.is_private && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--color-accent)] text-white leading-none">private</span>
                  )}
                  <span className="text-xs text-[var(--color-text-muted)]">{d.num_chunks} chunks</span>
                  <button onClick={() => handleDeleteDoc(d.id)} className="text-[var(--color-text-muted)] hover:text-[var(--color-error)]">
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Change PIN */}
        <Section title="Account">
          <div className="space-y-3">
            <input
              type="password"
              placeholder="Current PIN"
              value={pinSection.current}
              onChange={(e) => setPinSection((s) => ({ ...s, current: e.target.value, message: "" }))}
              className="w-full px-4 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
            />
            <input
              type="password"
              placeholder="New PIN (4-8 digits)"
              value={pinSection.new_pin}
              onChange={(e) => setPinSection((s) => ({ ...s, new_pin: e.target.value, message: "" }))}
              className="w-full px-4 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text)] text-sm focus:outline-none focus:border-[var(--color-accent)]"
            />
            <button onClick={handleChangePin} className="px-4 py-2 rounded-lg bg-[var(--color-bg-hover)] text-sm hover:bg-[var(--color-bg-tertiary)] transition-colors">
              Update PIN
            </button>
            {pinSection.message && (
              <p className={`text-sm ${pinSection.message.includes("updated") ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                {pinSection.message}
              </p>
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider mb-3">{title}</h2>
      {children}
    </section>
  );
}

function Toggle({ label, description, checked, onChange }: {
  label: string; description: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between py-2 cursor-pointer group">
      <div>
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-[var(--color-text-muted)]">{description}</div>
      </div>
      <div
        onClick={() => onChange(!checked)}
        className={`w-10 h-6 rounded-full transition-colors relative ${
          checked ? "bg-[var(--color-accent)]" : "bg-[var(--color-border)]"
        }`}
      >
        <div className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-transform ${
          checked ? "translate-x-5" : "translate-x-1"
        }`} />
      </div>
    </label>
  );
}
