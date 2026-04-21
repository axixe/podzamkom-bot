from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def user_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Отправить", callback_data="user_submit"),
            InlineKeyboardButton("Очистить", callback_data="user_clear"),
        ]]
    )


def admin_home_keyboard(has_pending: bool) -> InlineKeyboardMarkup:
    rows = []

    if has_pending:
        rows.append([InlineKeyboardButton("Перейти к проверке", callback_data="admin_go_review")])

    rows.append([InlineKeyboardButton("Добавить сотрудника", callback_data="admin_add_employee")])
    return InlineKeyboardMarkup(rows)


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
