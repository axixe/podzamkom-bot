from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.keyboards import (
    add_employee_confirm_keyboard,
    employee_card_keyboard,
    employee_list_keyboard,
    employee_manager_keyboard,
)
from bot.services.admin_service import (
    ensure_admin_chat_id,
    is_admin,
    is_allowed,
    recreate_admin_home,
    send_next_photo_to_admin,
    show_or_create_admin_home,
)
from bot.services.employee_service import (
    build_employee_card_text,
    build_employee_manager_text,
    format_employee_display,
    normalize_period,
)
from bot.services.user_service import (
    clear_user_photos,
    submit_user_photos,
    update_or_create_user_control_message,
)
from bot.storage import DataStore
from bot.utils import normalize_username, now_iso


EMPLOYEE_PAGE_SIZE = 8
UPLOAD_DENIED_NOTIFY_COOLDOWN = timedelta(seconds=30)


class BotHandlers:
    def __init__(self, store: DataStore) -> None:
        self.store = store

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await ensure_admin_chat_id(update, context, self.store)

        username = normalize_username(update.effective_user.username)

        if is_admin(username):
            await update.message.reply_text("Привет.\n\nТы админ этого бота.")
            await recreate_admin_home(context, update.effective_chat.id, self.store)
            return

        if not is_allowed(self.store, update.effective_user.id, update.effective_user.username):
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

        if not is_allowed(self.store, user.id, user.username):
            now = datetime.now()
            last_notified = context.user_data.get("upload_access_denied_at")
            if not isinstance(last_notified, datetime) or now - last_notified >= UPLOAD_DENIED_NOTIFY_COOLDOWN:
                await update.message.reply_text("У тебя нет доступа к загрузке фото.")
                context.user_data["upload_access_denied_at"] = now
            return

        if not update.message.photo:
            return

        file_id = update.message.photo[-1].file_id
        context.user_data.pop("upload_access_denied_at", None)
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
            if await self._handle_admin_text_flow(update, context):
                return
            await recreate_admin_home(context, update.effective_chat.id, self.store)
            return

        if is_allowed(self.store, update.effective_user.id, update.effective_user.username):
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

            await recreate_admin_home(context, query.message.chat_id, self.store)
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

        if payload == "admin_employee_manager":
            await self._render_employee_manager(query, period="day")
            return

        if payload.startswith("manager_period:"):
            period = normalize_period(payload.split(":", 1)[1])
            await self._render_employee_manager(query, period=period)
            return

        if payload.startswith("manager_list:"):
            page = int(payload.split(":", 1)[1])
            await self._render_employee_list(query, page)
            return

        if payload.startswith("manager_employee:"):
            _, employee_id_raw, period_raw = payload.split(":", 2)
            await self._render_employee_card(query, int(employee_id_raw), normalize_period(period_raw))
            return

        if payload.startswith("manager_employee_period:"):
            _, employee_id_raw, period_raw = payload.split(":", 2)
            await self._render_employee_card(query, int(employee_id_raw), normalize_period(period_raw))
            return

        if payload.startswith("manager_delete:"):
            employee_id = int(payload.split(":", 1)[1])
            employee = self.store.get_employee_by_id(employee_id)
            self.store.deactivate_employee(employee_id)
            if employee and employee.get("telegram_user_id"):
                try:
                    await context.bot.send_message(
                        chat_id=employee["telegram_user_id"],
                        text="Ваш доступ к боту был деактивирован администратором.",
                    )
                except Exception:
                    pass
            await self._render_employee_list(query, page=0, include_inactive=True)
            return

        if payload.startswith("manager_edit_name:"):
            _, employee_id_raw, period_raw = payload.split(":", 2)
            employee_id = int(employee_id_raw)
            period = normalize_period(period_raw)
            context.user_data["employee_flow"] = {"mode": "edit_name", "employee_id": employee_id, "period": period}
            await query.edit_message_text("Введи новое имя (display_name). Можно отправить '-' чтобы очистить.")
            return

        if payload == "manager_add_start":
            context.user_data["employee_flow"] = {"mode": "add", "step": "username"}
            await query.edit_message_text("Шаг 1/3. Введи username сотрудника (например, @axixe).")
            return

        if payload == "manager_add_back":
            flow = context.user_data.get("employee_flow", {})
            if flow.get("mode") == "add":
                flow["step"] = "display_name"
                context.user_data["employee_flow"] = flow
                await query.edit_message_text("Шаг 2/3. Введи display_name (или '-' чтобы оставить пустым).")
            return

        if payload == "manager_add_cancel":
            context.user_data.pop("employee_flow", None)
            await self._render_employee_manager(query, period="day")
            return

        if payload == "manager_add_save":
            flow = context.user_data.get("employee_flow", {})
            if flow.get("mode") != "add" or flow.get("step") != "confirm":
                await query.answer("Добавление неактивно.", show_alert=True)
                return

            try:
                employee = self.store.create_employee(
                    username=flow["username"],
                    display_name=flow.get("display_name"),
                )
            except sqlite3.IntegrityError:
                await query.answer("Такой username уже существует.", show_alert=True)
                return

            context.user_data.pop("employee_flow", None)
            await query.edit_message_text(f"Сотрудник сохранен: {format_employee_display(employee)}")
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

    async def _handle_admin_text_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        flow = context.user_data.get("employee_flow")
        if not flow:
            return False

        text = (update.message.text or "").strip()

        if flow.get("mode") == "edit_name":
            employee_id = int(flow["employee_id"])
            period = normalize_period(flow.get("period"))
            new_name = None if text == "-" else text
            self.store.update_employee_name(employee_id, new_name)
            context.user_data.pop("employee_flow", None)
            await update.message.reply_text("Имя сотрудника было изменено.")
            await update.message.reply_text(
                text=build_employee_card_text(self.store, employee_id, period),
                reply_markup=employee_card_keyboard(employee_id, period),
            )
            return True

        if flow.get("mode") != "add":
            return False

        if flow.get("step") == "username":
            normalized_username = normalize_username(text)
            if not normalized_username or not text.startswith("@"):
                await update.message.reply_text("Username должен начинаться с @. Попробуй снова.")
                return True

            if self.store.get_active_employee_by_username(normalized_username):
                await update.message.reply_text("Такой username уже есть среди активных сотрудников.")
                return True

            flow["username"] = normalized_username
            flow["step"] = "display_name"
            context.user_data["employee_flow"] = flow
            await update.message.reply_text("Шаг 2/3. Введи display_name (или '-' чтобы оставить пустым).")
            return True

        if flow.get("step") == "display_name":
            flow["display_name"] = None if text == "-" else text
            flow["step"] = "confirm"
            context.user_data["employee_flow"] = flow
            pretty_name = flow["display_name"] or "не указано"
            await update.message.reply_text(
                f"Подтверждение:\nUsername: {flow['username']}\nИмя: {pretty_name}",
                reply_markup=add_employee_confirm_keyboard(),
            )
            return True

        return False

    async def _render_employee_manager(self, query, period: str) -> None:
        text = build_employee_manager_text(self.store, period)
        await query.edit_message_text(text=text, reply_markup=employee_manager_keyboard(period))

    async def _render_employee_list(self, query, page: int, include_inactive: bool = False) -> None:
        total = self.store.count_employees(include_inactive=include_inactive)
        offset = max(0, page) * EMPLOYEE_PAGE_SIZE
        employees = self.store.list_employees(
            offset=offset,
            limit=EMPLOYEE_PAGE_SIZE + 1,
            include_inactive=include_inactive,
        )
        has_next = len(employees) > EMPLOYEE_PAGE_SIZE
        current = employees[:EMPLOYEE_PAGE_SIZE]

        items = []
        for employee in current:
            title = format_employee_display(employee)
            if not employee.get("is_active"):
                title = f"🚫 {title}"
            items.append((employee["id"], title))
        has_prev = page > 0

        title = "Выберите сотрудника" if not include_inactive else "Список всех сотрудников"
        await query.edit_message_text(
            text=f"{title}\n\nВсего: {total}",
            reply_markup=employee_list_keyboard(items, page, has_prev=has_prev, has_next=has_next),
        )

    async def _render_employee_card(self, query, employee_id: int, period: str) -> None:
        text = build_employee_card_text(self.store, employee_id, period)
        await query.edit_message_text(text=text, reply_markup=employee_card_keyboard(employee_id, period))

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
