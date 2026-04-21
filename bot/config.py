from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    bot_token: str | None
    admin_username: str
    whitelist: set[str]
    data_file: Path


settings = Settings(
    bot_token=os.getenv("BOT_TOKEN"),
    admin_username=os.getenv("ADMIN_USERNAME", "@axixe"),
    whitelist={
        username.strip()
        for username in os.getenv("WHITELIST", "@asyncr0").split(",")
        if username.strip()
    },
    data_file=Path(os.getenv("DATA_FILE", "bot_data.json")),
)
