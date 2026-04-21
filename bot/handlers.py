from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.services.admin_service import (
    ensure_admin_chat_id,
    is_admin,
    is_allowed,
    send_next_photo_to_admin,
    show_or_create_admin_home,
)
from bot.services.user_service import (
    clear_user_photos,
    submit_user_photos,
    update_or_create_user_control_message,
)
from bot.storage import DataStore
from bot.utils import normalize_username, now_iso


class BotHandlers:
    def __init__(self, store: DataStore) -> None:
        self.store = store

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await ensure_admin_chat_id(update, context, self.store)

        username = normalize_username(update.effective_user.username)

        if is_admin(username):
            await update.message.reply_text("Привет.\n\nТы админ этого бота.")
            await show_or_create_admin_home(context, update.effective_chat.id, self.store)
            return

        if not is_allowed(update.effective_user.username):
            await update.message.reply_text("У тебя нет доступа к этому боту.")
            return

        await update.message.reply_text(
            "Привет.\n"
            "Отправляй фото по одному или несколько подряд.\n"
            "После загрузки появится сообщение с кнопками отправки и очистки."
        )

    async def photo_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await ensure_admin_chat_id(update, context, self.store)

        user = update.effective_user

        if not is_allowed(user.username):
            await update.message.reply_text("У тебя нет доступа к загрузке фото.")
            return

        if not update.message.photo:
            return

        file_id = update.message.photo[-1].file_id
        data = self.store.load_data()
        draft = self.store.get_user_draft(data, user.id, user.username)
        draft["photos"].append(file_id)
        total = len(draft["photos"])
        self.store.save_data(data)

        await update_or_create_user_control_message(
            update=update,
            context=context,
            text=(
                f"Фото добавлено. Сейчас в твоей пачке: {total}\n"
                "Нажми «Отправить», когда закончишь, или «Очистить»."
            ),
            show_buttons=True,
            store=self.store,
        )

    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await ensure_admin_chat_id(update, context, self.store)

        username = normalize_username(update.effective_user.username)

        if is_admin(username):
            await show_or_create_admin_home(context, update.effective_chat.id, self.store)
            return

        if is_allowed(update.effective_user.username):
            await update.message.reply_text(
                "Просто отправь фото. После этого бот покажет кнопки отправки и очистки."
            )
            return

        await update.message.reply_text("У тебя нет доступа.")

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()

        user = query.from_user
        username = normalize_username(user.username)
        payload = query.data or ""

        await ensure_admin_chat_id(update, context, self.store)

        if payload == "user_submit":
            await submit_user_photos(query, context, self.store)
            return

        if payload == "user_clear":
            await clear_user_photos(query, context, self.store)
            return

        if not is_admin(username):
            await query.answer("У тебя нет прав.", show_alert=True)
            return

        data = self.store.load_data()

        if payload == "admin_home":
            await show_or_create_admin_home(context, query.message.chat_id, self.store)
            return

        if payload.startswith("admin_home_from_photo:"):
            raw_id = payload.split(":", 1)[1]
            try:
                item_id = int(raw_id)
            except ValueError:
                await query.answer("Некорректный ID фото.", show_alert=True)
                return

            self.store.release_in_review_item(data, item_id)
            self.store.save_data(data)

            try:
                await query.message.delete()
            except Exception:
                pass

            await show_or_create_admin_home(context, query.message.chat_id, self.store)
            return

        if payload == "admin_go_review":
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass

            await send_next_photo_to_admin(context, query.message.chat_id, self.store)
            return

        if payload == "admin_go_review_empty":
            await show_or_create_admin_home(context, query.message.chat_id, self.store)
            return

        if payload == "admin_add_employee":
            await query.answer("Функцию добавим позже.")
            return

        if payload.startswith("approve:") or payload.startswith("reject:"):
            action, raw_id = payload.split(":", 1)

            try:
                item_id = int(raw_id)
            except ValueError:
                await query.answer("Некорректный ID фото.", show_alert=True)
                return

            item = self.store.get_queue_item_by_id(data, item_id)
            status_emoji = "✅" if action == "approve" else "❌"

            if not item or item["status"] not in {"pending", "in_review"}:
                await self._finalize_existing_message(query, status_emoji)
                await show_or_create_admin_home(context, query.message.chat_id, self.store)
                return

            item["status"] = "approved" if action == "approve" else "rejected"
            item["reviewed_at"] = now_iso()
            self.store.save_data(data)

            await self._finalize_existing_message(query, status_emoji)
            await send_next_photo_to_admin(context, query.message.chat_id, self.store)

    async def _finalize_existing_message(self, query, status_emoji: str) -> None:
        try:
            old_caption = query.message.caption or "Фото"
            new_caption = old_caption if "Статус:" in old_caption else f"{old_caption}\nСтатус: {status_emoji}"
            await query.edit_message_caption(caption=new_caption, reply_markup=None)
        except Exception:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass

    async def admin_check_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await ensure_admin_chat_id(update, context, self.store)

        if not is_admin(update.effective_user.username):
            await update.message.reply_text("У тебя нет прав.")
            return

        await send_next_photo_to_admin(context, update.effective_chat.id, self.store)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await ensure_admin_chat_id(update, context, self.store)

        if not is_admin(update.effective_user.username):
            await update.message.reply_text("У тебя нет прав.")
            return

        data = self.store.load_data()
        pending = sum(1 for item in data["queue"] if item["status"] == "pending")
        in_review = sum(1 for item in data["queue"] if item["status"] == "in_review")
        approved = sum(1 for item in data["queue"] if item["status"] == "approved")
        rejected = sum(1 for item in data["queue"] if item["status"] == "rejected")

        await update.message.reply_text(
            "Статус очереди:\n"
            f"- Ожидают: {pending}\n"
            f"- В проверке: {in_review}\n"
            f"- Одобрены: {approved}\n"
            f"- Отклонены: {rejected}"
        )


def register_handlers(app: Application, store: DataStore) -> None:
    handlers = BotHandlers(store)

    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("check", handlers.admin_check_command))
    app.add_handler(CommandHandler("status", handlers.status_command))
    app.add_handler(CallbackQueryHandler(handlers.callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handlers.photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_handler))
