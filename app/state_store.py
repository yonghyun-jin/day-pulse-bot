from database.database import get_app_state, set_app_state

ADMIN_KEY = "ADMIN_CHAT_ID"


def get_admin_chat_id(default_value: str = ""):
    return default_value or (get_app_state(ADMIN_KEY) or "")


def ensure_admin_chat_id(chat_id: str, default_value: str = ""):
    if default_value:
        return default_value
    if not get_app_state(ADMIN_KEY):
        set_app_state(ADMIN_KEY, str(chat_id))
    return get_app_state(ADMIN_KEY)


def get_last_prompt_date(chat_id: str, key_prefix: str):
    return get_app_state(f"{key_prefix}_{chat_id}")


def set_last_prompt_date(chat_id: str, key_prefix: str, date_str: str):
    set_app_state(f"{key_prefix}_{chat_id}", date_str)
