from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from html import escape
from typing import Any

from bot.storage import DataStore
from bot.utils import normalize_username


PERIOD_DAY = "day"
PERIOD_WEEK = "week"
PERIOD_MONTH = "month"
PERIODS = {PERIOD_DAY, PERIOD_WEEK, PERIOD_MONTH}


def normalize_period(period: str | None) -> str:
    if period in PERIODS:
        return period
    return PERIOD_DAY


def period_label(period: str) -> str:
    labels = {
        PERIOD_DAY: "День",
        PERIOD_WEEK: "Неделя",
        PERIOD_MONTH: "Месяц",
    }
    return labels.get(period, "День")


def period_start(period: str) -> datetime:
    now = datetime.now()
    if period == PERIOD_WEEK:
        return now - timedelta(days=7)
    if period == PERIOD_MONTH:
        return now - timedelta(days=30)
    return now - timedelta(days=1)


def format_employee_display(employee: dict[str, Any] | None) -> str:
    if not employee:
        return "Неизвестный сотрудник"

    display_name = (employee.get("display_name") or "").strip()
    username = normalize_username(employee.get("username"))

    if display_name and username:
        return f"{display_name} ({username})"
    if display_name:
        return display_name
    if username:
        return username
    return "Неизвестный сотрудник"


def format_employee_display_html(employee: dict[str, Any] | None) -> str:
    if not employee:
        return "Неизвестный сотрудник"
    display_name = (employee.get("display_name") or "").strip()
    username = normalize_username(employee.get("username"))
    if display_name and username:
        return f'<a href="https://t.me/{username.lstrip("@")}">{escape(display_name)}</a>'
    return escape(format_employee_display(employee))


def ensure_employee_identity(store: DataStore, telegram_user_id: int, username: str | None) -> dict[str, Any] | None:
    return store.resolve_employee_identity(telegram_user_id=telegram_user_id, username=username)


def get_allowed_employee(store: DataStore, telegram_user_id: int, username: str | None) -> dict[str, Any] | None:
    return ensure_employee_identity(store, telegram_user_id, username)


def employee_stats(store: DataStore, period: str, employee_id: int | None = None) -> dict[str, Any]:
    data = store.load_data()
    start = period_start(period)

    total = 0
    approved = 0
    rejected = 0
    top_counter: Counter[str] = Counter()

    for item in data["queue"]:
        created_at = _parse_dt(item.get("created_at"))
        if not created_at or created_at < start:
            continue

        if employee_id is not None and item.get("employee_id") != employee_id:
            continue

        total += 1

        if item.get("status") == "approved" and _is_in_period(item.get("reviewed_at"), start):
            approved += 1
        if item.get("status") == "rejected" and _is_in_period(item.get("reviewed_at"), start):
            rejected += 1

        if employee_id is None:
            label = store.resolve_item_employee_label(item)
            top_counter[label] += 1

    top = top_counter.most_common(5)
    return {
        "total": total,
        "approved": approved,
        "rejected": rejected,
        "top": top,
    }


def build_employee_manager_text(store: DataStore, period: str) -> str:
    stats = employee_stats(store, period)
    active_count = store.count_active_employees()

    lines = [
        "Менеджер сотрудников",
        "",
        f"Период: {period_label(period)}",
        f"Активных сотрудников: {active_count}",
        "",
        f"Фото всего: {stats['total']}",
        f"Одобрено: {stats['approved']}",
        f"Отклонено: {stats['rejected']}",
        "",
        "Топ сотрудников:",
    ]

    if stats["top"]:
        lines.extend([f"- {name}: {count}" for name, count in stats["top"]])
    else:
        lines.append("- Нет данных")

    return "\n".join(lines)


def build_employee_card_text(store: DataStore, employee_id: int, period: str) -> str:
    employee = store.get_employee_by_id(employee_id)
    if not employee:
        return "Сотрудник не найден."

    stats = employee_stats(store, period, employee_id=employee_id)
    username = normalize_username(employee.get("username")) or "не указан"
    tg_id = employee.get("telegram_user_id")
    linked = "привязан" if tg_id else "не привязан"
    active_status = "активен" if employee.get("is_active") else "деактивирован"

    return (
        "Карточка сотрудника\n\n"
        f"Имя: {employee.get('display_name') or 'не указано'}\n"
        f"Username: {username}\n"
        f"Telegram user id: {tg_id or 'не указан'}\n"
        f"Статус: {linked}, {active_status}\n\n"
        f"Период: {period_label(period)}\n"
        f"Фото всего: {stats['total']}\n"
        f"Одобрено: {stats['approved']}\n"
        f"Отклонено: {stats['rejected']}"
    )


def _parse_dt(iso_string: str | None) -> datetime | None:
    if not iso_string:
        return None
    try:
        return datetime.fromisoformat(iso_string)
    except ValueError:
        return None


def _is_in_period(iso_string: str | None, start: datetime) -> bool:
    dt = _parse_dt(iso_string)
    return bool(dt and dt >= start)
