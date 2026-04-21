from bot.app import create_application
from bot.logging_config import logger


def main() -> None:
    app = create_application()
    logger.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
