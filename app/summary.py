from datetime import datetime, timedelta
from typing import List, Dict

import pytz
from dateutil import parser as date_parser

from app.config import Settings
from app.calendar_client import get_today_events
from app.utils import parse_hhmm, get_timezone


def _parse_event_time(value: Dict, tz):
    if "dateTime" in value:
        dt = date_parser.isoparse(value["dateTime"])
        return dt.astimezone(tz)
    if "date" in value:
        dt = date_parser.isoparse(value["date"])
        if dt.tzinfo is None:
            dt = tz.localize(datetime(dt.year, dt.month, dt.day, 0, 0, 0))
        return dt
    return None


def _working_window(day: datetime):
    tz = get_timezone()
    start_h, start_m = parse_hhmm(Settings.WORKING_HOURS_START)
    end_h, end_m = parse_hhmm(Settings.WORKING_HOURS_END)
    start = tz.localize(datetime(day.year, day.month, day.day, start_h, start_m, 0))
    end = tz.localize(datetime(day.year, day.month, day.day, end_h, end_m, 0))
    return start, end


def _merge_intervals(intervals):
    if not intervals:
        return []
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for current in intervals[1:]:
        last = merged[-1]
        if current[0] <= last[1]:
            merged[-1] = (last[0], max(last[1], current[1]))
        else:
            merged.append(current)
    return merged


def _calculate_busy_minutes(events, window_start, window_end):
    intervals = []
    for ev in events:
        if ev.get("allDay"):
            start = window_start
            end = window_end
        else:
            start = _parse_event_time(ev.get("start", {}), window_start.tzinfo)
            end = _parse_event_time(ev.get("end", {}), window_end.tzinfo)
            if not start or not end:
                continue
        if end <= window_start or start >= window_end:
            continue
        clipped_start = max(start, window_start)
        clipped_end = min(end, window_end)
        if clipped_end > clipped_start:
            intervals.append((clipped_start, clipped_end))

    merged = _merge_intervals(intervals)
    total_minutes = 0
    for start, end in merged:
        total_minutes += int((end - start).total_seconds() / 60)
    return total_minutes


def get_today_summary():
    tz = get_timezone()
    now = datetime.now(tz)
    work_start, work_end = _working_window(now)
    events = get_today_events()

    busy_minutes = _calculate_busy_minutes(events, work_start, work_end)
    working_minutes = int((work_end - work_start).total_seconds() / 60)
    spare_minutes = max(0, working_minutes - busy_minutes)

    lines = []
    for ev in events[:8]:
        if ev.get("allDay"):
            lines.append(f"- All-day: {ev.get('title')} ({ev.get('calendarId')})")
        else:
            start = _parse_event_time(ev.get("start", {}), tz)
            end = _parse_event_time(ev.get("end", {}), tz)
            if not start or not end:
                continue
            lines.append(
                f"- {start.strftime('%H:%M')}-{end.strftime('%H:%M')} {ev.get('title')} ({ev.get('calendarId')})"
            )

    return {
        "lines": lines,
        "busy_minutes": busy_minutes,
        "spare_minutes": spare_minutes,
        "work_start": work_start,
        "work_end": work_end,
    }


def format_minutes(minutes: int) -> str:
    hrs = minutes // 60
    mins = minutes % 60
    if hrs and mins:
        return f"{hrs}h {mins}m"
    if hrs:
        return f"{hrs}h"
    return f"{mins}m"


def format_summary_message(summary: Dict) -> str:
    tz = get_timezone()
    work_start = summary["work_start"].astimezone(tz).strftime("%H:%M")
    work_end = summary["work_end"].astimezone(tz).strftime("%H:%M")
    lines = [f"Today\nWorking window: {work_start}-{work_end}"]

    if summary["lines"]:
        lines.append("Events:")
        lines.extend(summary["lines"])
    else:
        lines.append("Events: (none)")

    lines.append(f"Busy: {format_minutes(summary['busy_minutes'])}")
    lines.append(f"Spare: {format_minutes(summary['spare_minutes'])}")
    return "\n".join(lines)
