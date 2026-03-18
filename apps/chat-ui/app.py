import os

import httpx
import streamlit as st

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")

st.set_page_config(page_title="AI Lab Chat", page_icon="🧪")
st.title("AI Lab Chat")

# Fetch available models once per session
if "models" not in st.session_state:
    try:
        resp = httpx.get(f"{GATEWAY_URL}/models", timeout=10.0)
        st.session_state.models = resp.json()["models"]
    except Exception:
        st.session_state.models = []

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None

# --- Sidebar ---
with st.sidebar:
    # New Chat button
    if st.button("New Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.conversation_id = None
        st.rerun()

    st.divider()

    # Conversation history
    st.header("Conversations")
    try:
        conv_resp = httpx.get(f"{GATEWAY_URL}/conversations", timeout=10.0)
        if conv_resp.status_code == 200:
            conversations = conv_resp.json().get("conversations", [])
            for conv in conversations:
                col1, col2 = st.columns([5, 1])
                title = conv["title"] or "Untitled"
                is_active = st.session_state.conversation_id == conv["id"]
                with col1:
                    if st.button(
                        f"{'> ' if is_active else ''}{title}",
                        key=f"conv_{conv['id']}",
                        use_container_width=True,
                    ):
                        # Load conversation
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
                    if st.button("X", key=f"del_{conv['id']}"):
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
    st.header("Settings")
    if st.session_state.models:
        selected_model = st.selectbox("Model", st.session_state.models)
    else:
        selected_model = st.text_input("Model", value="mistral:latest")
        st.warning("Could not fetch models from gateway")
    temperature = st.slider("Temperature", 0.0, 1.0, 0.7, 0.1)

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat input
if prompt := st.chat_input("Ask something..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                payload = {
                    "message": prompt,
                    "model": selected_model,
                    "temperature": temperature,
                }
                if st.session_state.conversation_id:
                    payload["conversation_id"] = st.session_state.conversation_id
                else:
                    # Send history for new conversations (before DB assigns an ID)
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
