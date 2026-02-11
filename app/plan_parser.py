import re
from datetime import datetime, timedelta

import pytz

from app.config import Settings


TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)
KOR_TIME_RE = re.compile(
    r"(오전|오후)?\s*(\d{1,2})\s*시(?!간)\s*(?:(\d{1,2})\s*분?)?\s*(반)?",
    re.IGNORECASE,
)
HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|시간)", re.IGNORECASE)
MINS_RE = re.compile(r"(\d+)\s*(m|min|mins|minute|minutes|분)", re.IGNORECASE)


def _apply_ampm(hour: int, ampm: str) -> int:
    if ampm == "pm" and hour < 12:
        return hour + 12
    if ampm == "am" and hour == 12:
        return 0
    return hour


def _extract_time(raw: str):
    kor_match = KOR_TIME_RE.search(raw)
    if kor_match:
        ampm_kr = (kor_match.group(1) or "").lower()
        hour = int(kor_match.group(2))
        minute = 0
        if kor_match.group(3):
            minute = int(kor_match.group(3))
        elif kor_match.group(4):
            minute = 30
        ampm = "am" if ampm_kr == "오전" else "pm" if ampm_kr == "오후" else ""
        hour = _apply_ampm(hour, ampm)
        return hour, minute, kor_match.group(0)

    time_match = TIME_RE.search(raw)
    if not time_match:
        return None
    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    ampm = (time_match.group(3) or "").lower()
    if not ampm:
        if "오후" in raw:
            ampm = "pm"
        elif "오전" in raw:
            ampm = "am"
    hour = _apply_ampm(hour, ampm)
    return hour, minute, time_match.group(0)


def _extract_duration(raw: str) -> int:
    total = 0
    for match in HOURS_RE.finditer(raw):
        total += int(float(match.group(1)) * 60)
    for match in MINS_RE.finditer(raw):
        total += int(match.group(1))
    return total


def parse_plan(text: str, base_dt: datetime = None):
    raw = text.strip()
    if not raw:
        return None

    time_info = _extract_time(raw)
    if not time_info:
        return None
    hour, minute, time_token = time_info

    if hour > 23 or minute > 59:
        return None

    duration_minutes = _extract_duration(raw)

    if not duration_minutes or duration_minutes <= 0:
        duration_minutes = 60

    tz = pytz.timezone(Settings.TIMEZONE)
    base = base_dt.astimezone(tz) if base_dt else datetime.now(tz)
    start = tz.localize(datetime(base.year, base.month, base.day, hour, minute, 0))
    end = start + timedelta(minutes=duration_minutes)

    title = raw.replace(time_token, "")
    for match in HOURS_RE.finditer(raw):
        title = title.replace(match.group(0), "")
    for match in MINS_RE.finditer(raw):
        title = title.replace(match.group(0), "")
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        title = "Planned Block"

    return {
        "title": title,
        "start": start,
        "end": end,
        "duration_minutes": duration_minutes,
        "raw": raw,
    }
