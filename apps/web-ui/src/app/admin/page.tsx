"use client";

import { useAuth } from "@/lib/auth-context";
import { admin as adminApi, mcp as mcpApi, secrets as secretsApi, type AdminUser, type MCPServer } from "@/lib/api";
import JsonEditor from "@/components/json-editor";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Plus, Trash2, Shield, ShieldOff, Baby, RefreshCw, Eye, EyeOff, Key, Edit2 } from "lucide-react";
import Link from "next/link";

export default function AdminPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && (!user || !user.is_admin)) router.replace("/chat");
  }, [user, loading, router]);

  if (loading || !user || !user.is_admin) return null;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 bg-[var(--color-bg)]/80 backdrop-blur border-b border-[var(--color-border)] px-4 py-3">
        <div className="max-w-3xl mx-auto flex items-center gap-3">
          <Link href="/chat" className="p-2 text-[var(--color-text-muted)] hover:text-[var(--color-text)]">
            <ArrowLeft size={20} />
          </Link>
          <h1 className="text-lg font-semibold">Admin</h1>
        </div>
      </header>

      <div className="max-w-3xl mx-auto px-4 py-8 space-y-10">
        <UserManagement userId={user.user_id} />
        <MCPManagement userId={user.user_id} />
        <SecretsManagement userId={user.user_id} />
      </div>
    </div>
  );
}

// --- User Management ---

function UserManagement({ userId }: { userId: string }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newUser, setNewUser] = useState({ username: "", pin: "", isChild: false });
  const [resetPins, setResetPins] = useState<Record<string, string>>({});

  const reload = () => adminApi.listUsers(userId).then((d) => setUsers(d.users)).catch(() => {});

  useEffect(() => { reload(); }, [userId]);

  const handleCreate = async () => {
    if (!newUser.username.trim() || newUser.pin.length < 4) return;
    await adminApi.createUser(userId, newUser.username.trim(), newUser.pin, newUser.isChild);
    setNewUser({ username: "", pin: "", isChild: false });
    setShowCreate(false);
    reload();
  };

  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">Users</h2>
        <button onClick={() => setShowCreate(!showCreate)} className="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]">
          <Plus size={14} /> Add user
        </button>
      </div>

      {showCreate && (
        <div className="bg-[var(--color-bg-secondary)] rounded-xl p-4 mb-4 space-y-3 animate-fade-in border border-[var(--color-border)]">
          <input type="text" placeholder="Username" value={newUser.username} onChange={(e) => setNewUser((s) => ({ ...s, username: e.target.value }))} className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)]" />
          <input type="password" placeholder="PIN (4+ digits)" value={newUser.pin} onChange={(e) => setNewUser((s) => ({ ...s, pin: e.target.value }))} className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)]" />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={newUser.isChild} onChange={(e) => setNewUser((s) => ({ ...s, isChild: e.target.checked }))} className="accent-[var(--color-accent)]" />
            Child account
          </label>
          <button onClick={handleCreate} className="px-4 py-2 rounded-lg bg-[var(--color-accent)] text-[var(--color-bg)] text-sm font-medium">Create</button>
        </div>
      )}

      <div className="space-y-2">
        {users.map((u) => (
          <div key={u.id} className="flex items-center gap-3 px-4 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
            <div className="flex-1">
              <div className="text-sm font-medium flex items-center gap-2">
                {u.username}
                {u.is_admin && <span className="text-xs text-[var(--color-accent)]">admin</span>}
                {u.is_child && <span className="text-xs text-[var(--color-warning)]">child</span>}
              </div>
            </div>
            {u.id !== userId && (
              <div className="flex items-center gap-1">
                <button
                  onClick={() => adminApi.toggleAdmin(userId, u.id, !u.is_admin).then(reload)}
                  title={u.is_admin ? "Remove admin" : "Make admin"}
                  className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-text-muted)]"
                >
                  {u.is_admin ? <ShieldOff size={14} /> : <Shield size={14} />}
                </button>
                <button
                  onClick={() => adminApi.toggleChild(userId, u.id, !u.is_child).then(reload)}
                  title={u.is_child ? "Remove child flag" : "Set as child"}
                  className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-text-muted)]"
                >
                  <Baby size={14} />
                </button>
                {/* Reset PIN inline */}
                {resetPins[u.id] !== undefined ? (
                  <div className="flex items-center gap-1">
                    <input
                      type="password" placeholder="New PIN" value={resetPins[u.id]}
                      onChange={(e) => setResetPins((s) => ({ ...s, [u.id]: e.target.value }))}
                      className="w-20 px-2 py-1 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-xs"
                    />
                    <button onClick={async () => { await adminApi.resetPin(userId, u.id, resetPins[u.id]); setResetPins((s) => { const n = { ...s }; delete n[u.id]; return n; }); }} className="text-xs text-[var(--color-accent)]">Save</button>
                  </div>
                ) : (
                  <button onClick={() => setResetPins((s) => ({ ...s, [u.id]: "" }))} title="Reset PIN" className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-text-muted)]">
                    <Key size={14} />
                  </button>
                )}
                <button
                  onClick={() => { if (confirm(`Delete ${u.username}?`)) adminApi.deleteUser(userId, u.id).then(reload); }}
                  className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-text-muted)] hover:text-[var(--color-error)]"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// --- MCP Management ---

function MCPManagement({ userId }: { userId: string }) {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [configJson, setConfigJson] = useState("");
  const [configLoaded, setConfigLoaded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const reload = async () => {
    try {
      const [serverData, configData] = await Promise.all([
        mcpApi.listServers(userId),
        mcpApi.getFullConfig(userId),
      ]);
      setServers(serverData.servers);
      // Only update the editor if not actively editing
      if (!editing) {
        setConfigJson(JSON.stringify(configData, null, 2));
      }
      setConfigLoaded(true);
    } catch {
      // If config endpoint fails (e.g. not admin), just load servers
      try {
        const serverData = await mcpApi.listServers(userId);
        setServers(serverData.servers);
        setConfigLoaded(true);
        if (!editing) setConfigJson('{\n  "mcpServers": {}\n}');
      } catch {}
    }
  };

  useEffect(() => { reload(); }, []);

  const handleSave = async () => {
    if (!configJson.trim()) return;
    try {
      const parsed = JSON.parse(configJson);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setStatus("Config must be a JSON object");
        return;
      }
      const servers = parsed.mcpServers || parsed;
      if (!servers || typeof servers !== "object" || Array.isArray(servers)) {
        setStatus("mcpServers must be a JSON object");
        return;
      }
      const serverCount = Object.keys(servers).length;
      setBusy(`Saving and connecting to ${serverCount} server(s)...`);
      setStatus("");
      const result = await mcpApi.saveFullConfig(userId, parsed);
      setServers(result.servers);
      const connected = result.servers.filter((s: MCPServer) => s.connected).length;
      setStatus(`Saved — ${connected}/${result.servers.length} server(s) connected`);
      setEditing(false);
      // Refresh the config to get the canonical format back
      const fresh = await mcpApi.getFullConfig(userId);
      setConfigJson(JSON.stringify(fresh, null, 2));
    } catch (err) {
      if (err instanceof SyntaxError) {
        setStatus("Invalid JSON");
      } else {
        setStatus(err instanceof Error ? err.message : "Failed");
      }
    } finally {
      setBusy(null);
    }
  };

  const handleRestart = async () => {
    setBusy("Restarting all MCP servers...");
    setStatus("");
    try {
      const d = await mcpApi.restart(userId);
      setStatus(`Restarted — ${d.tools.length} tool(s)`);
      await reload();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Restart failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">MCP Servers</h2>
        <div className="flex items-center gap-2">
          <button onClick={handleRestart} disabled={!!busy} className="p-1.5 text-[var(--color-text-muted)] hover:text-[var(--color-text)] disabled:opacity-30" title="Restart all">
            <RefreshCw size={14} />
          </button>
          {!editing && (
            <button onClick={() => setEditing(true)} className="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]">
              <Plus size={14} /> Add / Edit
            </button>
          )}
        </div>
      </div>

      {/* Status / busy indicators */}
      {busy && (
        <div className="flex items-center gap-2 text-xs text-[var(--color-accent)] mb-3 animate-fade-in">
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-accent)]" />
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-accent)]" />
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-accent)]" />
          {busy}
        </div>
      )}
      {status && !busy && (
        <p className={`text-xs mb-3 animate-fade-in ${status.includes("failed") || status.includes("Failed") || status.includes("Invalid") ? "text-[var(--color-error)]" : "text-[var(--color-accent)]"}`}>{status}</p>
      )}

      {/* Server status cards */}
      <div className="space-y-2 mb-4">
        {servers.map((s) => (
          <div key={s.name} className="flex items-center gap-3 px-4 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
            <div className={`w-2 h-2 rounded-full shrink-0 ${s.connected ? "bg-[var(--color-success)]" : "bg-[var(--color-error)]"}`} />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">{s.name}</div>
              <div className="text-xs text-[var(--color-text-muted)] truncate">
                {s.transport === "http" ? s.url : `${s.command} ${(s.args || []).map(String).join(" ")}`}
                {s.tools.length > 0 && ` · ${s.tools.join(", ")}`}
              </div>
            </div>
            <span className={`text-xs shrink-0 ${s.connected ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
              {s.connected ? `${s.tools.length} tool(s)` : "disconnected"}
            </span>
            <button
              onClick={() => setEditing(true)}
              className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-text-muted)]"
              title="Edit config"
            >
              <Edit2 size={14} />
            </button>
            <button
              onClick={async () => {
                try {
                  setBusy(`Removing ${s.name}...`);
                  // Fetch fresh config to avoid saving stale edits
                  const fresh = await mcpApi.getFullConfig(userId);
                  const servers = fresh.mcpServers || {};
                  delete servers[s.name];
                  await mcpApi.saveFullConfig(userId, { mcpServers: servers });
                  setEditing(false);
                  await reload();
                  setStatus(`Removed ${s.name}`);
                } catch (err) {
                  setStatus(err instanceof Error ? err.message : "Failed");
                } finally {
                  setBusy(null);
                }
              }}
              className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-text-muted)] hover:text-[var(--color-error)]"
              title="Remove server"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {servers.length === 0 && !configLoaded && <p className="text-sm text-[var(--color-text-muted)]">Loading...</p>}
        {servers.length === 0 && configLoaded && !editing && <p className="text-sm text-[var(--color-text-muted)]">No MCP servers configured</p>}
      </div>

      {/* JSON editor — hidden by default, shown on Edit or Add */}
      {editing && (
        <div className="mb-4 animate-fade-in">
          <JsonEditor
            value={configJson}
            onChange={(v) => setConfigJson(v)}
            rows={14}
            placeholder={'{\n  "mcpServers": {\n    "fetch": {\n      "command": "python",\n      "args": ["-m", "mcp_server_fetch"]\n    }\n  }\n}'}
          />
          <div className="flex items-center gap-2 mt-2">
            <button
              onClick={handleSave}
              disabled={!!busy || !configLoaded}
              className="px-4 py-2 rounded-lg bg-[var(--color-accent)] text-[var(--color-bg)] text-sm font-medium disabled:opacity-50"
            >
              {busy ? "Connecting..." : "Save & reconnect"}
            </button>
            <button
              onClick={() => { setEditing(false); reload(); }}
              disabled={!!busy}
              className="px-4 py-2 rounded-lg bg-[var(--color-bg-hover)] text-sm disabled:opacity-50"
            >
              Cancel
            </button>
            <p className="text-xs text-[var(--color-text-muted)] flex-1">
              Use {"`${SECRET_NAME}`"} for secrets. {"`${file:SECRET_NAME}`"} for files.
            </p>
          </div>
        </div>
      )}
    </section>
  );
}

// --- Secrets Management ---

function SecretsManagement({ userId }: { userId: string }) {
  const [items, setItems] = useState<{ key: string; created_at: string }[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const [showValue, setShowValue] = useState(false);
  const [multiline, setMultiline] = useState(false);

  const reload = () => secretsApi.list(userId).then((d) => setItems(d.secrets)).catch(() => {});

  useEffect(() => { reload(); }, [userId]);

  const handleAdd = async () => {
    if (!newKey.trim() || !newValue) return;
    await secretsApi.set(userId, newKey.trim(), newValue);
    setNewKey("");
    setNewValue("");
    setShowAdd(false);
    reload();
  };

  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">Secrets</h2>
        <button onClick={() => setShowAdd(!showAdd)} className="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]">
          <Plus size={14} /> Add
        </button>
      </div>
      <p className="text-xs text-[var(--color-text-muted)] mb-3">
        Store API keys. Reference them in MCP configs as {"`${SECRET_NAME}`"}.
      </p>

      {showAdd && (
        <div className="bg-[var(--color-bg-secondary)] rounded-xl p-4 mb-4 space-y-3 animate-fade-in border border-[var(--color-border)]">
          <input type="text" placeholder="Key (e.g. WANDB_API_KEY)" value={newKey} onChange={(e) => setNewKey(e.target.value)} className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm font-mono text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)]" />
          <div className="flex items-center gap-2 text-xs">
            <label className="flex items-center gap-1.5 text-[var(--color-text-secondary)] cursor-pointer">
              <input type="checkbox" checked={multiline} onChange={(e) => setMultiline(e.target.checked)} className="accent-[var(--color-accent)]" />
              Multi-line (files, certificates, kubeconfig)
            </label>
          </div>
          {multiline ? (
            <textarea
              placeholder="Paste file content (YAML, PEM, etc.)"
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              rows={8}
              spellCheck={false}
              className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm font-mono text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)] resize-y"
            />
          ) : (
            <div className="relative">
              <input type={showValue ? "text" : "password"} placeholder="Value (API key, token, etc.)" value={newValue} onChange={(e) => setNewValue(e.target.value)} className="w-full px-3 py-2 pr-10 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)]" />
              <button onClick={() => setShowValue(!showValue)} className="absolute right-2 top-2 text-[var(--color-text-muted)]">
                {showValue ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          )}
          <p className="text-xs text-[var(--color-text-muted)]">
            Use {"`${SECRET_NAME}`"} for inline values, {"`${file:SECRET_NAME}`"} to write to a temp file (kubeconfig, certs).
          </p>
          <button onClick={handleAdd} className="px-4 py-2 rounded-lg bg-[var(--color-accent)] text-[var(--color-bg)] text-sm font-medium">Save</button>
        </div>
      )}

      <div className="space-y-2">
        {items.map((s) => (
          <div key={s.key} className="flex items-center gap-3 px-4 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
            <code className="text-sm font-mono text-[var(--color-accent)] flex-1">${`{${s.key}}`}</code>
            <button onClick={() => secretsApi.delete(s.key, userId).then(reload)} className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-text-muted)] hover:text-[var(--color-error)]">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {items.length === 0 && <p className="text-sm text-[var(--color-text-muted)]">No secrets stored</p>}
      </div>
    </section>
  );
}
