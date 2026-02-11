API keys and secrets you must set up
- TELEGRAM_BOT_TOKEN: Create via BotFather in Telegram (/newbot). Save the token.
- GITHUB_TOKEN: Personal Access Token (classic) with repo scope. Used for GitHub Contents API (create/update files).

No extra API key needed
- Google Calendar: Using CalendarApp does not require an external API key. The script will prompt for OAuth consent on first run.

Required config values (non-secret but required)
- GITHUB_OWNER: your GitHub username (owner is you)
- GITHUB_REPO: repo name
- CALENDAR_ID: usually "primary" or a specific calendar ID
- TIMEZONE: America/Los_Angeles
- WORKING_HOURS_START: 09:00
- WORKING_HOURS_END: 21:00
- TELEGRAM_ADMIN_CHAT_ID: your chat id (captured from first message or set manually)

Where to store
- All secrets and config values should be stored in Script Properties via PropertiesService.

One-time setup steps
- Deploy GAS as Web App (execute as you, access: anyone with link) and note the Web App URL.
- Set Telegram webhook to the GAS Web App URL.
- Create time-based triggers for morning and 21:00 check-in in the GAS project.
