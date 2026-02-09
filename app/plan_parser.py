import re
from datetime import datetime, timedelta

import pytz

from app.config import Settings


TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)
HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours)\b", re.IGNORECASE)
MINS_RE = re.compile(r"(\d+)\s*(m|min|mins|minute|minutes)\b", re.IGNORECASE)


def parse_plan(text: str, base_dt: datetime = None):
    raw = text.strip()
    if not raw:
        return None

    time_match = TIME_RE.search(raw)
    if not time_match:
        return None

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    ampm = (time_match.group(3) or "").lower()

    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    if hour > 23 or minute > 59:
        return None

    duration_minutes = None
    hours_match = HOURS_RE.search(raw)
    if hours_match:
        duration_minutes = int(float(hours_match.group(1)) * 60)

    mins_match = MINS_RE.search(raw)
    if mins_match:
        duration_minutes = int(mins_match.group(1))

    if not duration_minutes or duration_minutes <= 0:
        duration_minutes = 60

    tz = pytz.timezone(Settings.TIMEZONE)
    base = base_dt.astimezone(tz) if base_dt else datetime.now(tz)
    start = tz.localize(datetime(base.year, base.month, base.day, hour, minute, 0))
    end = start + timedelta(minutes=duration_minutes)

    title = raw
    title = title.replace(time_match.group(0), "")
    if hours_match:
        title = title.replace(hours_match.group(0), "")
    if mins_match:
        title = title.replace(mins_match.group(0), "")
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
