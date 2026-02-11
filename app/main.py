import json
import logging
import re
import sys
import types

try:
    import pkg_resources  # type: ignore
except Exception:
    import importlib.metadata as importlib_metadata

    pkg_resources = types.ModuleType("pkg_resources")

    class DistributionNotFound(Exception):
        pass

    def get_distribution(name):
        try:
            version = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError as exc:
            raise DistributionNotFound(str(exc)) from exc
        return types.SimpleNamespace(version=version)

    def iter_entry_points(group, name=None):
        try:
            eps = importlib_metadata.entry_points()
        except Exception:
            return []
        if hasattr(eps, "select"):
            eps = eps.select(group=group)
        else:
            eps = eps.get(group, [])
        if name is not None:
            eps = [ep for ep in eps if ep.name == name]
        return eps

    pkg_resources.DistributionNotFound = DistributionNotFound
    pkg_resources.get_distribution = get_distribution
    pkg_resources.iter_entry_points = iter_entry_points
    sys.modules["pkg_resources"] = pkg_resources

from dateutil import parser as date_parser

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater

from app.calendar_client import create_event
from app.config import Settings
from app.github_client import (
    append_morning_log,
    append_night_log,
    append_note_log,
    append_plan_log,
    append_todo_log,
    assert_github_config,
)
from app.llm_client import generate_chat_reply
from app.plan_parser import parse_plan
from app.state_store import (
    ensure_admin_chat_id,
    get_admin_chat_id,
    get_last_prompt_date,
    set_last_prompt_date,
)
from app.summary import format_summary_message, get_today_summary
from app.utils import get_today_date_str, parse_hhmm
from database.database import (
    add_new_user,
    clear_pending_plan,
    create_db,
    get_user_state,
    retrieve_history,
    set_user_state,
    update_history_user,
)

STATE_NONE = "NONE"
STATE_WAIT_MORNING = "WAIT_MORNING"
STATE_WAIT_PLAN = "WAIT_PLAN"
STATE_WAIT_PLAN_CONFIRM = "WAIT_PLAN_CONFIRM"
STATE_WAIT_NIGHT = "WAIT_NIGHT"


def split_message(text, max_len=3900):
    if len(text) <= max_len:
        return [text]
    chunks = []
    remaining = text
    while len(remaining) > max_len:
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at < 1000:
            split_at = max_len
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def send_text(bot, chat_id, text):
    for chunk in split_message(text):
        bot.send_message(chat_id=chat_id, text=chunk)


def parse_morning_response(text):
    mood = ""
    worry = ""
    must_do = ""

    def extract(label):
        for line in text.split("\n"):
            if line.lower().startswith(label + ":"):
                return line.split(":", 1)[1].strip()
        return ""

    def extract_any(labels):
        for label in labels:
            value = extract(label)
            if value:
                return value
        return ""

    mood = extract_any(["mood", "기분"])
    worry = extract_any(["worry", "걱정"])
    must_do = extract_any(["must-do", "must do", "할일", "해야할일", "해야 할 일"])

    if not (mood and worry and must_do):
        parts = [p.strip() for p in text.replace(";", "\n").split("\n") if p.strip()]
        if not mood and parts:
            mood = parts[0]
        if not worry and len(parts) > 1:
            worry = parts[1]
        if not must_do and len(parts) > 2:
            must_do = parts[2]

    return {
        "mood": mood or "(empty)",
        "worry": worry or "(empty)",
        "must_do": must_do or "(empty)",
    }


PLAN_TIME_RE = re.compile(
    r"(\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*(am|pm)\b|(?:오전|오후)?\s*\d{1,2}\s*시)",
    re.IGNORECASE,
)
PLAN_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(h|hr|hrs|hour|hours|시간)|\d+\s*(m|min|mins|minute|minutes|분))",
    re.IGNORECASE,
)
MORNING_LABEL_RE = re.compile(
    r"^(mood|worry|must[- ]?do|기분|걱정|할일|해야\s*할\s*일)\s*[:：]",
    re.IGNORECASE,
)
MORNING_PREFIX_RE = re.compile(
    r"^(mood|worry|must[- ]?do|기분|걱정|할일|해야\s*할\s*일)\b",
    re.IGNORECASE,
)
NIGHT_HINT_RE = re.compile(r"(오늘|하루).*(어땠|어떻|어때|어떴|어땟)|check-?in|회고", re.IGNORECASE)


def looks_like_morning_response(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any(MORNING_LABEL_RE.search(line) for line in lines):
        return True
    if lines and MORNING_PREFIX_RE.search(lines[0]):
        return True
    keywords = ["mood", "worry", "must-do", "must do", "기분", "걱정", "할일", "해야 할 일"]
    hits = sum(1 for k in keywords if k in text.lower())
    return hits >= 2 and len(lines) >= 2


def looks_like_night_response(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith("?"):
        return False
    return bool(NIGHT_HINT_RE.search(text))


def looks_like_plan(text: str) -> bool:
    if not PLAN_TIME_RE.search(text):
        return False
    if looks_like_morning_response(text) or looks_like_night_response(text):
        return False
    if PLAN_DURATION_RE.search(text):
        return True
    remainder = PLAN_TIME_RE.sub("", text).strip()
    return bool(remainder)


def serialize_plan(plan):
    return {
        "title": plan["title"],
        "start": plan["start"].isoformat(),
        "end": plan["end"].isoformat(),
        "duration_minutes": plan["duration_minutes"],
        "raw": plan["raw"],
    }


def deserialize_plan(raw):
    if not raw:
        return None
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    if "start" in data and isinstance(data["start"], str):
        data["start"] = date_parser.isoparse(data["start"])
    if "end" in data and isinstance(data["end"], str):
        data["end"] = date_parser.isoparse(data["end"])
    return data


def help_command_handler(update, context):
    update.message.reply_text(
        "Commands:\n"
        "/start\n"
        "/help\n"
        "/summary\n"
        "/morning\n"
        "/night\n"
        "/todo\n"
        "/note\n"
        "/status\n\n"
        "Plan example: 3pm 2h Lombard"
    )


def start_command_handler(update, context):
    telegram_id = str(update.message.chat.id)
    add_new_user(telegram_id)
    ensure_admin_chat_id(telegram_id, Settings.ADMIN_CHAT_ID)
    update.message.reply_text(
        "Connected. You will receive daily prompts.\n"
        "Use /summary for today, and send a plan like '3pm 2h Lombard'."
    )


def status_command_handler(update, context):
    telegram_id = str(update.message.chat.id)
    state_data = get_user_state(telegram_id)
    update.message.reply_text(f"State: {state_data['state']}")


def summary_command_handler(update, context):
    try:
        summary = get_today_summary()
        send_text(context.bot, update.message.chat.id, format_summary_message(summary))
    except Exception as err:
        logging.exception("Summary failed")
        update.message.reply_text("Calendar summary failed. Check calendar config.")


def handle_text(update, context):
    telegram_id = str(update.message.chat.id)
    text = (update.message.text or "").strip()
    if not text:
        return

    state_data = get_user_state(telegram_id)
    state = state_data["state"]

    if state == STATE_WAIT_MORNING:
        handle_morning_response(update, context, telegram_id, text, followup=True)
        return

    if state == STATE_WAIT_PLAN_CONFIRM:
        handle_plan_confirmation(update, context, telegram_id, text, state_data)
        return

    if state == STATE_WAIT_NIGHT:
        handle_night_response(update, context, telegram_id, text, followup=True)
        return

    if looks_like_morning_response(text):
        handle_morning_response(update, context, telegram_id, text, followup=False)
        return

    if looks_like_night_response(text):
        handle_night_response(update, context, telegram_id, text, followup=False)
        return

    if state == STATE_WAIT_PLAN:
        if text.lower() in {"skip", "no", "none", "pass"}:
            handle_plan_candidate(update, context, telegram_id, text)
            return
        if looks_like_plan(text):
            handle_plan_candidate(update, context, telegram_id, text)
            return
        handle_chat(update, context, telegram_id, text)
        return

    if looks_like_plan(text):
        handle_plan_candidate(update, context, telegram_id, text)
        return

    handle_chat(update, context, telegram_id, text)


def handle_morning_response(update, context, telegram_id, text, followup: bool = True):
    parsed = parse_morning_response(text)
    date_str = get_today_date_str()

    try:
        assert_github_config()
        append_morning_log(date_str, parsed["mood"], parsed["worry"], parsed["must_do"])
    except Exception:
        logging.exception("GitHub morning log failed")
        update.message.reply_text("Morning log failed. Check GitHub config.")
        return

    if not followup:
        update.message.reply_text("Morning log saved.")
        return

    try:
        summary = get_today_summary()
        send_text(context.bot, telegram_id, format_summary_message(summary))
    except Exception:
        logging.exception("Summary failed")
        update.message.reply_text("Calendar summary failed. Check calendar config.")

    update.message.reply_text("Send a plan like '3pm 2h Lombard', or reply 'skip'.")
    set_user_state(telegram_id, STATE_WAIT_PLAN, last_date=date_str)


def handle_plan_candidate(update, context, telegram_id, text):
    if text.lower() in {"skip", "no", "none", "pass"}:
        update.message.reply_text("OK, no plan added.")
        set_user_state(telegram_id, STATE_NONE, last_date=get_today_date_str())
        return

    plan = parse_plan(text)
    if not plan:
        update.message.reply_text(
            "Could not parse. Example: 3pm 2h Lombard / 오후 3시 2시간 롬바드"
        )
        return

    serialized = serialize_plan(plan)
    set_user_state(telegram_id, STATE_WAIT_PLAN_CONFIRM, pending_plan=serialized, last_date=get_today_date_str())

    time_range = f"{plan['start'].strftime('%H:%M')}-{plan['end'].strftime('%H:%M')}"
    update.message.reply_text(f"Create event?\n{time_range} {plan['title']}\nReply YES/NO.")


def handle_plan_confirmation(update, context, telegram_id, text, state_data):
    yes = text.lower() in {"yes", "y", "ok", "sure", "confirm"}
    no = text.lower() in {"no", "n", "cancel"}

    if not yes and not no:
        update.message.reply_text("Please reply YES or NO.")
        return

    pending_raw = state_data.get("pending_plan")
    plan = deserialize_plan(pending_raw)
    clear_pending_plan(telegram_id)
    set_user_state(telegram_id, STATE_NONE, last_date=get_today_date_str())

    if not plan:
        update.message.reply_text("No pending plan found.")
        return

    if no:
        update.message.reply_text("Canceled.")
        return

    try:
        start = plan["start"]
        end = plan["end"]
        create_event(plan["title"], start, end)
        time_range = f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
        append_plan_log(get_today_date_str(), time_range, plan["title"])
        update.message.reply_text("Event created and logged.")
    except Exception:
        logging.exception("Plan insert failed")
        update.message.reply_text("Failed to create event.")


def handle_night_response(update, context, telegram_id, text, followup: bool = True):
    try:
        append_night_log(get_today_date_str(), text)
        update.message.reply_text("Saved. Good night." if followup else "Night log saved.")
    except Exception:
        logging.exception("Night log failed")
        update.message.reply_text("Night log failed. Check GitHub config.")
    if followup:
        set_user_state(telegram_id, STATE_NONE, last_date=get_today_date_str())


def handle_note(update, context, telegram_id, text):
    try:
        assert_github_config()
        append_note_log(get_today_date_str(), text)
        update.message.reply_text("Noted.")
    except Exception:
        logging.exception("Note log failed")
        update.message.reply_text("Note log failed. Check GitHub config.")


def handle_chat(update, context, telegram_id, text):
    try:
        row = retrieve_history(telegram_id)
        if not row:
            add_new_user(telegram_id)
            row = retrieve_history(telegram_id)
        history = json.loads(row[1]) if row else None
        reply = generate_chat_reply(history, text)
        send_text(context.bot, telegram_id, reply)
        update_history_user(telegram_id, text, reply)
    except Exception:
        logging.exception("ChatGPT response failed")
        update.message.reply_text("ChatGPT failed. Check OpenAI config.")


def morning_command_handler(update, context):
    telegram_id = str(update.message.chat.id)
    update.message.reply_text("Reply with:\nMood: ...\nWorry: ...\nMust-do: ...")
    set_user_state(telegram_id, STATE_WAIT_MORNING, last_date=get_today_date_str())


def night_command_handler(update, context):
    telegram_id = str(update.message.chat.id)
    update.message.reply_text("How was today?")
    set_user_state(telegram_id, STATE_WAIT_NIGHT, last_date=get_today_date_str())


def todo_command_handler(update, context):
    telegram_id = str(update.message.chat.id)
    text = (update.message.text or "").strip()
    item = text.split(" ", 1)[1].strip() if " " in text else ""
    if not item:
        update.message.reply_text("Usage: /todo <text>")
        return
    try:
        assert_github_config()
        append_todo_log(get_today_date_str(), item)
        update.message.reply_text("Todo saved.")
    except Exception:
        logging.exception("Todo log failed")
        update.message.reply_text("Todo log failed. Check GitHub config.")


def note_command_handler(update, context):
    telegram_id = str(update.message.chat.id)
    text = (update.message.text or "").strip()
    item = text.split(" ", 1)[1].strip() if " " in text else ""
    if not item:
        update.message.reply_text("Usage: /note <text>")
        return
    try:
        assert_github_config()
        append_note_log(get_today_date_str(), item)
        update.message.reply_text("Noted.")
    except Exception:
        logging.exception("Note log failed")
        update.message.reply_text("Note log failed. Check GitHub config.")


def run_morning_job(bot):
    chat_id = get_admin_chat_id(Settings.ADMIN_CHAT_ID)
    if not chat_id:
        logging.info("No admin chat id set for morning job.")
        return

    today = get_today_date_str()
    if get_last_prompt_date(chat_id, "LAST_MORNING") == today:
        return

    send_text(bot, chat_id, "Good morning. Reply with:\nMood: ...\nWorry: ...\nMust-do: ...")
    set_user_state(chat_id, STATE_WAIT_MORNING, last_date=today)
    set_last_prompt_date(chat_id, "LAST_MORNING", today)


def run_night_job(bot):
    chat_id = get_admin_chat_id(Settings.ADMIN_CHAT_ID)
    if not chat_id:
        logging.info("No admin chat id set for night job.")
        return

    today = get_today_date_str()
    if get_last_prompt_date(chat_id, "LAST_NIGHT") == today:
        return

    send_text(bot, chat_id, "21:00 check-in: How was today?")
    set_user_state(chat_id, STATE_WAIT_NIGHT, last_date=today)
    set_last_prompt_date(chat_id, "LAST_NIGHT", today)


class _ApschedulerTzWrapper:
    def __init__(self, tz):
        self._tz = tz

    def localize(self, dt, is_dst=False):
        if hasattr(self._tz, "localize"):
            return self._tz.localize(dt, is_dst=is_dst)
        return dt.replace(tzinfo=self._tz)

    def normalize(self, dt, is_dst=False):
        if hasattr(self._tz, "normalize"):
            return self._tz.normalize(dt)
        return dt.astimezone(self._tz)

    def __getattr__(self, name):
        return getattr(self._tz, name)


def _get_scheduler_timezone():
    tz = pytz.timezone(Settings.TIMEZONE)
    if hasattr(tz, "localize"):
        return tz
    return _ApschedulerTzWrapper(tz)


def start_scheduler(bot):
    tz = _get_scheduler_timezone()
    scheduler = BackgroundScheduler(timezone=tz)
    morning_h, morning_m = parse_hhmm(Settings.MORNING_PROMPT_TIME)
    night_h, night_m = parse_hhmm(Settings.NIGHT_PROMPT_TIME)

    scheduler.add_job(
        lambda: run_morning_job(bot),
        CronTrigger(hour=morning_h, minute=morning_m, timezone=tz),
        name="morning_prompt",
    )
    scheduler.add_job(
        lambda: run_night_job(bot),
        CronTrigger(hour=night_h, minute=night_m, timezone=tz),
        name="night_prompt",
    )
    scheduler.start()
    return scheduler


def normalize_webhook_url():
    base = Settings.WEBHOOK_URL.strip()
    if not base:
        return ""
    if not base.endswith("/"):
        base += "/"
    return base


def main():
    create_db()

    updater = Updater(Settings.TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("help", help_command_handler))
    dp.add_handler(CommandHandler("start", start_command_handler))
    dp.add_handler(CommandHandler("summary", summary_command_handler))
    dp.add_handler(CommandHandler("morning", morning_command_handler))
    dp.add_handler(CommandHandler("night", night_command_handler))
    dp.add_handler(CommandHandler("todo", todo_command_handler))
    dp.add_handler(CommandHandler("note", note_command_handler))
    dp.add_handler(CommandHandler("status", status_command_handler))

    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))

    dp.add_error_handler(lambda update, context: logging.exception(context.error))

    scheduler = start_scheduler(updater.bot)

    if Settings.MODE == "webhook":
        webhook_url = normalize_webhook_url()
        if not webhook_url:
            raise RuntimeError("WEBHOOK_URL is required in webhook mode")
        updater.start_webhook(
            listen="0.0.0.0",
            port=int(Settings.PORT),
            url_path=Settings.TELEGRAM_TOKEN,
            webhook_url=webhook_url + Settings.TELEGRAM_TOKEN,
        )
        logging.info("Webhook mode on port %s", Settings.PORT)
    else:
        updater.start_polling()
        logging.info("Polling mode")

    updater.idle()
    scheduler.shutdown()


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=Settings.LOG_LEVEL,
    )
    logging.info("Starting bot")
    main()
