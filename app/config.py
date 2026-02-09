import os
from dotenv import load_dotenv

load_dotenv("app/.env")


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class Settings:
    # App
    MODE = os.environ.get("MODE", "webhook")
    PORT = int(os.environ.get("PORT", 5000))
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Telegram
    TELEGRAM_TOKEN = os.environ.get("API_TELEGRAM", "")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
    AUTO_SET_WEBHOOK = _as_bool(os.environ.get("AUTO_SET_WEBHOOK", "false"))
    ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")

    # OpenAI (optional)
    OPENAI_TOKEN = os.environ.get("OPENAI_TOKEN", "")
    CHATGPT_MODEL = os.environ.get("CHATGPT_MODEL", "gpt-3.5-turbo")

    # Google Calendar
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
    GOOGLE_TOKEN_URI = os.environ.get("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")
    CALENDAR_IDS = os.environ.get("CALENDAR_IDS", "")
    PLAN_CALENDAR_ID = os.environ.get("PLAN_CALENDAR_ID", "")

    # GitHub
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
    GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "")
    GITHUB_REPO = os.environ.get("GITHUB_REPO", "")

    # Scheduling
    TIMEZONE = os.environ.get("TIMEZONE", "America/Los_Angeles")
    WORKING_HOURS_START = os.environ.get("WORKING_HOURS_START", "09:00")
    WORKING_HOURS_END = os.environ.get("WORKING_HOURS_END", "21:00")
    MORNING_PROMPT_TIME = os.environ.get("MORNING_PROMPT_TIME", "08:30")
    NIGHT_PROMPT_TIME = os.environ.get("NIGHT_PROMPT_TIME", "21:00")

    # Database (Railway provides these automatically)
    PGDATABASE = os.environ.get("PGDATABASE", "")
    PGHOST = os.environ.get("PGHOST", "")
    PGPASSWORD = os.environ.get("PGPASSWORD", "")
    PGPORT = os.environ.get("PGPORT", "")
    PGUSER = os.environ.get("PGUSER", "")
