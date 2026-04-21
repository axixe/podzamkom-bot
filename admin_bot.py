import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = "8720185549:AAG-mXTX2LJTL-MMaEU0AcgXX8JVgoAkHqk"

ADMIN_USERNAME = "@axixe"

WHITELIST = {
    "@asyncr0",
}

DATA_FILE = Path("bot_data.json")


# =========================
# ЛОГИ
# =========================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# =========================
# НОРМАЛИЗАЦИЯ
# =========================

def normalize_username(username: str | None) -> str | None:
    if not username:
        return None
    username = username.strip()
    if not username.startswith("@"):
        username = f"@{username}"
    return username.lower()


def is_admin(username: str | None) -> bool:
    return normalize_username(username) == normalize_username(ADMIN_USERNAME)


def is_allowed(username: str | None) -> bool:
    normalized = normalize_username(username)
    if not normalized:
        return False
    whitelist_normalized = {normalize_username(x) for x in WHITELIST}
    return normalized in whitelist_normalized


# =========================
# ДАТА / ВРЕМЯ
# =========================

def now_iso() -> str:
    return datetime.now().isoformat()


def is_same_day(iso_string: str | None) -> bool:
    if not iso_string:
        return False
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.date() == datetime.now().date()
    except Exception:
        return False


# =========================
# ХРАНЕНИЕ ДАННЫХ
# =========================

def default_data() -> dict[str, Any]:
    return {
        "drafts": {
            # "<user_id>": {
            #   "username": "@user",
            #   "photos": ["file_id1", "file_id2"],
            #   "control_message_chat_id": 123456789,
            #   "control_message_id": 111
            # }
        },
        "queue": [
            # {
            #   "id": 1,
            #   "from_user_id": 123,
            #   "from_username": "@user",
            #   "file_id": "ABC",
            #   "status": "pending" | "in_review" | "approved" | "rejected",
            #   "created_at": "...",
            #   "review_started_at": "...",
            #   "reviewed_at": "..."
            # }
        ],
        "admin_chat_id": None,
        "admin_home_message_id": None,
        "last_item_id": 0,
    }


def load_data() -> dict[str, Any]:
    if not DATA_FILE.exists():
        data = default_data()
        save_data(data)
        return data

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.exception("Не удалось загрузить bot_data.json: %s", e)
        data = default_data()
        save_data(data)
        return data

    if "drafts" not in data:
        data["drafts"] = {}
    if "queue" not in data:
        data["queue"] = []
    if "admin_chat_id" not in data:
        data["admin_chat_id"] = None
    if "admin_home_message_id" not in data:
        data["admin_home_message_id"] = None
    if "last_item_id" not in data:
        data["last_item_id"] = 0

    changed = False

    for item in data["queue"]:
        if "created_at" not in item:
            item["created_at"] = now_iso()
            changed = True
        if "review_started_at" not in item:
            item["review_started_at"] = None
            changed = True
        if "reviewed_at" not in item:
            item["reviewed_at"] = None
            changed = True

    if changed:
        save_data(data)

    return data


def save_data(data: dict[str, Any]) -> None:
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_draft(data: dict[str, Any], user_id: int, username: str | None) -> dict[str, Any]:
    user_key = str(user_id)

    if user_key not in data["drafts"]:
        data["drafts"][user_key] = {
            "username": normalize_username(username),
            "photos": [],
            "control_message_chat_id": None,
            "control_message_id": None,
        }

    draft = data["drafts"][user_key]

    if "photos" not in draft:
        draft["photos"] = []
    if "control_message_chat_id" not in draft:
        draft["control_message_chat_id"] = None
    if "control_message_id" not in draft:
        draft["control_message_id"] = None

    draft["username"] = normalize_username(username)
    return draft


def clear_user_control_message_refs(data: dict[str, Any], user_id: int) -> None:
    user_key = str(user_id)
    if user_key not in data["drafts"]:
        return

    data["drafts"][user_key]["control_message_chat_id"] = None
    data["drafts"][user_key]["control_message_id"] = None


def get_next_reviewable_item(data: dict[str, Any]) -> dict[str, Any] | None:
    for item in data["queue"]:
        if item["status"] == "pending":
            return item
    return None


def get_queue_item_by_id(data: dict[str, Any], item_id: int) -> dict[str, Any] | None:
    for item in data["queue"]:
        if item["id"] == item_id:
            return item
    return None


def release_in_review_item(data: dict[str, Any], item_id: int) -> dict[str, Any] | None:
    item = get_queue_item_by_id(data, item_id)
    if not item:
        return None

    if item["status"] == "in_review":
        item["status"] = "pending"
        item["review_started_at"] = None

    return item


# =========================
# КНОПКИ
# =========================

def user_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Отправить", callback_data="user_submit"),
            InlineKeyboardButton("Очистить", callback_data="user_clear"),
        ]]
    )


def admin_home_keyboard(has_pending: bool) -> InlineKeyboardMarkup:
    review_callback = "admin_go_review" if has_pending else "admin_go_review_empty"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Перейти к проверке", callback_data=review_callback)],
            [InlineKeyboardButton("Добавить сотрудника", callback_data="admin_add_employee")],
        ]
    )


def moderation_keyboard(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅", callback_data=f"approve:{item_id}"),
                InlineKeyboardButton("❌", callback_data=f"reject:{item_id}"),
            ],
            [
                InlineKeyboardButton(
                    "Вернуться на главную",
                    callback_data=f"admin_home_from_photo:{item_id}",
                ),
            ],
        ]
    )


# =========================
# АДМИНСКАЯ СТАТИСТИКА
# =========================

def build_admin_home_text(data: dict[str, Any]) -> str:
    pending_now = sum(1 for item in data["queue"] if item["status"] == "pending")
    in_review_now = sum(1 for item in data["queue"] if item["status"] == "in_review")

    total_today = sum(
        1 for item in data["queue"]
        if is_same_day(item.get("created_at"))
    )
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


# =========================
# ВСПОМОГАТЕЛЬНОЕ
# =========================

async def ensure_admin_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()

    username = normalize_username(update.effective_user.username)
    if username == normalize_username(ADMIN_USERNAME):
        current_chat_id = update.effective_chat.id
        if data.get("admin_chat_id") != current_chat_id:
            data["admin_chat_id"] = current_chat_id
            save_data(data)


async def show_or_create_admin_home(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    data = load_data()
    text = build_admin_home_text(data)
    has_pending = any(item["status"] in {"pending", "in_review"} for item in data["queue"])
    markup = admin_home_keyboard(has_pending=has_pending)

    admin_home_message_id = data.get("admin_home_message_id")

    if admin_home_message_id:
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

    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=markup,
    )
    data["admin_home_message_id"] = sent.message_id
    save_data(data)


async def notify_admin_new_photos(
    context: ContextTypes.DEFAULT_TYPE,
    from_username: str,
    count: int,
) -> None:
    data = load_data()
    admin_chat_id = data.get("admin_chat_id")

    if not admin_chat_id:
        logger.warning("admin_chat_id не сохранён. Уведомление не отправлено.")
        return

    await context.bot.send_message(
        chat_id=admin_chat_id,
        text=(
            f"Пользователь {from_username} загрузил новые фото.\n"
            f"Количество: {count}"
        ),
    )

    await show_or_create_admin_home(context, admin_chat_id)


async def send_next_photo_to_admin(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    data = load_data()
    item = get_next_reviewable_item(data)

    if not item:
        await show_or_create_admin_home(context, chat_id)
        return

    item["status"] = "in_review"
    item["review_started_at"] = now_iso()
    save_data(data)

    caption = f"Фото от {item['from_username']}"

    await context.bot.send_photo(
        chat_id=chat_id,
        photo=item["file_id"],
        caption=caption,
        reply_markup=moderation_keyboard(item["id"]),
    )

    await show_or_create_admin_home(context, chat_id)


async def update_or_create_user_control_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    show_buttons: bool,
) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id

    data = load_data()
    draft = get_user_draft(data, user.id, user.username)

    old_chat_id = draft.get("control_message_chat_id")
    old_message_id = draft.get("control_message_id")
    reply_markup = user_action_keyboard() if show_buttons else None

    if old_chat_id and old_message_id:
        try:
            await context.bot.delete_message(
                chat_id=old_chat_id,
                message_id=old_message_id,
            )
        except BadRequest as e:
            logger.warning("Не удалось удалить старое control message: %s", e)
        except Exception as e:
            logger.warning("Ошибка при удалении старого control message: %s", e)

    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
    )

    draft["control_message_chat_id"] = sent.chat_id
    draft["control_message_id"] = sent.message_id
    save_data(data)


# =========================
# БИЗНЕС-ЛОГИКА ПОЛЬЗОВАТЕЛЯ
# =========================

async def submit_user_photos(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = query.from_user

    if not is_allowed(user.username):
        await query.answer("У тебя нет доступа.", show_alert=True)
        return

    data = load_data()
    draft = get_user_draft(data, user.id, user.username)

    if not draft["photos"]:
        try:
            await query.edit_message_text("У тебя нет фото для отправки.")
        except BadRequest:
            pass

        clear_user_control_message_refs(data, user.id)
        save_data(data)
        return

    added_count = 0
    for file_id in draft["photos"]:
        data["last_item_id"] += 1
        data["queue"].append({
            "id": data["last_item_id"],
            "from_user_id": user.id,
            "from_username": normalize_username(user.username),
            "file_id": file_id,
            "status": "pending",
            "created_at": now_iso(),
            "review_started_at": None,
            "reviewed_at": None,
        })
        added_count += 1

    draft["photos"] = []
    clear_user_control_message_refs(data, user.id)
    save_data(data)

    try:
        await query.edit_message_text(
            f"Отправка подтверждена. Фото отправлены в очередь: {added_count}"
        )
    except BadRequest:
        pass

    await notify_admin_new_photos(
        context=context,
        from_username=normalize_username(user.username) or "без username",
        count=added_count,
    )


async def clear_user_photos(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = query.from_user

    if not is_allowed(user.username):
        await query.answer("У тебя нет доступа.", show_alert=True)
        return

    data = load_data()
    draft = get_user_draft(data, user.id, user.username)

    draft["photos"] = []
    clear_user_control_message_refs(data, user.id)
    save_data(data)

    try:
        await query.edit_message_text("Твоя текущая пачка фото очищена.")
    except BadRequest:
        pass


# =========================
# ХЕНДЛЕРЫ
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_admin_chat_id(update, context)

    username = normalize_username(update.effective_user.username)

    if is_admin(username):
        await update.message.reply_text(
            "Привет.\n\nТы админ этого бота."
        )
        await show_or_create_admin_home(context, update.effective_chat.id)
        return

    if not is_allowed(update.effective_user.username):
        await update.message.reply_text("У тебя нет доступа к этому боту.")
        return

    await update.message.reply_text(
        "Привет.\n"
        "Отправляй фото по одному или несколько подряд.\n"
        "После загрузки появится сообщение с кнопками отправки и очистки."
    )


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_admin_chat_id(update, context)

    user = update.effective_user

    if not is_allowed(user.username):
        await update.message.reply_text("У тебя нет доступа к загрузке фото.")
        return

    if not update.message.photo:
        return

    largest_photo = update.message.photo[-1]
    file_id = largest_photo.file_id

    data = load_data()
    draft = get_user_draft(data, user.id, user.username)

    draft["photos"].append(file_id)
    total = len(draft["photos"])
    save_data(data)

    await update_or_create_user_control_message(
        update=update,
        context=context,
        text=(
            f"Фото добавлено. Сейчас в твоей пачке: {total}\n"
            "Нажми «Отправить», когда закончишь, или «Очистить»."
        ),
        show_buttons=True,
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_admin_chat_id(update, context)

    username = normalize_username(update.effective_user.username)

    if is_admin(username):
        await show_or_create_admin_home(context, update.effective_chat.id)
        return

    if is_allowed(update.effective_user.username):
        await update.message.reply_text(
            "Просто отправь фото. После этого бот покажет кнопки отправки и очистки."
        )
        return

    await update.message.reply_text("У тебя нет доступа.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user = query.from_user
    username = normalize_username(user.username)
    payload = query.data or ""

    await ensure_admin_chat_id(update, context)

    # Пользовательские действия
    if payload == "user_submit":
        await submit_user_photos(query, context)
        return

    if payload == "user_clear":
        await clear_user_photos(query, context)
        return

    # Дальше только админ
    if not is_admin(username):
        await query.answer("У тебя нет прав.", show_alert=True)
        return

    data = load_data()

    if payload == "admin_home":
        await show_or_create_admin_home(context, query.message.chat_id)
        return

    if payload.startswith("admin_home_from_photo:"):
        raw_id = payload.split(":", 1)[1]

        try:
            item_id = int(raw_id)
        except ValueError:
            await query.answer("Некорректный ID фото.", show_alert=True)
            return

        release_in_review_item(data, item_id)
        save_data(data)

        try:
            await query.message.delete()
        except Exception:
            pass

        await show_or_create_admin_home(context, query.message.chat_id)
        return

    if payload == "admin_go_review":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        await send_next_photo_to_admin(context, query.message.chat_id)
        return

    if payload == "admin_go_review_empty":
        await show_or_create_admin_home(context, query.message.chat_id)
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

        item = get_queue_item_by_id(data, item_id)
        status_emoji = "✅" if action == "approve" else "❌"

        if not item:
            try:
                old_caption = query.message.caption or "Фото"
                new_caption = (
                    old_caption
                    if "Статус:" in old_caption
                    else f"{old_caption}\nСтатус: {status_emoji}"
                )

                await query.edit_message_caption(
                    caption=new_caption,
                    reply_markup=None,
                )
            except Exception:
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass

            await show_or_create_admin_home(context, query.message.chat_id)
            return

        if item["status"] not in {"pending", "in_review"}:
            try:
                old_caption = query.message.caption or "Фото"
                new_caption = (
                    old_caption
                    if "Статус:" in old_caption
                    else f"{old_caption}\nСтатус: {status_emoji}"
                )

                await query.edit_message_caption(
                    caption=new_caption,
                    reply_markup=None,
                )
            except Exception:
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass

            await show_or_create_admin_home(context, query.message.chat_id)
            return

        item["status"] = "approved" if action == "approve" else "rejected"
        item["reviewed_at"] = now_iso()
        save_data(data)

        try:
            old_caption = query.message.caption or "Фото"
            new_caption = (
                old_caption
                if "Статус:" in old_caption
                else f"{old_caption}\nСтатус: {status_emoji}"
            )

            await query.edit_message_caption(
                caption=new_caption,
                reply_markup=None,
            )
        except Exception:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass

        await send_next_photo_to_admin(context, query.message.chat_id)
        return


async def admin_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_admin_chat_id(update, context)

    if not is_admin(update.effective_user.username):
        await update.message.reply_text("У тебя нет прав.")
        return

    await send_next_photo_to_admin(context, update.effective_chat.id)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_admin_chat_id(update, context)

    if not is_admin(update.effective_user.username):
        await update.message.reply_text("У тебя нет прав.")
        return

    data = load_data()
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


# =========================
# ЗАПУСК
# =========================

def main() -> None:
    if BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise ValueError("Сначала вставь токен бота в BOT_TOKEN.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", admin_check_command))
    app.add_handler(CommandHandler("status", status_command))

    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()