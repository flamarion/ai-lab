"use client";

import { useAuth } from "@/lib/auth-context";
import { admin as adminApi, mcp as mcpApi, secrets as secretsApi, type AdminUser, type MCPServer } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Plus, Trash2, Shield, ShieldOff, Baby, Edit2, RefreshCw, Eye, EyeOff, Key } from "lucide-react";
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
  const [showAdd, setShowAdd] = useState(false);
  const [editServer, setEditServer] = useState<string | null>(null);
  const [editJson, setEditJson] = useState("");
  const [addName, setAddName] = useState("");
  const [addJson, setAddJson] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState<string | null>(null); // null or description of what's happening

  const reload = () => mcpApi.listServers().then((d) => setServers(d.servers)).catch(() => {});

  useEffect(() => { reload(); }, []);

  const handleAdd = async () => {
    if (!addJson.trim()) return;
    try {
      const parsed = JSON.parse(addJson);

      // Detect Cursor-style format: {"mcpServers": {"name": {...}, ...}}
      if (parsed.mcpServers && typeof parsed.mcpServers === "object") {
        const names = Object.keys(parsed.mcpServers);
        setBusy(`Connecting to ${names.length} server(s)...`);
        setStatus("");
        // Send the full object — gateway extracts mcpServers
        await mcpApi.addServer(userId, names[0] || "import", parsed);
        setStatus(`Imported ${names.length} server(s): ${names.join(", ")}`);
      } else {
        // Single server — name is required
        if (!addName.trim()) {
          setStatus("Server name is required for single-server config");
          return;
        }
        setBusy(`Connecting to ${addName.trim()}...`);
        setStatus("");
        const result = await mcpApi.addServer(userId, addName.trim(), parsed);
        setStatus(result.connected ? `Added — ${result.tools.length} tool(s)` : "Added but connection failed — check config");
      }
      setShowAdd(false);
      setAddName("");
      setAddJson("");
      reload();
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

  const handleEdit = async (name: string) => {
    const data = await mcpApi.getConfig(name, userId);
    setEditServer(name);
    setEditJson(JSON.stringify(data.config, null, 2));
  };

  const handleSaveEdit = async () => {
    if (!editServer) return;
    try {
      const config = JSON.parse(editJson);
      setBusy(`Reconnecting to ${editServer}...`);
      setStatus("");
      const result = await mcpApi.addServer(userId, editServer, config);
      setStatus(result.connected ? `Updated — ${result.tools.length} tool(s)` : "Updated but connection failed — check config");
      setEditServer(null);
      reload();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Failed");
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
      reload();
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
          <button onClick={() => setShowAdd(!showAdd)} className="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]">
            <Plus size={14} /> Add
          </button>
        </div>
      </div>

      {busy && (
        <div className="flex items-center gap-2 text-xs text-[var(--color-accent)] mb-3 animate-fade-in">
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-accent)]" />
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-accent)]" />
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-[var(--color-accent)]" />
          {busy}
        </div>
      )}
      {status && !busy && (
        <p className={`text-xs mb-3 animate-fade-in ${status.includes("failed") || status.includes("Failed") ? "text-[var(--color-error)]" : "text-[var(--color-accent)]"}`}>{status}</p>
      )}

      {showAdd && (
        <div className="bg-[var(--color-bg-secondary)] rounded-xl p-4 mb-4 space-y-3 animate-fade-in border border-[var(--color-border)]">
          <textarea
            placeholder={'Paste Cursor/Claude Desktop format:\n{\n  "mcpServers": {\n    "wandb": {\n      "command": "uvx",\n      "args": ["--from", "git+https://...", "server"]\n    }\n  }\n}\n\nOr a single server config:\n{"command": "npx", "args": ["-y", "server@latest"]}'}
            value={addJson}
            onChange={(e) => setAddJson(e.target.value)}
            rows={8}
            className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm font-mono text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)] resize-y"
          />
          <input
            type="text"
            placeholder="Server name (required for single server, ignored for bulk import)"
            value={addName}
            onChange={(e) => setAddName(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)]"
          />
          <p className="text-xs text-[var(--color-text-muted)]">Use {"`${SECRET_NAME}`"} in configs to reference secrets. Bulk import detects the {"`mcpServers`"} wrapper automatically.</p>
          <button onClick={handleAdd} disabled={!!busy} className="px-4 py-2 rounded-lg bg-[var(--color-accent)] text-[var(--color-bg)] text-sm font-medium disabled:opacity-50">{busy ? "Connecting..." : "Add & validate"}</button>
        </div>
      )}

      {/* Edit panel */}
      {editServer && (
        <div className="bg-[var(--color-bg-secondary)] rounded-xl p-4 mb-4 space-y-3 animate-fade-in border border-[var(--color-accent)]">
          <div className="text-sm font-medium">Editing: {editServer}</div>
          <textarea value={editJson} onChange={(e) => setEditJson(e.target.value)} rows={6} className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm font-mono text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)] resize-none" />
          <div className="flex gap-2">
            <button onClick={handleSaveEdit} disabled={!!busy} className="px-4 py-2 rounded-lg bg-[var(--color-accent)] text-[var(--color-bg)] text-sm font-medium disabled:opacity-50">{busy ? "Connecting..." : "Save & reconnect"}</button>
            <button onClick={() => setEditServer(null)} disabled={!!busy} className="px-4 py-2 rounded-lg bg-[var(--color-bg-hover)] text-sm disabled:opacity-50">Cancel</button>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {servers.map((s) => (
          <div key={s.name} className="flex items-center gap-3 px-4 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
            <div className={`w-2 h-2 rounded-full ${s.connected ? "bg-[var(--color-success)]" : "bg-[var(--color-error)]"}`} />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">{s.name}</div>
              <div className="text-xs text-[var(--color-text-muted)] truncate">
                {s.transport === "http" ? s.url : `${s.command} ${(s.args || []).join(" ")}`}
                {s.tools.length > 0 && ` · ${s.tools.length} tool(s)`}
              </div>
            </div>
            <button onClick={() => handleEdit(s.name)} className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-text-muted)]">
              <Edit2 size={14} />
            </button>
            <button onClick={() => mcpApi.removeServer(s.name, userId).then(reload)} className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-text-muted)] hover:text-[var(--color-error)]">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {servers.length === 0 && <p className="text-sm text-[var(--color-text-muted)]">No MCP servers configured</p>}
      </div>
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
          <div className="relative">
            <input type={showValue ? "text" : "password"} placeholder="Value" value={newValue} onChange={(e) => setNewValue(e.target.value)} className="w-full px-3 py-2 pr-10 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm text-[var(--color-text)] focus:outline-none focus:border-[var(--color-accent)]" />
            <button onClick={() => setShowValue(!showValue)} className="absolute right-2 top-2 text-[var(--color-text-muted)]">
              {showValue ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
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
