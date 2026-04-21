from __future__ import annotations

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.keyboards import user_action_keyboard
from bot.storage import DataStore
from bot.utils import normalize_username, now_iso
from bot.services.admin_service import is_allowed, notify_admin_new_photos


async def update_or_create_user_control_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    show_buttons: bool,
    store: DataStore,
) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id

    data = store.load_data()
    draft = store.get_user_draft(data, user.id, user.username)

    old_chat_id = draft.get("control_message_chat_id")
    old_message_id = draft.get("control_message_id")
    reply_markup = user_action_keyboard() if show_buttons else None

    if old_chat_id and old_message_id:
        try:
            await context.bot.delete_message(chat_id=old_chat_id, message_id=old_message_id)
        except BadRequest:
            pass

    sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

    draft["control_message_chat_id"] = sent.chat_id
    draft["control_message_id"] = sent.message_id
    store.save_data(data)


async def submit_user_photos(query, context: ContextTypes.DEFAULT_TYPE, store: DataStore) -> None:
    user = query.from_user

    if not is_allowed(user.username):
        await query.answer("У тебя нет доступа.", show_alert=True)
        return

    data = store.load_data()
    draft = store.get_user_draft(data, user.id, user.username)

    if not draft["photos"]:
        try:
            await query.edit_message_text("У тебя нет фото для отправки.")
        except BadRequest:
            pass

        store.clear_user_control_message_refs(data, user.id)
        store.save_data(data)
        return

    added_count = 0
    for file_id in draft["photos"]:
        data["last_item_id"] += 1
        data["queue"].append(
            {
                "id": data["last_item_id"],
                "from_user_id": user.id,
                "from_username": normalize_username(user.username),
                "file_id": file_id,
                "status": "pending",
                "created_at": now_iso(),
                "review_started_at": None,
                "reviewed_at": None,
            }
        )
        added_count += 1

    draft["photos"] = []
    store.clear_user_control_message_refs(data, user.id)
    store.save_data(data)

    try:
        await query.edit_message_text(f"Отправка подтверждена. Фото отправлены в очередь: {added_count}")
    except BadRequest:
        pass

    await notify_admin_new_photos(
        context=context,
        from_username=normalize_username(user.username) or "без username",
        count=added_count,
        store=store,
    )


async def clear_user_photos(query, context: ContextTypes.DEFAULT_TYPE, store: DataStore) -> None:
    del context
    user = query.from_user

    if not is_allowed(user.username):
        await query.answer("У тебя нет доступа.", show_alert=True)
        return

    data = store.load_data()
    draft = store.get_user_draft(data, user.id, user.username)

    draft["photos"] = []
    store.clear_user_control_message_refs(data, user.id)
    store.save_data(data)

    try:
        await query.edit_message_text("Твоя текущая пачка фото очищена.")
    except BadRequest:
        pass
