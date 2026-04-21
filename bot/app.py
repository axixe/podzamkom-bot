from telegram.ext import Application

from bot.config import settings
from bot.handlers import register_handlers
from bot.storage import DataStore


def create_application() -> Application:
    if not settings.bot_token:
        raise ValueError("Укажи BOT_TOKEN в переменных окружения или .env файле.")

    app = Application.builder().token(settings.bot_token).build()
    register_handlers(app, DataStore(settings.data_file))
    return app
