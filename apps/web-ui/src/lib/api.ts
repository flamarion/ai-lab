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

export interface StatusEvent {
  status: string;
  detail: string;
}

/** Default preference values — shared between settings page and chat page. */
export const DEFAULT_PREFS = {
  temperature: 0.7,
  top_p: 0.9,
  top_k: 40,
  num_predict: 1024,
  repeat_penalty: 1.1,
  use_rag: false,
  use_tools: false,
} as const;

export interface ChatParams {
  message: string;
  model?: string;
  temperature?: number;
  top_p?: number;
  top_k?: number;
  num_predict?: number;
  repeat_penalty?: number;
  seed?: number;
  num_ctx?: number;
  system_prompt?: string;
  use_rag?: boolean;
  use_tools?: boolean;
  user_id?: string;
  conversation_id?: string;
  history?: ChatMessage[];
}

export const chat = {
  send: (params: ChatParams) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  /**
   * Streaming chat — sends the request and yields SSE events.
   * Use for real-time status updates (thinking, tool calls, etc.)
   */
  sendStream: async (
    params: ChatParams,
    onStatus: (event: StatusEvent) => void,
    onToken?: (text: string) => void,
  ): Promise<ChatResponse> => {
    const res = await fetch(`${BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `API error: ${res.status}`);
    }

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result: ChatResponse | null = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      let eventType = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          const data = JSON.parse(line.slice(6));
          if (eventType === "status") {
            onStatus(data as StatusEvent);
          } else if (eventType === "token") {
            onToken?.(data.text);
          } else if (eventType === "done") {
            result = data as ChatResponse;
          } else if (eventType === "error") {
            throw new Error(data.detail || "Stream error");
          }
        }
      }
    }

    if (!result) throw new Error("Stream ended without result");
    return result;
  },

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
  listServers: (adminUserId: string) => request<{ servers: MCPServer[] }>(`/mcp/servers?admin_user_id=${adminUserId}`),

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
  list: (userId?: string) =>
    request<{ documents: { id: string; source: string; num_chunks: number; created_at: string; user_id: string | null; is_private: boolean }[] }>(
      userId ? `/documents?user_id=${userId}` : "/documents",
    ),

  delete: (id: string, userId?: string) =>
    request(`/documents/${id}${userId ? `?user_id=${userId}` : ""}`, { method: "DELETE" }),

  ingest: async (file: File, userId?: string, isPrivate = false) => {
    const form = new FormData();
    form.append("file", file);
    if (userId) form.append("user_id", userId);
    if (isPrivate) form.append("is_private", "true");
    const res = await fetch(`${BASE}/ingest`, { method: "POST", body: form });
    if (!res.ok) throw new Error("Upload failed");
    return res.json();
  },
};
