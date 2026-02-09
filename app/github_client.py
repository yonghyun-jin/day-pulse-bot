import base64
import json
from datetime import datetime
from typing import Optional

import requests

from app.config import Settings


def _headers():
    return {
        "Authorization": f"token {Settings.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _api_url(path: str) -> str:
    return f"https://api.github.com{path}"


def _daily_path(date_str: str) -> str:
    return f"daily/{date_str}.md"


def _get_file(path: str):
    url = _api_url(f"/repos/{Settings.GITHUB_OWNER}/{Settings.GITHUB_REPO}/contents/{path}")
    res = requests.get(url, headers=_headers(), timeout=30)
    if res.status_code == 200:
        return res.json()
    if res.status_code == 404:
        return None
    raise RuntimeError(f"GitHub GET failed: {res.status_code} {res.text}")


def _put_file(path: str, content: str, sha: Optional[str], message: str):
    url = _api_url(f"/repos/{Settings.GITHUB_OWNER}/{Settings.GITHUB_REPO}/contents/{path}")
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha
    res = requests.put(url, headers=_headers(), json=payload, timeout=30)
    if res.status_code in (200, 201):
        return res.json()
    raise RuntimeError(f"GitHub PUT failed: {res.status_code} {res.text}")


def _template(date_str: str) -> str:
    return (
        f"# {date_str}\n\n"
        "## Morning\n"
        "- Mood: \n"
        "- Worry: \n"
        "- Must-do: \n\n"
        "## Plan (optional)\n"
        "- Planned Blocks:\n\n"
        "## 21:00 Check-in\n"
        "- How was today: \n"
    )


def _append_to_section(content: str, header: str, lines: list) -> str:
    insert_text = "\n".join(lines) + "\n"
    idx = content.find(header)
    if idx == -1:
        return content.rstrip() + f"\n\n{header}\n" + insert_text

    next_header_idx = content.find("\n## ", idx + len(header))
    insert_pos = len(content) if next_header_idx == -1 else next_header_idx + 1
    before = content[:insert_pos].rstrip()
    after = content[insert_pos:].lstrip()
    return before + "\n" + insert_text + "\n" + after


def ensure_daily_file(date_str: str):
    path = _daily_path(date_str)
    file_data = _get_file(path)
    if file_data:
        content = base64.b64decode(file_data["content"]).decode("utf-8")
        return {"path": path, "content": content, "sha": file_data["sha"]}

    content = _template(date_str)
    created = _put_file(path, content, None, f"Create daily log {date_str}")
    return {"path": path, "content": content, "sha": created["content"]["sha"]}


def append_morning_log(date_str: str, mood: str, worry: str, must_do: str):
    file_data = ensure_daily_file(date_str)
    lines = [f"- Mood: {mood}", f"- Worry: {worry}", f"- Must-do: {must_do}"]
    updated = _append_to_section(file_data["content"], "## Morning", lines)
    _put_file(file_data["path"], updated, file_data["sha"], f"Update morning log {date_str}")


def append_plan_log(date_str: str, time_range: str, title: str):
    file_data = ensure_daily_file(date_str)
    lines = [f"- {time_range} {title}"]
    updated = _append_to_section(file_data["content"], "## Plan (optional)", lines)
    _put_file(file_data["path"], updated, file_data["sha"], f"Update plan log {date_str}")


def append_night_log(date_str: str, text: str):
    file_data = ensure_daily_file(date_str)
    lines = [f"- How was today: {text}"]
    updated = _append_to_section(file_data["content"], "## 21:00 Check-in", lines)
    _put_file(file_data["path"], updated, file_data["sha"], f"Update night log {date_str}")


def assert_github_config():
    missing = []
    if not Settings.GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN")
    if not Settings.GITHUB_OWNER:
        missing.append("GITHUB_OWNER")
    if not Settings.GITHUB_REPO:
        missing.append("GITHUB_REPO")
    if missing:
        raise RuntimeError("Missing GitHub config: " + ", ".join(missing))
