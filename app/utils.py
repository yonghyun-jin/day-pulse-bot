from datetime import datetime

import pytz

from app.config import Settings


def get_timezone():
    return pytz.timezone(Settings.TIMEZONE)


def get_today_date_str():
    tz = get_timezone()
    return datetime.now(tz).strftime("%Y-%m-%d")


def parse_hhmm(value: str):
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("Invalid time format, expected HH:MM")
    return int(parts[0]), int(parts[1])
