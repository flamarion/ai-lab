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

/* ---- Model chip shown above chat ---- */
.model-chip {
    display: inline-block;
    background: #f0f0fa;
    color: #6366f1;
    padding: 3px 12px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 500;
    margin-bottom: 0.5rem;
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


# --- Session state init ---

if "models" not in st.session_state:
    try:
        resp = httpx.get(f"{GATEWAY_URL}/models", timeout=10.0)
        st.session_state.models = resp.json()["models"]
    except Exception:
        st.session_state.models = []

if "messages" not in st.session_state:
    st.session_state.messages = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None

# --- Sidebar ---
with st.sidebar:
    # App branding
    st.markdown("#### 🧪 AI Lab")

    # New Chat
    if st.button("✨  New Chat", use_container_width=True, type="primary"):
        st.session_state.messages = []
        st.session_state.conversation_id = None
        st.rerun()

    st.divider()

    # Conversation history
    st.caption("RECENT CONVERSATIONS")
    try:
        conv_resp = httpx.get(f"{GATEWAY_URL}/conversations", timeout=10.0)
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

    # Settings
    st.caption("SETTINGS")

    # Model selector — "Auto" routes to the server default
    if st.session_state.models:
        model_options = ["Auto (recommended)"] + st.session_state.models
        selected_option = st.selectbox(
            "Model",
            model_options,
            help="Auto uses the default model. Pick a specific model to override.",
        )
        if selected_option == "Auto (recommended)":
            selected_model = None  # gateway will use its default
        else:
            selected_model = selected_option
    else:
        selected_model = st.text_input("Model", value="mistral:7b")
        st.warning("Could not fetch models from gateway")

    temperature = st.slider("Temperature", 0.0, 1.0, 0.7, 0.1)

    with st.expander("Advanced"):
        num_predict = st.slider(
            "Max response length",
            64,
            4096,
            1024,
            64,
            help="Limit how long the response can be (in tokens, ~0.75 words each)",
        )
        top_p = st.slider(
            "Top P",
            0.0,
            1.0,
            0.9,
            0.05,
            help="Controls diversity. Lower = more focused, higher = more creative",
        )
        system_prompt = st.text_area(
            "System prompt",
            value="",
            height=80,
            help="Optional instructions the model follows for every message",
            placeholder="e.g. You are a helpful cooking assistant",
        )

# --- Main chat area ---

# Welcome screen when no messages
if not st.session_state.messages:
    st.markdown(
        """
    <div class="welcome-box">
        <div class="welcome-icon">🧪</div>
        <div class="welcome-title">Welcome to AI Lab</div>
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
                }
                if selected_model:
                    payload["model"] = selected_model
                if top_p != 0.9:
                    payload["top_p"] = top_p
                if num_predict != 1024:
                    payload["num_predict"] = num_predict
                if system_prompt.strip():
                    payload["system_prompt"] = system_prompt
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
