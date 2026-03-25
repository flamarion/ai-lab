/**
 * Gateway API client. All calls go through /api/ which nginx proxies
 * to the FastAPI gateway.
 */

const BASE = "/api";

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${res.status}`);
  }
  return res.json();
}

// --- Auth ---

export interface User {
  username: string;
}

export interface AuthResponse {
  user_id: string;
  username: string;
  is_admin: boolean;
  is_child?: boolean;
  preferences: Record<string, unknown>;
}

export const auth = {
  listUsers: () => request<{ users: User[] }>("/auth/users"),

  login: (username: string, pin: string) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, pin }),
    }),

  register: (username: string, pin: string) =>
    request<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, pin }),
    }),

  session: (userId: string) =>
    request<AuthResponse>(`/auth/session?user_id=${userId}`),

  updatePreferences: (userId: string, preferences: Record<string, unknown>) =>
    request("/auth/preferences", {
      method: "PATCH",
      body: JSON.stringify({ user_id: userId, preferences }),
    }),

  changePin: (userId: string, currentPin: string, newPin: string) =>
    request("/auth/change-pin", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, current_pin: currentPin, new_pin: newPin }),
    }),
};

// --- Chat ---

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ToolUsed {
  name: string;
  arguments: Record<string, unknown>;
  result: string;
}

export interface ChatResponse {
  response: string;
  model: string;
  conversation_id: string;
  tools_used: ToolUsed[];
}

export interface Conversation {
  id: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: { role: string; content: string; created_at: string }[];
}

export const chat = {
  send: (params: {
    message: string;
    model?: string;
    temperature?: number;
    top_p?: number;
    num_predict?: number;
    system_prompt?: string;
    use_rag?: boolean;
    use_tools?: boolean;
    user_id?: string;
    conversation_id?: string;
    history?: ChatMessage[];
  }) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  models: () => request<{ models: string[] }>("/models"),
  tools: () => request<{ tools: { name: string; description: string; source: string }[] }>("/tools"),
};

export const conversations = {
  list: (userId: string) =>
    request<{ conversations: Conversation[] }>(`/conversations?user_id=${userId}`),

  get: (id: string) => request<ConversationDetail>(`/conversations/${id}`),

  delete: (id: string) =>
    request(`/conversations/${id}`, { method: "DELETE" }),
};

// --- Admin ---

export interface AdminUser {
  id: string;
  username: string;
  is_admin: boolean;
  is_child: boolean;
}

export const admin = {
  listUsers: (adminUserId: string) =>
    request<{ users: AdminUser[] }>(`/admin/users?admin_user_id=${adminUserId}`),

  createUser: (adminUserId: string, username: string, pin: string, isChild = false) =>
    request("/admin/create-user", {
      method: "POST",
      body: JSON.stringify({ admin_user_id: adminUserId, username, pin, is_child: isChild }),
    }),

  deleteUser: (adminUserId: string, targetUserId: string) =>
    request("/admin/delete-user", {
      method: "POST",
      body: JSON.stringify({ admin_user_id: adminUserId, target_user_id: targetUserId }),
    }),

  resetPin: (adminUserId: string, targetUserId: string, newPin: string) =>
    request("/admin/reset-pin", {
      method: "POST",
      body: JSON.stringify({ admin_user_id: adminUserId, target_user_id: targetUserId, new_pin: newPin }),
    }),

  toggleAdmin: (adminUserId: string, targetUserId: string, isAdmin: boolean) =>
    request("/admin/toggle-admin", {
      method: "POST",
      body: JSON.stringify({ admin_user_id: adminUserId, target_user_id: targetUserId, is_admin: isAdmin }),
    }),

  toggleChild: (adminUserId: string, targetUserId: string, isChild: boolean) =>
    request("/admin/toggle-child", {
      method: "POST",
      body: JSON.stringify({ admin_user_id: adminUserId, target_user_id: targetUserId, is_child: isChild }),
    }),
};

// --- MCP ---

export interface MCPServer {
  name: string;
  transport: string;
  connected: boolean;
  tools: string[];
  command?: string;
  args?: string[];
  url?: string;
}

export const mcp = {
  listServers: () => request<{ servers: MCPServer[] }>("/mcp/servers"),

  getFullConfig: (adminUserId: string) =>
    request<{ mcpServers: Record<string, unknown> }>(`/mcp/config?admin_user_id=${adminUserId}`),

  saveFullConfig: (adminUserId: string, config: Record<string, unknown>) =>
    request<{ status: string; servers: MCPServer[] }>("/mcp/config", {
      method: "PUT",
      body: JSON.stringify({ admin_user_id: adminUserId, config }),
    }),

  getConfig: (name: string, adminUserId: string) =>
    request<{ name: string; config: Record<string, unknown> }>(
      `/mcp/servers/${name}/config?admin_user_id=${adminUserId}`
    ),

  addServer: (adminUserId: string, name: string, config: Record<string, unknown>) =>
    request<{ status: string; name: string; connected: boolean; tools: string[] }>("/mcp/servers", {
      method: "POST",
      body: JSON.stringify({ admin_user_id: adminUserId, name, config }),
    }),

  removeServer: (name: string, adminUserId: string) =>
    request(`/mcp/servers/${name}?admin_user_id=${adminUserId}`, { method: "DELETE" }),

  restart: (adminUserId: string) =>
    request<{ status: string; tools: string[] }>("/mcp/restart", {
      method: "POST",
      body: JSON.stringify({ admin_user_id: adminUserId }),
    }),
};

// --- Secrets ---

export const secrets = {
  list: (adminUserId: string) =>
    request<{ secrets: { key: string; created_at: string }[] }>(`/secrets?admin_user_id=${adminUserId}`),

  set: (adminUserId: string, key: string, value: string) =>
    request("/secrets", {
      method: "POST",
      body: JSON.stringify({ admin_user_id: adminUserId, key, value }),
    }),

  delete: (key: string, adminUserId: string) =>
    request(`/secrets/${key}?admin_user_id=${adminUserId}`, { method: "DELETE" }),
};

// --- Memory ---

export interface Memory {
  id: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export const memory = {
  list: (userId: string) =>
    request<{ memories: Memory[] }>(`/memory?user_id=${userId}`),

  add: (userId: string, content: string) =>
    request<{ status: string; id: string }>("/memory", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, content }),
    }),

  delete: (memoryId: string, userId: string) =>
    request(`/memory/${memoryId}?user_id=${userId}`, { method: "DELETE" }),
};

// --- Documents ---

export const documents = {
  list: () => request<{ documents: { id: string; source: string; num_chunks: number; created_at: string }[] }>("/documents"),

  delete: (id: string) => request(`/documents/${id}`, { method: "DELETE" }),

  ingest: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/ingest`, { method: "POST", body: form });
    if (!res.ok) throw new Error("Upload failed");
    return res.json();
  },
};
