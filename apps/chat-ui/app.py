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

# Sidebar: model selection
with st.sidebar:
    st.header("Settings")
    if st.session_state.models:
        selected_model = st.selectbox("Model", st.session_state.models)
    else:
        selected_model = st.text_input("Model", value="mistral:latest")
        st.warning("Could not fetch models from gateway")
    temperature = st.slider("Temperature", 0.0, 1.0, 0.7, 0.1)

# Chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

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
                resp = httpx.post(
                    f"{GATEWAY_URL}/chat",
                    json={
                        "message": prompt,
                        "model": selected_model,
                        "temperature": temperature,
                        "history": st.session_state.messages[:-1],
                    },
                    timeout=120.0,
                )
                resp.raise_for_status()
                answer = resp.json()["response"]
            except Exception as e:
                answer = f"Error: {e}"
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
