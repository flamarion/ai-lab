import html
import json
import os
from datetime import datetime, timezone

import httpx
import streamlit as st

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")

# All file types supported for upload (matches chunker.SUPPORTED_EXTENSIONS)
_ALL_TYPES = [
    "txt", "md", "rst", "csv", "tsv", "log",
    "pdf", "docx", "xlsx",
    "py", "js", "ts", "go", "rs", "rb", "java", "kt",
    "c", "cpp", "h", "hpp", "cs", "sh", "bash", "zsh",
    "yaml", "yml", "toml", "json", "xml", "html", "css",
    "sql", "tf", "hcl", "ini", "cfg", "env",
    "r", "scala", "lua", "pl", "php", "swift",
]

# --- Page config ---
st.set_page_config(page_title="AI Lab", page_icon="🧪", layout="centered")

# --- Custom CSS ---
st.markdown(
    """
<style>
.block-container { max-width: 800px; }

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f0f1a 0%, #1a1a2e 100%);
}
section[data-testid="stSidebar"] [data-testid="stMarkdown"] p,
section[data-testid="stSidebar"] [data-testid="stMarkdown"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stSlider label {
    color: #c0c0d0 !important;
}
section[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.08);
}
section[data-testid="stSidebar"] button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    border: none; border-radius: 10px; font-weight: 600;
}
section[data-testid="stSidebar"] button[kind="primary"]:hover {
    background: linear-gradient(135deg, #818cf8, #a78bfa);
}
section[data-testid="stSidebar"] button[kind="secondary"] {
    text-align: left !important;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    background: rgba(255,255,255,0.03);
    color: #d0d0e0 !important;
    font-size: 0.82rem;
    padding: 0.35rem 0.6rem;
}
section[data-testid="stSidebar"] button[kind="secondary"]:hover {
    background: rgba(255,255,255,0.08);
}
section[data-testid="stSidebar"] button[kind="tertiary"] {
    color: #666 !important; opacity: 0.5;
}
section[data-testid="stSidebar"] button[kind="tertiary"]:hover {
    color: #ef4444 !important; opacity: 1;
}
[data-testid="stChatMessage"] { border-radius: 12px; padding: 1rem; }
.welcome-box { text-align: center; padding: 4rem 2rem 2rem; }
.welcome-icon { font-size: 3.5rem; margin-bottom: 0.5rem; }
.welcome-title { font-size: 1.6rem; font-weight: 600; margin-bottom: 0.3rem; }
.welcome-sub { font-size: 1rem; color: #888; margin-bottom: 2rem; }
.hint-card {
    display: inline-block; background: #f8f8fc; border: 1px solid #e8e8f0;
    border-radius: 10px; padding: 0.6rem 1.2rem; margin: 0.3rem;
    font-size: 0.85rem; color: #555;
}
</style>
""",
    unsafe_allow_html=True,
)


# --- Helpers ---


def _relative_time(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - dt
        if diff.days > 30:
            return dt.strftime("%b %d")
        if diff.days > 0:
            return f"{diff.days}d ago"
        hours = diff.seconds // 3600
        if hours > 0:
            return f"{hours}h ago"
        minutes = diff.seconds // 60
        if minutes > 0:
            return f"{minutes}m ago"
        return "just now"
    except Exception:
        return ""


def _save_preferences():
    if not st.session_state.get("user_id"):
        return
    prefs = {
        "model": st.session_state.get("pref_model", "Auto (recommended)"),
        "temperature": st.session_state.get("pref_temperature", 0.7),
    }
    try:
        httpx.patch(
            f"{GATEWAY_URL}/auth/preferences",
            json={"user_id": st.session_state.user_id, "preferences": prefs},
            timeout=5.0,
        )
        # Keep local state in sync so Chat page reads updated values
        st.session_state.preferences = prefs
    except Exception:
        pass


def _logout():
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.is_admin = False
    st.session_state.preferences = {}
    st.session_state.messages = []
    st.session_state.conversation_id = None
    st.session_state.page = "Chat"
    st.rerun()


# --- Session state init ---

for key, default in [
    ("messages", []),
    ("conversation_id", None),
    ("user_id", None),
    ("username", None),
    ("preferences", {}),
    ("is_admin", False),
    ("page", "Chat"),
]:
    if key not in st.session_state:
        st.session_state[key] = default

if "models" not in st.session_state:
    try:
        resp = httpx.get(f"{GATEWAY_URL}/models", timeout=10.0)
        st.session_state.models = resp.json()["models"]
    except Exception:
        st.session_state.models = []


# ============================================================
# LOGIN SCREEN
# ============================================================

if not st.session_state.user_id:
    st.markdown("#### 🧪 AI Lab")

    users = []
    try:
        resp = httpx.get(f"{GATEWAY_URL}/auth/users", timeout=5.0)
        if resp.status_code == 200:
            users = resp.json().get("users", [])
    except Exception:
        pass

    tab_login, tab_register = st.tabs(["Sign in", "Create account"])

    with tab_login:
        if users:
            usernames = [u["username"] for u in users]
            selected_user = st.selectbox("Who are you?", usernames, key="login_user")
            pin_input = st.text_input("PIN", type="password", max_chars=8, key="login_pin")
            if st.button("Sign in", use_container_width=True, type="primary"):
                if pin_input:
                    try:
                        resp = httpx.post(
                            f"{GATEWAY_URL}/auth/login",
                            json={"username": selected_user, "pin": pin_input},
                            timeout=10.0,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            st.session_state.user_id = data["user_id"]
                            st.session_state.username = data["username"]
                            st.session_state.is_admin = data.get("is_admin", False)
                            st.session_state.preferences = data.get("preferences", {})
                            st.rerun()
                        else:
                            st.error("Invalid PIN")
                    except Exception:
                        st.error("Could not connect to gateway")
                else:
                    st.warning("Enter your PIN")
        else:
            st.info("No users yet. Create an account to get started.")

    with tab_register:
        new_username = st.text_input("Choose a username", key="reg_user")
        new_pin = st.text_input("Choose a PIN (4+ digits)", type="password", max_chars=8, key="reg_pin")
        if st.button("Create account", use_container_width=True):
            if new_username.strip() and len(new_pin) >= 4:
                try:
                    resp = httpx.post(
                        f"{GATEWAY_URL}/auth/register",
                        json={"username": new_username.strip(), "pin": new_pin},
                        timeout=10.0,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        st.session_state.user_id = data["user_id"]
                        st.session_state.username = data["username"]
                        st.session_state.is_admin = data.get("is_admin", False)
                        st.session_state.preferences = {}
                        st.rerun()
                    else:
                        st.error(resp.json().get("detail", "Registration failed"))
                except Exception:
                    st.error("Could not connect to gateway")
            else:
                st.warning("Username required and PIN must be at least 4 digits")

    st.stop()


# ============================================================
# MAIN APP — user is logged in
# ============================================================

prefs = st.session_state.preferences
# Handle legacy: preferences may be a JSON string if stored before the double-encoding fix
if isinstance(prefs, str):
    try:
        prefs = json.loads(prefs)
    except (json.JSONDecodeError, TypeError):
        prefs = {}
if not isinstance(prefs, dict):
    prefs = {}
st.session_state.preferences = prefs
default_model = prefs.get("model", "Auto (recommended)")
default_temp = prefs.get("temperature", 0.7)

# --- Sidebar: user header + navigation ---
with st.sidebar:
    # User header with clear logout
    st.markdown(f"#### 🧪 {st.session_state.username}")
    if st.button("Sign out", use_container_width=True, type="tertiary"):
        _logout()

    st.divider()

    # Page navigation
    pages = ["Chat", "Settings"]
    if st.session_state.is_admin:
        pages.append("Admin")

    st.session_state.page = st.radio(
        "Navigation",
        pages,
        index=pages.index(st.session_state.page) if st.session_state.page in pages else 0,
        label_visibility="collapsed",
        horizontal=True,
    )

    st.divider()

    # --- Chat page sidebar: New Chat + conversations ---
    if st.session_state.page == "Chat":
        if st.button("✨  New Chat", use_container_width=True, type="primary"):
            st.session_state.messages = []
            st.session_state.conversation_id = None
            st.rerun()

        st.caption("RECENT CONVERSATIONS")
        try:
            conv_resp = httpx.get(
                f"{GATEWAY_URL}/conversations",
                params={"user_id": st.session_state.user_id},
                timeout=10.0,
            )
            if conv_resp.status_code == 200:
                conversations = conv_resp.json().get("conversations", [])
                if not conversations:
                    st.caption("No conversations yet. Start chatting!")
                for conv in conversations:
                    col1, col2 = st.columns([6, 1])
                    title = conv.get("title") or "Untitled"
                    is_active = st.session_state.conversation_id == conv["id"]
                    time_str = _relative_time(conv.get("updated_at", ""))
                    with col1:
                        label = f"{'▸ ' if is_active else ''}{title}"
                        if time_str:
                            label += f"  ·  {time_str}"
                        if st.button(label, key=f"conv_{conv['id']}", use_container_width=True):
                            try:
                                detail = httpx.get(
                                    f"{GATEWAY_URL}/conversations/{conv['id']}",
                                    timeout=10.0,
                                )
                                detail.raise_for_status()
                                data = detail.json()
                                st.session_state.conversation_id = conv["id"]
                                st.session_state.messages = [
                                    {"role": m["role"], "content": m["content"]}
                                    for m in data["messages"]
                                ]
                                st.rerun()
                            except Exception:
                                st.error("Failed to load conversation")
                    with col2:
                        if st.button("🗑", key=f"del_{conv['id']}", type="tertiary"):
                            try:
                                httpx.delete(
                                    f"{GATEWAY_URL}/conversations/{conv['id']}",
                                    timeout=10.0,
                                )
                                if st.session_state.conversation_id == conv["id"]:
                                    st.session_state.conversation_id = None
                                    st.session_state.messages = []
                                st.rerun()
                            except Exception:
                                st.error("Failed to delete")
            else:
                st.caption("Conversation history unavailable")
        except Exception:
            st.caption("Conversation history unavailable")


# ============================================================
# CHAT PAGE
# ============================================================

if st.session_state.page == "Chat":
    # We need settings values for the chat — use defaults from preferences
    # Settings are configured on the Settings page
    if st.session_state.models:
        model_options = ["Auto (recommended)"] + st.session_state.models
        selected_model = None if default_model == "Auto (recommended)" else default_model
        if selected_model and selected_model not in st.session_state.models:
            selected_model = None
    else:
        selected_model = None
    temperature = default_temp

    # Advanced settings stored in session (set on Settings page)
    top_p = st.session_state.get("adv_top_p", 0.9)
    num_predict = st.session_state.get("adv_num_predict", 1024)
    system_prompt = st.session_state.get("adv_system_prompt", "")
    use_rag = st.session_state.get("adv_use_rag", False)
    use_tools = st.session_state.get("adv_use_tools", False)

    # Welcome screen
    if not st.session_state.messages:
        st.markdown(
            f"""
        <div class="welcome-box">
            <div class="welcome-icon">🧪</div>
            <div class="welcome-title">Hey {html.escape(st.session_state.username or "")}!</div>
            <div class="welcome-sub">Your personal AI assistant — powered by local models</div>
            <div style="margin-top: 1.5rem;">
                <div class="hint-card">💡 Ask me anything</div>
                <div class="hint-card">📝 Help me write</div>
                <div class="hint-card">🔍 Explain a concept</div>
                <div class="hint-card">💻 Debug some code</div>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )
    else:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # File upload — attach documents to ground the conversation
    uploaded_files = st.file_uploader(
        "Attach documents",
        type=_ALL_TYPES,
        accept_multiple_files=True,
        key="chat_file_upload",
        label_visibility="collapsed",
    )
    if uploaded_files:
        ingested = st.session_state.get("_ingested_files", set())
        for uf in uploaded_files:
            if uf.name in ingested:
                continue
            with st.spinner(f"Processing {uf.name}..."):
                try:
                    resp = httpx.post(
                        f"{GATEWAY_URL}/ingest",
                        files={"file": (uf.name, uf.getvalue())},
                        timeout=120.0,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    ingested.add(uf.name)
                    st.session_state["_ingested_files"] = ingested
                    st.session_state["adv_use_rag"] = True
                    use_rag = True
                    st.success(f"{data['source']} ({data['num_chunks']} chunks)")
                except Exception as e:
                    st.error(f"Failed to process {uf.name}: {e}")
        if ingested:
            st.caption("RAG enabled — ask questions about your documents")

    # Chat input
    if prompt := st.chat_input("Type your message..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    payload = {
                        "message": prompt,
                        "temperature": temperature,
                        "user_id": st.session_state.user_id,
                    }
                    if selected_model:
                        payload["model"] = selected_model
                    if top_p != 0.9:
                        payload["top_p"] = top_p
                    if num_predict != 1024:
                        payload["num_predict"] = num_predict
                    if system_prompt.strip():
                        payload["system_prompt"] = system_prompt
                    if use_rag:
                        payload["use_rag"] = True
                    if use_tools:
                        payload["use_tools"] = True
                    if st.session_state.conversation_id:
                        payload["conversation_id"] = st.session_state.conversation_id
                    else:
                        payload["history"] = st.session_state.messages[:-1]

                    resp = httpx.post(
                        f"{GATEWAY_URL}/chat",
                        json=payload,
                        timeout=120.0,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    answer = data["response"]
                    tools_used = data.get("tools_used", [])
                    st.session_state.conversation_id = data.get("conversation_id")
                    success = True
                except Exception as e:
                    answer = f"Error: {e}"
                    tools_used = []
                    success = False

            # Show tool usage before the answer
            if tools_used:
                with st.expander(f"Used {len(tools_used)} tool(s)", expanded=False):
                    for t in tools_used:
                        st.markdown(f"**{t['name']}**({', '.join(f'{k}={v!r}' for k, v in t['arguments'].items())})")
                        st.code(t["result"], language=None)

            st.markdown(answer)

        if success:
            st.session_state.messages.append({"role": "assistant", "content": answer})
        else:
            # Roll back the user message so it doesn't pollute history on next turn
            st.session_state.messages.pop()


# ============================================================
# SETTINGS PAGE
# ============================================================

elif st.session_state.page == "Settings":
    st.header("Settings")

    st.subheader("Model")
    if st.session_state.models:
        model_options = ["Auto (recommended)"] + st.session_state.models
        default_idx = 0
        if default_model in model_options:
            default_idx = model_options.index(default_model)
        st.selectbox(
            "Model",
            model_options,
            index=default_idx,
            key="pref_model",
            help="Auto routes to the best model based on your message.",
            on_change=_save_preferences,
        )
    else:
        st.warning("Could not fetch models from gateway")

    st.subheader("Temperature")
    st.slider(
        "Temperature", 0.0, 1.0, default_temp, 0.1,
        key="pref_temperature",
        on_change=_save_preferences,
        help="Higher = more creative, lower = more focused",
    )

    st.divider()
    st.subheader("Advanced")

    st.slider(
        "Max response length", 64, 4096,
        st.session_state.get("adv_num_predict", 1024), 64,
        key="adv_num_predict",
        help="Limit how long the response can be (in tokens, ~0.75 words each)",
    )
    st.slider(
        "Top P", 0.0, 1.0,
        st.session_state.get("adv_top_p", 0.9), 0.05,
        key="adv_top_p",
        help="Controls diversity. Lower = more focused, higher = more creative",
    )
    st.text_area(
        "System prompt",
        value=st.session_state.get("adv_system_prompt", ""),
        height=80,
        key="adv_system_prompt",
        help="Optional instructions the model follows for every message",
        placeholder="e.g. You are a helpful cooking assistant",
    )
    st.toggle(
        "Use documents (RAG)",
        value=st.session_state.get("adv_use_rag", False),
        key="adv_use_rag",
        help="Ground answers in your uploaded documents",
    )
    st.toggle(
        "Use tools",
        value=st.session_state.get("adv_use_tools", False),
        key="adv_use_tools",
        help="Let the model use tools (calculator, web search, current time). Requires a tool-capable model (llama3.1, qwen3.5).",
    )

    st.divider()
    st.subheader("Upload Documents")
    st.caption("Supported: PDF, DOCX, XLSX, text, markdown, code, config files.")
    settings_files = st.file_uploader(
        "Upload files",
        type=_ALL_TYPES,
        accept_multiple_files=True,
        label_visibility="collapsed",
        key="settings_file_upload",
    )
    if settings_files:
        if st.button("Ingest all", use_container_width=True, type="primary"):
            for sf in settings_files:
                with st.spinner(f"Processing {sf.name}..."):
                    try:
                        resp = httpx.post(
                            f"{GATEWAY_URL}/ingest",
                            files={"file": (sf.name, sf.getvalue())},
                            timeout=120.0,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        st.success(f"{data['source']} ({data['num_chunks']} chunks)")
                    except Exception as e:
                        st.error(f"Failed to ingest: {e}")

    st.divider()
    st.subheader("Account")
    current_pin = st.text_input("Current PIN", type="password", max_chars=8, key="chg_cur_pin")
    new_pin = st.text_input("New PIN (4-8 digits)", type="password", max_chars=8, key="chg_new_pin")
    if st.button("Update PIN", use_container_width=True):
        if current_pin and new_pin and len(new_pin) >= 4:
            try:
                resp = httpx.post(
                    f"{GATEWAY_URL}/auth/change-pin",
                    json={
                        "user_id": st.session_state.user_id,
                        "current_pin": current_pin,
                        "new_pin": new_pin,
                    },
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    st.success("PIN updated")
                else:
                    st.error(resp.json().get("detail", "Failed"))
            except Exception:
                st.error("Could not connect to gateway")
        else:
            st.warning("Enter current PIN and new PIN (4+ digits)")


# ============================================================
# ADMIN PAGE (admins only)
# ============================================================

elif st.session_state.page == "Admin" and st.session_state.is_admin:
    st.header("Admin")

    # Fetch all users
    all_users = []
    try:
        users_resp = httpx.get(
            f"{GATEWAY_URL}/admin/users",
            params={"admin_user_id": st.session_state.user_id},
            timeout=5.0,
        )
        if users_resp.status_code == 200:
            all_users = users_resp.json().get("users", [])
    except Exception:
        st.error("Could not fetch users")

    # --- User list ---
    st.subheader("Users")

    for u in all_users:
        col_name, col_role, col_child, col_admin, col_del = st.columns([3, 2, 1, 1, 1])
        with col_name:
            st.markdown(f"**{u['username']}**")
        with col_role:
            badges = []
            if u.get("is_admin"):
                badges.append("admin")
            if u.get("is_child"):
                badges.append("child")
            if u["id"] == st.session_state.user_id:
                badges.append("you")
            st.caption(", ".join(badges) if badges else "user")
        with col_child:
            if u["id"] != st.session_state.user_id:
                child_label = "🧒" if u.get("is_child") else "👤"
                if st.button(child_label, key=f"child_{u['id']}", help="Toggle child flag"):
                    try:
                        resp = httpx.post(
                            f"{GATEWAY_URL}/admin/toggle-child",
                            json={
                                "admin_user_id": st.session_state.user_id,
                                "target_user_id": u["id"],
                                "is_child": not u.get("is_child", False),
                            },
                            timeout=10.0,
                        )
                        resp.raise_for_status()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
        with col_admin:
            if u["id"] != st.session_state.user_id:
                admin_label = "⭐" if u.get("is_admin") else "☆"
                if st.button(admin_label, key=f"adm_{u['id']}", help="Toggle admin"):
                    try:
                        resp = httpx.post(
                            f"{GATEWAY_URL}/admin/toggle-admin",
                            json={
                                "admin_user_id": st.session_state.user_id,
                                "target_user_id": u["id"],
                                "is_admin": not u.get("is_admin", False),
                            },
                            timeout=10.0,
                        )
                        resp.raise_for_status()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
        with col_del:
            if u["id"] != st.session_state.user_id:
                if st.button("🗑", key=f"delusr_{u['id']}", type="tertiary"):
                    try:
                        resp = httpx.post(
                            f"{GATEWAY_URL}/admin/delete-user",
                            json={
                                "admin_user_id": st.session_state.user_id,
                                "target_user_id": u["id"],
                            },
                            timeout=10.0,
                        )
                        resp.raise_for_status()
                        st.rerun()
                    except Exception:
                        st.error("Failed")

    # --- Add user ---
    st.divider()
    st.subheader("Add User")
    add_username = st.text_input("Username", key="add_user_name")
    add_pin = st.text_input("PIN (4-8 digits)", type="password", max_chars=8, key="add_user_pin")
    add_child = st.checkbox("This is a child account", key="add_user_child")
    if st.button("Create user", use_container_width=True, type="primary"):
        if add_username.strip() and add_pin and len(add_pin) >= 4:
            try:
                resp = httpx.post(
                    f"{GATEWAY_URL}/admin/create-user",
                    json={
                        "admin_user_id": st.session_state.user_id,
                        "username": add_username.strip(),
                        "pin": add_pin,
                        "is_child": add_child,
                    },
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    st.success(f"Created user {add_username.strip()}")
                    st.rerun()
                else:
                    st.error(resp.json().get("detail", "Failed"))
            except Exception:
                st.error("Could not connect to gateway")
        else:
            st.warning("Username and PIN (4+ digits) required")

    # --- Reset PIN ---
    st.divider()
    st.subheader("Reset User PIN")
    other_users = [u for u in all_users if u["id"] != st.session_state.user_id]
    if other_users:
        reset_user = st.selectbox(
            "User",
            [u["username"] for u in other_users],
            key="reset_user_select",
        )
        reset_pin = st.text_input("New PIN", type="password", max_chars=8, key="reset_pin_input")
        if st.button("Reset PIN", use_container_width=True):
            target = next(u for u in other_users if u["username"] == reset_user)
            if reset_pin and len(reset_pin) >= 4:
                try:
                    resp = httpx.post(
                        f"{GATEWAY_URL}/admin/reset-pin",
                        json={
                            "admin_user_id": st.session_state.user_id,
                            "target_user_id": target["id"],
                            "new_pin": reset_pin,
                        },
                        timeout=10.0,
                    )
                    if resp.status_code == 200:
                        st.success(f"PIN reset for {reset_user}")
                    else:
                        st.error(resp.json().get("detail", "Failed"))
                except Exception:
                    st.error("Could not connect to gateway")
            else:
                st.warning("Enter a PIN (4+ digits)")
    else:
        st.caption("No other users to manage.")
