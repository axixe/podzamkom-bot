from __future__ import annotations

import asyncio
import json
import uuid
from urllib import parse, request

from telegram.ext import ContextTypes

from bot.config import settings

VK_API_BASE = "https://api.vk.com/method"


class VkUploadError(RuntimeError):
    pass


def _require_vk_settings() -> tuple[str, int, int, str]:
    token = settings.vk_token
    group_id = settings.vk_group_id
    album_id = settings.vk_album_id
    api_version = settings.vk_api_version

    if not token:
        raise VkUploadError("Не задан VK_TOKEN.")
    if not group_id:
        raise VkUploadError("Не задан VK_GROUP_ID.")
    if not album_id:
        raise VkUploadError("Не задан VK_ALBUM_ID.")

    return token, group_id, album_id, api_version


def _vk_api_call(method: str, params: dict[str, str | int]) -> dict:
    token, _, _, api_version = _require_vk_settings()
    body = parse.urlencode(
        {
            **params,
            "access_token": token,
            "v": api_version,
        }
    ).encode("utf-8")

    req = request.Request(
        f"{VK_API_BASE}/{method}",
        data=body,
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if "error" in payload:
        message = payload["error"].get("error_msg", "Неизвестная ошибка VK API")
        raise VkUploadError(f"{method}: {message}")

    return payload["response"]


def _build_multipart_form(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    parts: list[bytes] = []

    for name, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )

    for field_name, (filename, file_data, content_type) in files.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                file_data,
                b"\r\n",
            ]
        )

    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def _upload_file(upload_url: str, file_data: bytes) -> dict:
    body, boundary = _build_multipart_form(
        fields={},
        files={
            "file1": ("photo.jpg", file_data, "image/jpeg"),
        },
    )

    req = request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


async def upload_approved_photo_to_vk(context: ContextTypes.DEFAULT_TYPE, file_id: str) -> str:
    _, group_id, album_id, _ = _require_vk_settings()

    tg_file = await context.bot.get_file(file_id)
    photo_bytes = bytes(await tg_file.download_as_bytearray())

    upload_server = await asyncio.to_thread(
        _vk_api_call,
        "photos.getUploadServer",
        {"group_id": group_id, "album_id": album_id},
    )
    upload_result = await asyncio.to_thread(_upload_file, upload_server["upload_url"], photo_bytes)

    if "error" in upload_result:
        raise VkUploadError(f"VK upload server: {upload_result['error']}")

    saved = await asyncio.to_thread(
        _vk_api_call,
        "photos.save",
        {
            "group_id": group_id,
            "album_id": album_id,
            "server": upload_result["server"],
            "photos_list": upload_result["photos_list"],
            "hash": upload_result["hash"],
        },
    )

    if not saved:
        raise VkUploadError("VK не вернул данные о сохраненном фото.")

    first = saved[0]
    return first.get("text") or first.get("sizes", [{}])[-1].get("url", "")
