from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.employee_service import period_label


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

    rows.append([InlineKeyboardButton("Менеджер сотрудников", callback_data="admin_employee_manager")])
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


def employee_manager_keyboard(period: str) -> InlineKeyboardMarkup:
    rows = [
        _period_row("manager_period", period),
        [InlineKeyboardButton("Список сотрудников", callback_data="manager_list:active:0")],
        [InlineKeyboardButton("Деактивированные", callback_data="manager_list:inactive:0")],
        [InlineKeyboardButton("Добавить сотрудника", callback_data="manager_add_start")],
        [InlineKeyboardButton("Назад", callback_data="admin_home")],
    ]
    return InlineKeyboardMarkup(rows)


def employee_list_keyboard(
    items: list[tuple[int, str]],
    mode: str,
    page: int,
    total_pages: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(
            title,
            callback_data=f"manager_employee:{employee_id}:{mode}:{page}:day",
        ),
    ] for employee_id, title in items]

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"manager_list:{mode}:{page - 1}"))
    nav_row.append(InlineKeyboardButton(f"{page + 1}/{max(total_pages, 1)}", callback_data="manager_noop"))
    if has_next:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"manager_list:{mode}:{page + 1}"))
    rows.append(nav_row)

    rows.append([InlineKeyboardButton("Назад", callback_data="admin_employee_manager")])
    rows.append([InlineKeyboardButton("На главную", callback_data="admin_home")])
    return InlineKeyboardMarkup(rows)


def employee_card_keyboard(employee_id: int, period: str, mode: str = "active", page: int = 0) -> InlineKeyboardMarkup:
    rows = [
        _period_row(f"manager_employee_period:{employee_id}:{mode}:{page}", period),
        [InlineKeyboardButton("Редактировать имя", callback_data=f"manager_edit_name:{employee_id}:{mode}:{page}:{period}")],
        [InlineKeyboardButton("Удалить сотрудника", callback_data=f"manager_delete:{employee_id}:{mode}:{page}")],
        [InlineKeyboardButton("Назад", callback_data=f"manager_list:{mode}:{page}")],
        [InlineKeyboardButton("На главную", callback_data="admin_home")],
    ]
    return InlineKeyboardMarkup(rows)


def add_employee_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Сохранить", callback_data="manager_add_save")],
            [InlineKeyboardButton("Назад", callback_data="manager_add_back")],
            [InlineKeyboardButton("Отмена", callback_data="manager_add_cancel")],
        ]
    )


def _period_row(prefix: str, active: str) -> list[InlineKeyboardButton]:
    buttons = []
    for period in ["day", "week", "month"]:
        title = period_label(period)
        if period == active:
            title = f"· {title} ·"
        buttons.append(InlineKeyboardButton(title, callback_data=f"{prefix}:{period}"))
    return buttons
