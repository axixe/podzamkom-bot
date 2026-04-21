from __future__ import annotations

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.config import settings
from bot.keyboards import admin_home_keyboard, moderation_keyboard
from bot.logging_config import logger
from bot.storage import DataStore
from bot.utils import is_same_day, normalize_username, now_iso


def is_admin(username: str | None) -> bool:
    return normalize_username(username) == normalize_username(settings.admin_username)


def is_allowed(username: str | None) -> bool:
    normalized = normalize_username(username)
    if not normalized:
        return False
    whitelist_normalized = {normalize_username(x) for x in settings.whitelist}
    return normalized in whitelist_normalized


def build_admin_home_text(data: dict) -> str:
    pending_now = sum(1 for item in data["queue"] if item["status"] == "pending")
    in_review_now = sum(1 for item in data["queue"] if item["status"] == "in_review")

    total_today = sum(1 for item in data["queue"] if is_same_day(item.get("created_at")))
    approved_today = sum(
        1 for item in data["queue"]
        if item["status"] == "approved" and is_same_day(item.get("reviewed_at"))
    )
    rejected_today = sum(
        1 for item in data["queue"]
        if item["status"] == "rejected" and is_same_day(item.get("reviewed_at"))
    )

    return (
        "Главная админа\n\n"
        f"На проверке сейчас: {pending_now + in_review_now}\n\n"
        f"За сегодня всего: {total_today}\n"
        f"За сегодня одобрено: {approved_today}\n"
        f"За сегодня отклонено: {rejected_today}"
    )


async def ensure_admin_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE, store: DataStore) -> None:
    del context
    data = store.load_data()

    username = normalize_username(update.effective_user.username)
    if username == normalize_username(settings.admin_username):
        current_chat_id = update.effective_chat.id
        if data.get("admin_chat_id") != current_chat_id:
            data["admin_chat_id"] = current_chat_id
            store.save_data(data)


async def show_or_create_admin_home(context: ContextTypes.DEFAULT_TYPE, chat_id: int, store: DataStore) -> None:
    data = store.load_data()
    text = build_admin_home_text(data)
    has_pending = any(item["status"] in {"pending", "in_review"} for item in data["queue"])
    markup = admin_home_keyboard(has_pending=has_pending)

    admin_home_message_id = data.get("admin_home_message_id")

    if admin_home_message_id:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=admin_home_message_id,
            )
        except BadRequest as e:
            logger.warning("Не удалось удалить старое admin home message: %s", e)
        except Exception as e:
            logger.warning("Ошибка при удалении старого admin home message: %s", e)

    sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
    data["admin_home_message_id"] = sent.message_id
    store.save_data(data)


async def notify_admin_new_photos(
    context: ContextTypes.DEFAULT_TYPE,
    from_username: str,
    count: int,
    store: DataStore,
) -> None:
    data = store.load_data()
    admin_chat_id = data.get("admin_chat_id")

    if not admin_chat_id:
        logger.warning("admin_chat_id не сохранён. Уведомление не отправлено.")
        return

    await context.bot.send_message(
        chat_id=admin_chat_id,
        text=(f"Пользователь {from_username} загрузил новые фото.\n" f"Количество: {count}"),
    )

    await show_or_create_admin_home(context, admin_chat_id, store)


async def send_next_photo_to_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, store: DataStore) -> None:
    data = store.load_data()
    item = store.get_next_reviewable_item(data)

    if not item:
        await show_or_create_admin_home(context, chat_id, store)
        return

    item["status"] = "in_review"
    item["review_started_at"] = now_iso()
    store.save_data(data)

    await context.bot.send_photo(
        chat_id=chat_id,
        photo=item["file_id"],
        caption=f"Фото от {item['from_username']}",
        reply_markup=moderation_keyboard(item["id"]),
    )

    await show_or_create_admin_home(context, chat_id, store)
