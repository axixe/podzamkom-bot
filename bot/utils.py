from __future__ import annotations

from datetime import datetime


def normalize_username(username: str | None) -> str | None:
    if not username:
        return None
    username = username.strip()
    if not username.startswith("@"):
        username = f"@{username}"
    return username.lower()


def now_iso() -> str:
    return datetime.now().isoformat()


def is_same_day(iso_string: str | None) -> bool:
    if not iso_string:
        return False
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.date() == datetime.now().date()
    except ValueError:
        return False
