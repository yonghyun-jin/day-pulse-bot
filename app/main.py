import json
import logging

from dateutil import parser as date_parser

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater

from app.calendar_client import create_event
from app.config import Settings
from app.github_client import (
    append_morning_log,
    append_night_log,
    append_plan_log,
    assert_github_config,
)
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
    set_user_state,
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

    mood = extract("mood")
    worry = extract("worry")
    must_do = extract("must-do") or extract("must do")

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
        handle_morning_response(update, context, telegram_id, text)
        return

    if state == STATE_WAIT_PLAN_CONFIRM:
        handle_plan_confirmation(update, context, telegram_id, text, state_data)
        return

    if state == STATE_WAIT_NIGHT:
        handle_night_response(update, context, telegram_id, text)
        return

    handle_plan_candidate(update, context, telegram_id, text)


def handle_morning_response(update, context, telegram_id, text):
    parsed = parse_morning_response(text)
    date_str = get_today_date_str()

    try:
        assert_github_config()
        append_morning_log(date_str, parsed["mood"], parsed["worry"], parsed["must_do"])
    except Exception:
        logging.exception("GitHub morning log failed")
        update.message.reply_text("Morning log failed. Check GitHub config.")

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
        update.message.reply_text("Could not parse. Example: 3pm 2h Lombard")
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


def handle_night_response(update, context, telegram_id, text):
    try:
        append_night_log(get_today_date_str(), text)
        update.message.reply_text("Saved. Good night.")
    except Exception:
        logging.exception("Night log failed")
        update.message.reply_text("Night log failed. Check GitHub config.")
    set_user_state(telegram_id, STATE_NONE, last_date=get_today_date_str())


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


def start_scheduler(bot):
    scheduler = BackgroundScheduler(timezone=Settings.TIMEZONE)
    morning_h, morning_m = parse_hhmm(Settings.MORNING_PROMPT_TIME)
    night_h, night_m = parse_hhmm(Settings.NIGHT_PROMPT_TIME)

    scheduler.add_job(
        lambda: run_morning_job(bot),
        CronTrigger(hour=morning_h, minute=morning_m),
        name="morning_prompt",
    )
    scheduler.add_job(
        lambda: run_night_job(bot),
        CronTrigger(hour=night_h, minute=night_m),
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
