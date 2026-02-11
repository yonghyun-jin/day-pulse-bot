from typing import List, Dict, Optional

from openai import OpenAI

from app.config import Settings


MAX_HISTORY_MESSAGES = 12


def _normalize_history(history: Optional[List[Dict]]) -> List[Dict]:
    if not history:
        return []

    developer_message = None
    other_messages: List[Dict] = []

    for item in history:
        role = (item.get("role") or "").strip()
        content = (item.get("content") or "").strip()
        if not role or not content:
            continue
        if role == "system":
            role = "developer"
        if role == "developer":
            if developer_message is None:
                developer_message = {"role": "developer", "content": content}
            continue
        if role in {"user", "assistant"}:
            other_messages.append({"role": role, "content": content})

    if MAX_HISTORY_MESSAGES and len(other_messages) > MAX_HISTORY_MESSAGES:
        other_messages = other_messages[-MAX_HISTORY_MESSAGES:]

    messages: List[Dict] = []
    if developer_message:
        messages.append(developer_message)
    messages.extend(other_messages)
    return messages


def _extract_output_text(response) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    data = response
    if not isinstance(response, dict):
        data = getattr(response, "model_dump", None)
        if callable(data):
            data = data()
        else:
            data = getattr(response, "__dict__", response)

    output = data.get("output", []) if isinstance(data, dict) else []
    chunks: List[str] = []
    for item in output:
        if not isinstance(item, dict):
            item = getattr(item, "__dict__", {})
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if text:
                    chunks.append(text)
    return "\n".join(chunks)


def generate_chat_reply(history: Optional[List[Dict]], user_text: str) -> str:
    if not Settings.OPENAI_TOKEN:
        raise RuntimeError("Missing OPENAI_TOKEN")

    model = Settings.CHATGPT_MODEL or "gpt-4.1-mini"
    client = OpenAI(api_key=Settings.OPENAI_TOKEN)

    messages = _normalize_history(history)
    messages.append({"role": "user", "content": user_text})

    response = client.responses.create(
        model=model,
        input=messages,
    )
    text = _extract_output_text(response).strip()
    return text or "(empty response)"
