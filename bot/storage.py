from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bot.logging_config import logger
from bot.utils import normalize_username, now_iso


class DataStore:
    def __init__(self, data_file: Path) -> None:
        self.data_file = data_file

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

        if changed:
            self.save_data(data)

        return data

    def save_data(self, data: dict[str, Any]) -> None:
        with self.data_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

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
