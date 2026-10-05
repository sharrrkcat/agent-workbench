"""Bounded QQ image acquisition, original attachments and static model inputs."""
import asyncio
from dataclasses import replace
from functools import lru_cache
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from websockets.exceptions import WebSocketException

from ai_workbench.core.attachments import delete_attachment_if_unreferenced, save_attachment_from_upload
from ai_workbench.core.harness.network import fetch_bytes
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.schema.qq import QQImageAttachment

log = logging.getLogger(__name__)
MEDIA_WAIT_SECONDS = 10
MEDIA_CONCURRENCY = 4
IMAGE_TYPES = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"),
               "WEBP": ("image/webp", ".webp"), "GIF": ("image/gif", ".gif")}


@lru_cache(maxsize=1)
def system_faces():
    return json.loads(Path(__file__).with_name("qq_faces.json").read_text(encoding="utf-8"))


def media_label(media):
    if media.kind == "face":
        face_id = media.source.face_id
        return system_faces().get(face_id, {}).get("name") or f"QQ face {face_id or '?'}"
    return "[表情包]" if media.kind == "sticker" else "[图片]"


def media_url(media):
    source = media.source
    if media.kind == "face":
        face = system_faces().get(source.face_id)
        if face:
            suffix = f"static/s{source.face_id}.png" if face["static"] else f"gif/s{source.face_id}.gif"
            return "https://koishi.js.org/QFace/" + suffix
        return ""
    if source.url.startswith(("https://", "http://")):
        return source.url
    if source.file.startswith(("https://", "http://")):
        return source.file
    if re.fullmatch(r"[a-fA-F0-9]{32}", source.emoji_id):
        return f"https://gxh.vip.qq.com/club/item/parcel/item/{source.emoji_id[:2]}/{source.emoji_id}/raw300.gif"
    return ""


def decode_image(data):
    """Decode only the first frame; original animated bytes remain untouched."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as image:
            if image.format not in IMAGE_TYPES:
                raise ValueError("QQ images must be PNG, JPEG, WebP or GIF")
            mime, suffix = IMAGE_TYPES[image.format]
            animated = getattr(image, "is_animated", False)
            image.seek(0)
            frame = ImageOps.exif_transpose(image)
            frame.load()
            width, height = frame.size
            model_data = None
            if animated or mime == "image/gif":
                output = BytesIO()
                frame.convert("RGBA").save(output, format="PNG")
                model_data = output.getvalue()
        with Image.open(BytesIO(data)) as image:
            image.verify()
    return mime, suffix, width, height, model_data


class QQMediaService:
    def __init__(self, state, store, connections):
        self.state, self.store, self.connections = state, store, connections
        self.tasks = {}
        self.changed = asyncio.Event()

    def tick(self):
        for key in list(self.tasks):
            if self.tasks[key].done():
                self.tasks.pop(key).result()
        slots = MEDIA_CONCURRENCY - len(self.tasks)
        if slots:
            for media, project_id in self.store.pending_media(exclude=list(self.tasks), limit=slots):
                self.tasks[media.id] = asyncio.create_task(self.acquire(media, project_id))

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()

    async def wait_batch(self, batch_id):
        async def wait():
            while True:
                self.changed.clear()
                if not self.store.pending_media(batch_id=batch_id, limit=1):
                    return
                self.tick()
                await self.changed.wait()
        try:
            await asyncio.wait_for(wait(), MEDIA_WAIT_SECONDS)
        except asyncio.TimeoutError:
            # Pending images remain visible and can join a later model request.
            return

    async def download(self, media, project_id, settings):
        max_bytes = settings.max_image_size_mb * 1024 * 1024
        policy = replace(self.state.network_policy, max_response_bytes=max_bytes)
        url = media_url(media)
        failure = None
        if url:
            try:
                data, _, _ = await fetch_bytes(url, policy, max_bytes=max_bytes)
                return data
            except ToolExecutionError as exc:
                failure = exc
        connection = self.connections.get(project_id)
        if media.kind != "face" and media.source.file and connection is not None and connection.ready:
            response = await connection.call("get_image", {"file": media.source.file})
            resolved = response.get("url")
            if isinstance(resolved, str) and resolved.startswith(("http://", "https://")) and resolved != url:
                data, _, _ = await fetch_bytes(resolved, policy, max_bytes=max_bytes)
                return data
        if failure:
            raise failure
        raise ToolExecutionError("QQ_IMAGE_UNAVAILABLE", "No downloadable image resource is available.")

    def cleanup(self, attachment_ids):
        for attachment_id in attachment_ids:
            delete_attachment_if_unreferenced({"uri": "local://attachments/" + attachment_id}, self.state.messages,
                persona_store=self.state.personas, knowledge_store=self.state.knowledge, run_store=self.state.runs,
                qq_store=self.store)

    async def acquire(self, media, project_id):
        created = set()
        try:
            settings = self.state.app_settings.get()
            data = await self.download(media, project_id, settings)
            mime, suffix, width, height, model_data = await asyncio.to_thread(decode_image, data)

            def save(data, mime, suffix):
                saved = save_attachment_from_upload(f"qq-{media.message_id}-{media.segment_index}{suffix}", mime, data, settings)
                created.add(saved["uri"].removeprefix("local://attachments/"))
                return QQImageAttachment(id=saved["uri"].removeprefix("local://attachments/"),
                    **{key: saved[key] for key in ("name", "mime_type", "size", "uri")},
                    width=width, height=height).model_dump_json()

            media.attachment_json = save(data, mime, suffix)
            media.model_attachment_json = media.attachment_json
            if model_data is not None:
                if len(model_data) <= settings.max_image_size_mb * 1024 * 1024:
                    media.model_attachment_json = save(model_data, "image/png", ".png")
                else:
                    media.model_attachment_json = None
                    media.error_code = "QQ_IMAGE_TOO_LARGE"
            media.status = "ready"
        except (ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning,
                SyntaxError, EOFError) as exc:
            media.status, media.error_code = "failed", "QQ_IMAGE_INVALID"
            log.warning("QQ image decoding failed (%s)", type(exc).__name__)
        except (ToolExecutionError, OSError, WebSocketException, asyncio.TimeoutError) as exc:
            media.status, media.error_code = "failed", getattr(exc, "code", "QQ_IMAGE_UNAVAILABLE")
            log.warning("QQ image acquisition failed (%s)", media.error_code)
        finally:
            # Cancellation leaves the durable pending row for the next process.
            if media.status != "pending":
                if media.status == "failed":
                    media.attachment_json = media.model_attachment_json = None
                saved = self.store.finish_media(media)
                if not saved or media.status == "failed":
                    self.cleanup(created)
            self.changed.set()
