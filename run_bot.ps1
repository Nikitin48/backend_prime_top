# PowerShell script to activate virtualenv and run Telegram bot
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# Activate venv (virtualenv расположен на уровень выше корня проекта: hakaton\.venv)
& "$root\..\.venv\Scripts\Activate.ps1"

# Env vars (override if already set outside)
if (-not $env:TELEGRAM_BOT_TOKEN) {
    $env:TELEGRAM_BOT_TOKEN = "8538348155:AAHGYDfbYuQjZg1knLZPM3TAfgKWtQDH9TU"
}
if (-not $env:API_BASE_URL) {
    $env:API_BASE_URL = "http://localhost:8000/api"
}
if (-not $env:NOTIFY_TG_ENABLED) {
    $env:NOTIFY_TG_ENABLED = "true"
}

# Run bot
cd $root
python -m bot.bot
