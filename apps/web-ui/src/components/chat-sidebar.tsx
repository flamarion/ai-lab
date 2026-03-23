"use client";

import { useAuth } from "@/lib/auth-context";
import { conversations as convApi, type Conversation } from "@/lib/api";
import { useEffect, useState } from "react";
import { Plus, MessageSquare, Trash2, Settings, Shield, LogOut, X } from "lucide-react";
import Link from "next/link";

interface Props {
  currentId?: string;
  onSelect: (id: string | null) => void;
  open: boolean;
  onClose: () => void;
  refreshKey?: number; // increment to trigger conversation list refresh
}

export default function ChatSidebar({ currentId, onSelect, open, onClose, refreshKey }: Props) {
  const { user, logout } = useAuth();
  const [convs, setConvs] = useState<Conversation[]>([]);

  const refreshConvs = () => {
    if (!user) return;
    convApi.list(user.user_id).then((d) => setConvs(d.conversations)).catch(() => {});
  };

  // Load conversations on mount, user change, or explicit refresh
  useEffect(() => {
    refreshConvs();
  }, [user, refreshKey]);  // eslint-disable-line react-hooks/exhaustive-deps

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    await convApi.delete(id).catch(() => {});
    setConvs((prev) => prev.filter((c) => c.id !== id));
    if (currentId === id) onSelect(null);
  };

  const groupedConvs = groupByDate(convs);

  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div className="fixed inset-0 bg-black/50 z-40 lg:hidden" onClick={onClose} />
      )}

      <aside
        className={`fixed lg:relative z-50 lg:z-auto top-0 left-0 h-full w-72 bg-[var(--color-bg-secondary)] border-r border-[var(--color-border)] flex flex-col transition-transform duration-200 ${
          open ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        {/* Header */}
        <div className="p-4 flex items-center justify-between">
          <button
            onClick={() => onSelect(null)}
            className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[var(--color-bg-hover)] hover:bg-[var(--color-bg-tertiary)] transition-colors text-sm font-medium flex-1"
          >
            <Plus size={16} />
            New chat
          </button>
          <button onClick={onClose} className="lg:hidden ml-2 p-2 text-[var(--color-text-muted)]">
            <X size={18} />
          </button>
        </div>

        {/* Conversation list */}
        <div className="flex-1 overflow-y-auto px-2">
          {groupedConvs.map(([label, items]) => (
            <div key={label} className="mb-4">
              <p className="px-3 py-1 text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
                {label}
              </p>
              {items.map((c) => (
                <button
                  key={c.id}
                  onClick={() => { onSelect(c.id); onClose(); }}
                  className={`group w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm text-left transition-colors mb-0.5 ${
                    currentId === c.id
                      ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                      : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]"
                  }`}
                >
                  <MessageSquare size={14} className="shrink-0 opacity-50" />
                  <span className="truncate flex-1">{c.title || "Untitled"}</span>
                  <button
                    onClick={(e) => handleDelete(c.id, e)}
                    className="opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity"
                  >
                    <Trash2 size={13} />
                  </button>
                </button>
              ))}
            </div>
          ))}
        </div>

        {/* Footer nav */}
        <div className="p-3 border-t border-[var(--color-border)] space-y-1">
          <Link
            href="/settings"
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] transition-colors"
          >
            <Settings size={16} />
            Settings
          </Link>
          {user?.is_admin && (
            <Link
              href="/admin"
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] transition-colors"
            >
              <Shield size={16} />
              Admin
            </Link>
          )}
          <button
            onClick={logout}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-[var(--color-text-muted)] hover:text-[var(--color-error)] hover:bg-[var(--color-bg-hover)] transition-colors w-full"
          >
            <LogOut size={16} />
            Sign out · {user?.username}
          </button>
        </div>
      </aside>
    </>
  );
}

function groupByDate(convs: Conversation[]): [string, Conversation[]][] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: Record<string, Conversation[]> = {};
  for (const c of convs) {
    const d = new Date(c.updated_at || c.created_at);
    let label: string;
    if (d >= today) label = "Today";
    else if (d >= yesterday) label = "Yesterday";
    else if (d >= weekAgo) label = "This week";
    else label = "Older";

    (groups[label] ??= []).push(c);
  }
  const order = ["Today", "Yesterday", "This week", "Older"];
  return order.filter((k) => groups[k]).map((k) => [k, groups[k]]);
}
