import html
import os
from datetime import datetime, timezone

import httpx
import streamlit as st

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")

# --- Page config ---
st.set_page_config(page_title="AI Lab", page_icon="🧪", layout="centered")

# --- Custom CSS ---
st.markdown(
    """
<style>
/* ---- Global ---- */
.block-container { max-width: 800px; }

/* ---- Sidebar ---- */
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

/* New Chat button */
section[data-testid="stSidebar"] button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    border: none;
    border-radius: 10px;
    font-weight: 600;
    letter-spacing: 0.02em;
}
section[data-testid="stSidebar"] button[kind="primary"]:hover {
    background: linear-gradient(135deg, #818cf8, #a78bfa);
}

/* Conversation list buttons */
section[data-testid="stSidebar"] button[kind="secondary"] {
    text-align: left !important;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    background: rgba(255,255,255,0.03);
    color: #d0d0e0 !important;
    font-size: 0.82rem;
    padding: 0.35rem 0.6rem;
    transition: all 0.15s ease;
}
section[data-testid="stSidebar"] button[kind="secondary"]:hover {
    background: rgba(255,255,255,0.08);
    border-color: rgba(255,255,255,0.15);
}

/* Delete buttons */
section[data-testid="stSidebar"] button[kind="tertiary"] {
    color: #666 !important;
    opacity: 0.5;
}
section[data-testid="stSidebar"] button[kind="tertiary"]:hover {
    color: #ef4444 !important;
    opacity: 1;
}

/* ---- Chat area ---- */
[data-testid="stChatMessage"] {
    border-radius: 12px;
    padding: 1rem;
}

/* ---- Welcome screen ---- */
.welcome-box {
    text-align: center;
    padding: 4rem 2rem 2rem;
}
.welcome-icon { font-size: 3.5rem; margin-bottom: 0.5rem; }
.welcome-title {
    font-size: 1.6rem;
    font-weight: 600;
    margin-bottom: 0.3rem;
}
.welcome-sub {
    font-size: 1rem;
    color: #888;
    margin-bottom: 2rem;
}
.hint-card {
    display: inline-block;
    background: #f8f8fc;
    border: 1px solid #e8e8f0;
    border-radius: 10px;
    padding: 0.6rem 1.2rem;
    margin: 0.3rem;
    font-size: 0.85rem;
    color: #555;
}

/* ---- Login screen ---- */
.login-box {
    max-width: 360px;
    margin: 4rem auto;
    padding: 2rem;
    border: 1px solid #e8e8f0;
    border-radius: 16px;
    text-align: center;
}
</style>
""",
    unsafe_allow_html=True,
)


# --- Helpers ---


def _relative_time(iso_str: str) -> str:
    """Convert an ISO timestamp to a human-friendly relative string."""
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
    """Save current settings to the user's profile on the gateway."""
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
    except Exception:
        pass  # non-critical


# --- Session state init ---

if "messages" not in st.session_state:
    st.session_state.messages = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "username" not in st.session_state:
    st.session_state.username = None
if "preferences" not in st.session_state:
    st.session_state.preferences = {}
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# Fetch models once per session
if "models" not in st.session_state:
    try:
        resp = httpx.get(f"{GATEWAY_URL}/models", timeout=10.0)
        st.session_state.models = resp.json()["models"]
    except Exception:
        st.session_state.models = []


# ============================================================
# LOGIN SCREEN — shown when no user is logged in
# ============================================================

if not st.session_state.user_id:
    st.markdown("#### 🧪 AI Lab")

    # Fetch existing users for the dropdown
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

    st.stop()  # Don't render the rest of the app


# ============================================================
# MAIN APP — user is logged in
# ============================================================

# Load preferences into defaults
prefs = st.session_state.preferences
default_model = prefs.get("model", "Auto (recommended)")
default_temp = prefs.get("temperature", 0.7)

# --- Sidebar ---
with st.sidebar:
    # Header with username and logout
    col_brand, col_logout = st.columns([4, 1])
    with col_brand:
        st.markdown(f"#### 🧪 {st.session_state.username}")
    with col_logout:
        if st.button("↩", help="Sign out", type="tertiary"):
            st.session_state.user_id = None
            st.session_state.username = None
            st.session_state.is_admin = False
            st.session_state.preferences = {}
            st.session_state.messages = []
            st.session_state.conversation_id = None
            st.rerun()

    # New Chat
    if st.button("✨  New Chat", use_container_width=True, type="primary"):
        st.session_state.messages = []
        st.session_state.conversation_id = None
        st.rerun()

    st.divider()

    # Settings — Model + Temperature visible, rest in Advanced
    st.caption("SETTINGS")

    if st.session_state.models:
        model_options = ["Auto (recommended)"] + st.session_state.models
        default_idx = 0
        if default_model in model_options:
            default_idx = model_options.index(default_model)
        selected_option = st.selectbox(
            "Model",
            model_options,
            index=default_idx,
            key="pref_model",
            help="Auto routes to the best model based on your message.",
            on_change=_save_preferences,
        )
        if selected_option == "Auto (recommended)":
            selected_model = None
        else:
            selected_model = selected_option
    else:
        selected_model = st.text_input("Model", value="mistral:7b")
        st.warning("Could not fetch models from gateway")

    temperature = st.slider(
        "Temperature", 0.0, 1.0, default_temp, 0.1,
        key="pref_temperature",
        on_change=_save_preferences,
    )

    with st.expander("Advanced"):
        num_predict = st.slider(
            "Max response length",
            64, 4096, 1024, 64,
            help="Limit how long the response can be (in tokens, ~0.75 words each)",
        )
        top_p = st.slider(
            "Top P",
            0.0, 1.0, 0.9, 0.05,
            help="Controls diversity. Lower = more focused, higher = more creative",
        )
        system_prompt = st.text_area(
            "System prompt",
            value="",
            height=80,
            help="Optional instructions the model follows for every message",
            placeholder="e.g. You are a helpful cooking assistant",
        )
        use_rag = st.toggle(
            "Use documents (RAG)",
            value=False,
            help="Ground answers in your uploaded documents",
        )

        # File upload for RAG ingestion
        st.caption("UPLOAD DOCUMENT")
        uploaded_file = st.file_uploader(
            "Upload a file to use with RAG",
            type=["txt", "md", "pdf", "py", "js", "go", "sh", "yaml", "json", "sql"],
            label_visibility="collapsed",
        )
        if uploaded_file is not None:
            if st.button("Ingest document", use_container_width=True):
                with st.spinner("Processing..."):
                    try:
                        resp = httpx.post(
                            f"{GATEWAY_URL}/ingest",
                            files={"file": (uploaded_file.name, uploaded_file.getvalue())},
                            timeout=120.0,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        st.success(f"Ingested {data['source']} ({data['num_chunks']} chunks)")
                    except Exception as e:
                        st.error(f"Failed to ingest: {e}")

    st.divider()

    # Conversation history — filtered by user
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
                    if st.button(
                        label,
                        key=f"conv_{conv['id']}",
                        use_container_width=True,
                    ):
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

    st.divider()

    # Account section — change PIN
    with st.expander("Account"):
        st.caption("CHANGE PIN")
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

    # Admin panel — only visible to admins
    if st.session_state.is_admin:
        with st.expander("Admin"):
            st.caption("USER MANAGEMENT")
            try:
                users_resp = httpx.get(
                    f"{GATEWAY_URL}/admin/users",
                    params={"admin_user_id": st.session_state.user_id},
                    timeout=5.0,
                )
                all_users = users_resp.json().get("users", []) if users_resp.status_code == 200 else []
            except Exception:
                all_users = []

            for u in all_users:
                col_name, col_admin, col_del = st.columns([3, 1, 1])
                with col_name:
                    admin_badge = " (admin)" if u.get("is_admin") else ""
                    st.text(f"{u['username']}{admin_badge}")
                with col_admin:
                    if u["id"] != st.session_state.user_id:
                        new_admin = not u.get("is_admin", False)
                        label = "+" if new_admin else "-"
                        if st.button(label, key=f"adm_{u['id']}", help="Toggle admin"):
                            try:
                                httpx.post(
                                    f"{GATEWAY_URL}/admin/toggle-admin",
                                    json={
                                        "admin_user_id": st.session_state.user_id,
                                        "target_user_id": u["id"],
                                        "is_admin": new_admin,
                                    },
                                    timeout=10.0,
                                )
                                st.rerun()
                            except Exception:
                                st.error("Failed")
                with col_del:
                    if u["id"] != st.session_state.user_id:
                        if st.button("🗑", key=f"delusr_{u['id']}", type="tertiary"):
                            try:
                                httpx.post(
                                    f"{GATEWAY_URL}/admin/delete-user",
                                    json={
                                        "admin_user_id": st.session_state.user_id,
                                        "target_user_id": u["id"],
                                    },
                                    timeout=10.0,
                                )
                                st.rerun()
                            except Exception:
                                st.error("Failed")

            st.caption("RESET USER PIN")
            if all_users:
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

# --- Main chat area ---

# Welcome screen when no messages
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
    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

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
                st.session_state.conversation_id = data.get("conversation_id")
            except Exception as e:
                answer = f"Error: {e}"
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
