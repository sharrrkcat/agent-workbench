"""OneBot v11 transport and ordered ingress. QQ/NapCat remains external."""
import asyncio
import json
import re
from datetime import datetime, timezone
from uuid import uuid4
from websockets.asyncio.client import connect
from pydantic import BaseModel, Field, StrictInt, StrictStr, ConfigDict
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.schema.qq import QQMediaSource


class OneBotSegment(BaseModel):
    type: str
    data: dict = Field(default_factory=dict)


class OneBotSender(BaseModel):
    card: str = ""
    nickname: str = ""


class OneBotUser(OneBotSender):
    model_config = ConfigDict(strict=True)
    user_id: StrictInt | StrictStr


class OneBotMessage(BaseModel):
    # Adapter extensions are ignored at this protocol boundary.
    model_config = ConfigDict(allow_inf_nan=False)
    message_id: StrictInt | StrictStr
    user_id: StrictInt | StrictStr
    time: float = Field(ge=0, le=253402300799)
    sender: OneBotSender = Field(default_factory=OneBotSender)
    message: list[OneBotSegment] | str


def _cq_segments(value):
    def decode(text):
        return text.replace("&#91;", "[").replace("&#93;", "]").replace("&#44;", ",").replace("&amp;", "&")
    result, offset = [], 0
    for match in re.finditer(r"\[CQ:(\w+)((?:,[^\]]*)?)\]", value):
        result.append(OneBotSegment(type="text", data={"text": decode(value[offset:match.start()])}))
        data = dict(part.split("=", 1) for part in match[2].split(",")[1:] if "=" in part)
        result.append(OneBotSegment(type=match[1], data={key: decode(val) for key, val in data.items()}))
        offset = match.end()
    result.append(OneBotSegment(type="text", data={"text": decode(value[offset:])}))
    return result


def _card_string(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def _card_text(kind, data):
    if kind == "share":
        label = "分享链接"
        title, url = _card_string(data.get("title")), _card_string(data.get("url"))
    else:
        payload = data.get("data", data.get("content") if kind == "lightapp" else None)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return "[非文字消息]"
        if not isinstance(payload, dict):
            return "[非文字消息]"
        meta = payload.get("meta")
        meta = meta if isinstance(meta, dict) else {}
        if kind == "lightapp" or _card_string(payload.get("app")).startswith("com.tencent.miniapp"):
            label = "小程序"
            detail = meta.get("detail_1")
            detail = detail if isinstance(detail, dict) else {}
            title = _card_string(payload.get("prompt")) or _card_string(detail.get("title"))
            url = (_card_string(detail.get("qqdocurl")) or _card_string(detail.get("jumpUrl"))
                or _card_string(detail.get("url")))
        elif isinstance(meta.get("news"), dict):
            label = "分享链接"
            title = _card_string(meta["news"].get("title")) or _card_string(payload.get("prompt"))
            url = _card_string(meta["news"].get("jumpUrl"))
        else:
            return "[非文字消息]"
    summary = f"{title} ({url})" if title and url else title or url
    return f"[{label}: {summary}]" if summary else f"[{label}]"


def normalize(event):
    parsed = OneBotMessage.model_validate(event)
    segments = _cq_segments(parsed.message) if isinstance(parsed.message, str) else parsed.message
    text, keywords, refs, media, offset = [], [], [], [], 0
    placeholders = {"image": "[图片]", "face": "[表情包]", "mface": "[表情包]",
        "record": "[语音]", "video": "[视频]", "file": "[文件]", "forward": "[转发消息]"}
    for index, segment in enumerate(segments):
        kind, data = segment.type, segment.data
        if kind == "text":
            value = str(data.get("text", ""))
            text.append(value)
            keywords.append(value)
        elif kind == "at":
            value = str(data.get("qq", ""))
            text.append("@" + value)
            keywords.append(text[-1])
            refs.append({"type": "at", "id": value, "start": offset, "end": offset + len(text[-1]),
                         "name": None, "is_self": value == str(event.get("self_id")), "frozen": False})
        elif kind == "reply":
            value = str(data.get("id", ""))
            text.append("[引用:" + value + "]")
            refs.append({"type": "reply", "id": value})
        elif kind in {"share", "json", "lightapp"}:
            text.append(_card_text(kind, data))
        else:
            sticker = kind == "image" and (str(data.get("sub_type", "0")) != "0" or bool(data.get("emoji_id")))
            text.append("[表情包]" if sticker else placeholders.get(kind, "[非文字消息]"))
            if kind in {"image", "face", "mface"}:
                source = QQMediaSource(url=str(data.get("url") or ""), file=str(data.get("file") or ""),
                    face_id=str(data.get("id", "")) if kind == "face" else "",
                    emoji_id=str(data.get("emoji_id") or ""))
                media.append(dict(segment_index=index, text_start=offset, text_end=offset + len(text[-1]),
                    kind="face" if kind == "face" else "sticker" if sticker or kind == "mface" else "image",
                    source_json=source.model_dump_json()))
        offset += len(text[-1])
    sender_id = str(parsed.user_id)
    return dict(external_id=str(parsed.message_id), sender_id=sender_id,
        sender_name=parsed.sender.card or parsed.sender.nickname or sender_id,
        timestamp=datetime.fromtimestamp(parsed.time, timezone.utc).isoformat(),
        text="".join(text), references_json=json.dumps(refs, ensure_ascii=False)), "".join(keywords).casefold(), media


class OneBotConnection:
    def __init__(self, project, receive):
        self.project, self.receive = project, receive
        self.socket = None
        self.pending = {}
        self.ready = False
        self.status = "connecting"
        self.login_name = ""

    async def run(self):
        headers = {"Authorization": "Bearer " + self.project.access_token} if self.project.access_token else {}
        async with connect(self.project.websocket_url, additional_headers=headers, max_size=1024 * 1024,
                           max_queue=16, open_timeout=10) as socket:
            self.socket = socket
            try:
                login = OneBotUser.model_validate(await asyncio.wait_for(self.login(), 20))
                if str(login.user_id) != self.project.bot_account:
                    raise ToolExecutionError("QQ_ACCOUNT_MISMATCH", "Connected account differs from the Project.")
                self.login_name = login.nickname
                self.ready, self.status = True, "connected"
                await self.read()
            finally:
                self.ready = False
                for future in self.pending.values():
                    if not future.done():
                        future.set_exception(ConnectionError("OneBot disconnected"))
                self.socket = None

    async def login(self):
        echo = str(uuid4())
        await self.socket.send(json.dumps({"action": "get_login_info", "params": {}, "echo": echo}))
        async for raw in self.socket:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Expected OneBot object")
            if value.get("echo") == echo:
                return self.action_data(value)
        raise ConnectionError("OneBot disconnected before account verification")

    @staticmethod
    def action_data(response):
        if response.get("status") != "ok" or response.get("retcode") != 0:
            raise ToolExecutionError("QQ_ACTION_FAILED", "OneBot rejected the action.")
        data = response.get("data")
        if not isinstance(data, dict):
            raise ValueError("Expected OneBot action data")
        return data

    async def read(self):
        async for raw in self.socket:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Expected OneBot object")
            echo = value.get("echo")
            if isinstance(echo, str) and echo in self.pending:
                future = self.pending[echo]
                if not future.done():
                    future.set_result(value)
            elif self.ready and value.get("post_type") in {"message", "message_sent"}:
                await self.receive(value)

    async def call(self, action, params):
        if self.socket is None:
            raise ConnectionError("OneBot is disconnected")
        echo = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[echo] = future
        try:
            await self.socket.send(json.dumps({"action": action, "params": params, "echo": echo}))
            response = await asyncio.wait_for(future, 20)
            return self.action_data(response)
        finally:
            self.pending.pop(echo, None)
