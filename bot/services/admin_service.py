from __future__ import annotations

from telegram.constants import ParseMode
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.config import settings
from bot.keyboards import admin_home_keyboard, moderation_keyboard
from bot.logging_config import logger
from bot.storage import DataStore
from bot.utils import is_same_day, normalize_username, now_iso
from bot.services.employee_service import format_employee_display_html


def is_admin(username: str | None) -> bool:
    return normalize_username(username) == normalize_username(settings.admin_username)


def is_allowed(store: DataStore, telegram_user_id: int, username: str | None) -> bool:
    return store.resolve_employee_identity(telegram_user_id, username) is not None


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
    await _upsert_admin_home_message(context, chat_id, store, recreate=False)


async def recreate_admin_home(context: ContextTypes.DEFAULT_TYPE, chat_id: int, store: DataStore) -> None:
    await _upsert_admin_home_message(context, chat_id, store, recreate=True)


async def _upsert_admin_home_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    store: DataStore,
    recreate: bool,
) -> None:
    data = store.load_data()
    text = build_admin_home_text(data)
    has_pending = any(item["status"] in {"pending", "in_review"} for item in data["queue"])
    markup = admin_home_keyboard(has_pending=has_pending)

    admin_home_message_id = data.get("admin_home_message_id")

    if admin_home_message_id and not recreate:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=admin_home_message_id,
                text=text,
                reply_markup=markup,
            )
            return
        except BadRequest as e:
            logger.warning("Не удалось обновить admin home message: %s", e)
        except Exception as e:
            logger.warning("Ошибка при обновлении admin home message: %s", e)

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
    from_employee_title: str,
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
        text=(f"Новые фото от {from_employee_title}.\n" f"Количество: {count}"),
    )

    await show_or_create_admin_home(context, admin_chat_id, store)


async def send_next_photo_to_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, store: DataStore) -> None:
    data = store.load_data()
    item = store.get_next_reviewable_item(data)

    if not item:
        await recreate_admin_home(context, chat_id, store)
        return

    item["status"] = "in_review"
    item["review_started_at"] = now_iso()
    store.save_data(data)

    employee = store.get_employee_by_id(item.get("employee_id")) if item.get("employee_id") else None
    caption_author = format_employee_display_html(employee) if employee else store.resolve_item_employee_label(item)
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=item["file_id"],
        caption=f"Фото от {caption_author}",
        parse_mode=ParseMode.HTML,
        reply_markup=moderation_keyboard(item["id"]),
    )
