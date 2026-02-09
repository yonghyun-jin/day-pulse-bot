from datetime import datetime, timedelta
from typing import List, Dict

import pytz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import Settings


def _get_credentials() -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=Settings.GOOGLE_REFRESH_TOKEN,
        token_uri=Settings.GOOGLE_TOKEN_URI,
        client_id=Settings.GOOGLE_CLIENT_ID,
        client_secret=Settings.GOOGLE_CLIENT_SECRET,
        scopes=[
            "https://www.googleapis.com/auth/calendar",
        ],
    )
    creds.refresh(Request())
    return creds


def _build_service():
    creds = _get_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _parse_calendar_ids() -> List[str]:
    if Settings.CALENDAR_IDS:
        return [c.strip() for c in Settings.CALENDAR_IDS.split(",") if c.strip()]
    if Settings.PLAN_CALENDAR_ID:
        return [Settings.PLAN_CALENDAR_ID]
    return []


def get_today_events() -> List[Dict]:
    service = _build_service()
    tz = pytz.timezone(Settings.TIMEZONE)
    now = datetime.now(tz)
    day_start = tz.localize(datetime(now.year, now.month, now.day, 0, 0, 0))
    day_end = day_start + timedelta(days=1)

    events = []
    for calendar_id in _parse_calendar_ids():
        page_token = None
        while True:
            resp = service.events().list(
                calendarId=calendar_id,
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            ).execute()
            for item in resp.get("items", []):
                start = item.get("start", {})
                end = item.get("end", {})
                events.append(
                    {
                        "title": item.get("summary", "(no title)"),
                        "start": start,
                        "end": end,
                        "allDay": "date" in start,
                        "calendarId": calendar_id,
                    }
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    return events


def create_event(title: str, start_dt: datetime, end_dt: datetime) -> Dict:
    service = _build_service()
    calendar_id = Settings.PLAN_CALENDAR_ID or (Settings.CALENDAR_IDS.split(",")[0] if Settings.CALENDAR_IDS else "")
    if not calendar_id:
        raise ValueError("PLAN_CALENDAR_ID or CALENDAR_IDS is required to create events")

    tz = pytz.timezone(Settings.TIMEZONE)
    start_dt = start_dt.astimezone(tz)
    end_dt = end_dt.astimezone(tz)

    event_body = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": Settings.TIMEZONE},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": Settings.TIMEZONE},
        "description": "Created by Telegram bot",
    }

    created = service.events().insert(calendarId=calendar_id, body=event_body).execute()
    return created
