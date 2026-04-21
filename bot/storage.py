from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from bot.logging_config import logger
from bot.utils import normalize_username, now_iso


class DataStore:
    def __init__(self, data_file: Path, sqlite_file: Path) -> None:
        self.data_file = data_file
        self.sqlite_file = sqlite_file
        self._init_sqlite()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_file)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NULL,
                    username TEXT NULL UNIQUE,
                    display_name TEXT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def default_data() -> dict[str, Any]:
        return {
            "drafts": {},
            "queue": [],
            "admin_chat_id": None,
            "admin_home_message_id": None,
            "last_item_id": 0,
        }

    def load_data(self) -> dict[str, Any]:
        if not self.data_file.exists():
            data = self.default_data()
            self.save_data(data)
            return data

        try:
            with self.data_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.exception("Не удалось загрузить bot_data.json: %s", e)
            data = self.default_data()
            self.save_data(data)
            return data

        data.setdefault("drafts", {})
        data.setdefault("queue", [])
        data.setdefault("admin_chat_id", None)
        data.setdefault("admin_home_message_id", None)
        data.setdefault("last_item_id", 0)

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
            if "employee_id" not in item:
                item["employee_id"] = None
                changed = True

        if changed:
            self.save_data(data)

        return data

    def save_data(self, data: dict[str, Any]) -> None:
        with self.data_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _row_to_employee(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "id": row["id"],
            "telegram_user_id": row["telegram_user_id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_employee(self, username: str, display_name: str | None) -> dict[str, Any]:
        normalized_username = normalize_username(username)
        if not normalized_username:
            raise ValueError("Username обязателен")

        timestamp = now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO employees (telegram_user_id, username, display_name, is_active, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (None, normalized_username, display_name, timestamp, timestamp),
            )
            employee_id = cursor.lastrowid
            row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        employee = self._row_to_employee(row)
        if not employee:
            raise RuntimeError("Не удалось создать сотрудника")
        return employee

    def count_active_employees(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM employees WHERE is_active = 1").fetchone()
        return int(row["cnt"] if row else 0)

    def list_active_employees(self, offset: int = 0, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM employees
                WHERE is_active = 1
                ORDER BY COALESCE(display_name, username, '') COLLATE NOCASE, id ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._row_to_employee(row) for row in rows if row]

    def get_employee_by_id(self, employee_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        return self._row_to_employee(row)

    def get_active_employee_by_tg_id(self, telegram_user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM employees WHERE telegram_user_id = ? AND is_active = 1",
                (telegram_user_id,),
            ).fetchone()
        return self._row_to_employee(row)

    def get_active_employee_by_username(self, username: str | None) -> dict[str, Any] | None:
        normalized_username = normalize_username(username)
        if not normalized_username:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM employees WHERE username = ? AND is_active = 1",
                (normalized_username,),
            ).fetchone()
        return self._row_to_employee(row)

    def update_employee_name(self, employee_id: int, display_name: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE employees SET display_name = ?, updated_at = ? WHERE id = ?",
                (display_name, now_iso(), employee_id),
            )

    def deactivate_employee(self, employee_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE employees SET is_active = 0, updated_at = ? WHERE id = ?",
                (now_iso(), employee_id),
            )

    def resolve_employee_identity(self, telegram_user_id: int, username: str | None) -> dict[str, Any] | None:
        normalized_username = normalize_username(username)
        by_tg = self.get_active_employee_by_tg_id(telegram_user_id)

        if by_tg:
            if normalized_username and normalized_username != by_tg.get("username"):
                try:
                    with self._connect() as conn:
                        conn.execute(
                            "UPDATE employees SET username = ?, updated_at = ? WHERE id = ?",
                            (normalized_username, now_iso(), by_tg["id"]),
                        )
                    by_tg["username"] = normalized_username
                except sqlite3.IntegrityError:
                    logger.warning("Невозможно обновить username: %s", normalized_username)
            return self.get_employee_by_id(by_tg["id"])

        by_username = self.get_active_employee_by_username(normalized_username)
        if by_username and by_username.get("telegram_user_id") is None:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE employees SET telegram_user_id = ?, updated_at = ? WHERE id = ?",
                    (telegram_user_id, now_iso(), by_username["id"]),
                )
            return self.get_employee_by_id(by_username["id"])

        return by_username

    @staticmethod
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
        draft.setdefault("photos", [])
        draft.setdefault("control_message_chat_id", None)
        draft.setdefault("control_message_id", None)
        draft["username"] = normalize_username(username)
        return draft

    @staticmethod
    def clear_user_control_message_refs(data: dict[str, Any], user_id: int) -> None:
        user_key = str(user_id)
        if user_key not in data["drafts"]:
            return

        data["drafts"][user_key]["control_message_chat_id"] = None
        data["drafts"][user_key]["control_message_id"] = None

    @staticmethod
    def get_next_reviewable_item(data: dict[str, Any]) -> dict[str, Any] | None:
        for item in data["queue"]:
            if item["status"] == "pending":
                return item
        return None

    @staticmethod
    def get_queue_item_by_id(data: dict[str, Any], item_id: int) -> dict[str, Any] | None:
        for item in data["queue"]:
            if item["id"] == item_id:
                return item
        return None

    @classmethod
    def release_in_review_item(cls, data: dict[str, Any], item_id: int) -> dict[str, Any] | None:
        item = cls.get_queue_item_by_id(data, item_id)
        if not item:
            return None

        if item["status"] == "in_review":
            item["status"] = "pending"
            item["review_started_at"] = None

        return item

    def resolve_item_employee_label(self, item: dict[str, Any]) -> str:
        employee_id = item.get("employee_id")
        if employee_id:
            employee = self.get_employee_by_id(int(employee_id))
            if employee and employee.get("is_active"):
                from bot.services.employee_service import format_employee_display

                return format_employee_display(employee)

        username = normalize_username(item.get("from_username"))
        return username or "Неизвестный сотрудник"
