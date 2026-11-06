"""Direct QQ commands and durable notifications, separate from model batches."""
import asyncio
import logging
import re
import time
from uuid import uuid4

from sqlalchemy import update
from sqlmodel import Session, select

from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.qq_diagnostics import check_report, timestamp
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery, QQNotification

log = logging.getLogger(__name__)
USAGE = "用法：/cogita check；管理员：/cogita pause [group:群号|friend:QQ号|号码]、/cogita resume [目标]"
ERRORS = {
    "SESSION_BUSY": "会话仍有任务正在执行，请稍后重试。",
    "SESSION_NOT_FOUND": "目标会话不存在。",
    "QQ_TARGET_AMBIGUOUS": "号码对应多个会话，请用 group:群号 或 friend:QQ号。",
    "QQ_COMMAND_FORBIDDEN": "仅本项目配置的管理员 QQ 可以执行此指令。",
    "QQ_RUN_FAILED": "任务执行失败", "QQ_REPLY_REQUIRED": "模型未发送必需的回复",
    "QQ_INTERRUPTED": "任务因重启中断", "RUN_INTERRUPTED": "任务因重启中断",
    "QQ_ACTION_FAILED": "NapCat 操作失败", "QQ_SEND_ACK_TIMEOUT": "发送回执超时，结果不明",
    "QQ_DELIVERY_UNKNOWN": "发送结果不明", "QQ_DISCONNECTED": "NapCat 已断开",
    "QQ_CONNECTION_FAILED": "NapCat 连接失败", "QQ_AUTH_FAILED": "NapCat 认证失败",
    "QQ_ACCOUNT_MISMATCH": "NapCat 登录账号与项目不符", "RUN_CANCELLED": "任务意外取消",
}


class QQPrograms:
    def __init__(self, service):
        self.service, self.state, self.store = service, service.state, service.store
        self.commands = {}
        self.senders = {}
        self.active_commands = {}
        self.active_sends = {}

    async def close(self):
        tasks = [*self.commands.values(), *self.senders.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def busy(self, session_id, command_id=None, *, include_sends=True):
        return any(key != command_id and value == session_id for key, value in self.active_commands.items()) or (
            include_sends and session_id in self.active_sends.values())

    def ensure_admin(self, character):
        binding = self.store.binding(character.id, "friend", character.admin_qq)
        if binding is None:
            session = self.service.create_session(character.id, {"target_kind": "friend", "target_id": character.admin_qq,
                "title": f"QQ {character.admin_qq}"})
            binding = self.store.get(QQBinding, session.session_id)
            self.state.events.emit("session_updated", session_id=session.session_id,
                payload={"session": self.state.chat_service.session_response(session)})
        return binding

    def tick(self, characters):
        if self.service.stopping:
            return
        for workers in (self.commands, self.senders):
            for key, task in list(workers.items()):
                if task.done():
                    del workers[key]
                    task.result()
        for character in characters:
            if not character.connection_enabled:
                continue
            if character.id not in self.commands and self.next_command(character.id) is not None:
                self.commands[character.id] = asyncio.create_task(self.process_commands(character.id))
            if self.service.connected(character.id):
                self.prepare_notifications(character)
                if character.id not in self.senders and self.next_delivery(character.id) is not None:
                    self.senders[character.id] = asyncio.create_task(self.send_pending(character.id))

    def next_command(self, character_id):
        with Session(self.store.engine) as db:
            return db.exec(select(QQMessage).join(QQBinding, QQBinding.session_id == QQMessage.session_id).where(
                QQBinding.character_id == character_id, QQMessage.kind == "command", QQMessage.command_status == "pending",
                QQMessage.deleted == False).order_by(QQMessage.id).limit(1)).first()

    def next_delivery(self, character_id):
        with Session(self.store.engine) as db:
            return db.exec(select(QQDelivery).join(QQBinding, QQBinding.session_id == QQDelivery.session_id).where(
                QQBinding.character_id == character_id, QQDelivery.origin != "model", QQDelivery.status == "pending",
                QQDelivery.deleted == False).order_by(QQDelivery.id).limit(1)).first()

    @staticmethod
    def authorize(character, message):
        if character.admin_qq != message.sender_id:
            raise ChatError("QQ_COMMAND_FORBIDDEN", ERRORS["QQ_COMMAND_FORBIDDEN"], 403)

    def finish(self, db, message, text):
        current = db.get(QQMessage, message.id)
        if current is None or current.deleted or current.command_status != "pending":
            return
        current.command_status = "done"
        db.add(current)
        db.add(QQDelivery(session_id=current.session_id, origin="command", command_message_id=current.id,
            text=text, created_at=time.time()))
        self.store.advance_history(db, {current.session_id})

    def reply(self, message, text):
        with Session(self.store.engine) as db:
            self.finish(db, message, text)
            db.commit()

    def target(self, binding, value):
        if value is None:
            return binding
        match = re.fullmatch(r"(?:(group|friend):)?([1-9][0-9]{0,19})", value)
        if match is None:
            raise ChatError("QQ_COMMAND_USAGE", USAGE, 422)
        kind, number = match.groups()
        with Session(self.store.engine) as db:
            query = select(QQBinding).where(QQBinding.character_id == binding.character_id, QQBinding.target_id == number)
            if kind:
                query = query.where(QQBinding.target_kind == kind)
            rows = db.exec(query.limit(2)).all()
        if not rows:
            raise ChatError("SESSION_NOT_FOUND", ERRORS["SESSION_NOT_FOUND"], 404)
        if len(rows) > 1:
            raise ChatError("QQ_TARGET_AMBIGUOUS", ERRORS["QQ_TARGET_AMBIGUOUS"], 422)
        return rows[0]

    async def process_commands(self, character_id):
        while message := self.next_command(character_id):
            if not self.state.characters.get(character_id).connection_enabled:
                return
            self.active_commands[message.id] = message.session_id
            try:
                await self.process(message)
            except ChatError as exc:
                self.reply(message, ERRORS.get(exc.code, USAGE))
            except Exception:
                log.exception("QQ command failed (message %s)", message.id)
                self.reply(message, "指令执行失败（QQ_COMMAND_FAILED）。")
            finally:
                self.active_commands.pop(message.id, None)

    async def process(self, message):
        binding = self.store.get(QQBinding, message.session_id)
        character = self.state.characters.get(binding.character_id)
        parts = message.text.split()
        action = parts[1] if len(parts) > 1 else ""
        if action in {"pause", "resume"}:
            self.authorize(character, message)
            if len(parts) not in {2, 3}:
                self.reply(message, USAGE)
                return
            target = self.target(binding, parts[2] if len(parts) == 3 else None)
            await self.service.control(target.session_id, action, command=message)
        elif action == "check" and len(parts) == 2:
            resources = await asyncio.to_thread(self.state.runtime_resources.resources)
            self.reply(message, check_report(self.service, self.store.get(QQBinding, message.session_id), resources))
        else:
            self.reply(message, USAGE)

    def batch_finished(self, batch, *, notify=True, recovered=False):
        character = self.state.characters.get(batch.character_id)
        alert = notify and (recovered or batch.status in {"failed", "cancelled", "interrupted"}) and batch.error_code not in {
            "QQ_ICEBREAKER_CANCELLED", "QQ_STOPPED", "QQ_DISABLED"} and character.admin_qq is not None
        if alert:
            self.ensure_admin(character)
        with Session(self.store.engine) as db:
            db.add(batch)
            key = f"batch:{batch.session_id}:{batch.id}"
            if alert and db.exec(select(QQNotification.id).where(QQNotification.event_key == key)).first() is None:
                now = time.time()
                db.add(QQNotification(character_id=character.id, source_session_id=batch.session_id, event_key=key,
                    kind="session", error_code="QQ_INTERRUPTED" if recovered else batch.error_code or "QQ_RUN_FAILED", created_at=now,
                    last_at=now, resolved_at=now))
            db.commit()
            db.refresh(batch)

    def connection_failed(self, character_id, code):
        character = self.state.characters.get(character_id)
        if not character.admin_qq or not character.connection_enabled:
            return
        self.ensure_admin(character)
        now = time.time()
        with Session(self.store.engine) as db:
            event = db.exec(select(QQNotification).where(QQNotification.character_id == character_id,
                QQNotification.kind == "connection", QQNotification.resolved_at.is_(None),
                QQNotification.cancelled == False).limit(1)).first()
            if event is None:
                event = QQNotification(character_id=character_id, event_key=f"connection:{uuid4()}", kind="connection",
                    error_code=code, created_at=now, last_at=now)
            else:
                event.error_code, event.last_at = code, now
                event.occurrences += 1
            db.add(event)
            db.commit()

    def connection_restored(self, character_id):
        with Session(self.store.engine) as db:
            db.exec(update(QQNotification).where(QQNotification.character_id == character_id,
                QQNotification.kind == "connection", QQNotification.resolved_at.is_(None), QQNotification.cancelled == False)
                .values(resolved_at=time.time()))
            db.commit()

    def notification_text(self, character, event):
        binding = self.store.get(QQBinding, event.source_session_id) if event.source_session_id else None
        source = "NapCat 连接"
        if binding is not None:
            session = self.state.sessions.get_session(binding.session_id)
            source = f"{session.title} · {binding.target_kind}:{binding.target_id}"
        lines = [f"Cogita 异常通知 · {character.name}", f"来源：{source}", f"发生时间：{timestamp(event.created_at)}",
            f"{event.error_code}：{ERRORS.get(event.error_code, '任务执行失败，请查看 Cogita 中的任务详情。')}"]
        if event.kind == "connection":
            lines.append(f"连接已恢复：{timestamp(event.resolved_at)}；失败次数：{event.occurrences}")
        elif binding is not None:
            lines.append(f"当前状态：{'已暂停' if binding.paused else '未暂停'}")
            if binding.paused:
                lines.append(f"恢复：/cogita resume {binding.target_kind}:{binding.target_id}")
        return "\n".join(lines)

    def prepare_notifications(self, character):
        if not character.admin_qq:
            return
        with Session(self.store.engine) as db:
            events = db.exec(select(QQNotification).outerjoin(QQDelivery, QQDelivery.notification_id == QQNotification.id)
                .where(QQNotification.character_id == character.id, QQNotification.cancelled == False,
                    QQNotification.resolved_at.is_not(None), QQDelivery.id.is_(None))
                .order_by(QQNotification.id).limit(32)).all()
        if not events:
            return
        binding = self.ensure_admin(character)
        with Session(self.store.engine) as db:
            for event in events:
                db.add(QQDelivery(session_id=binding.session_id, origin="notification", notification_id=event.id,
                    text=self.notification_text(character, event), created_at=time.time()))
            self.store.advance_history(db, {binding.session_id})
            db.commit()

    def admin_changed(self, character):
        with Session(self.store.engine) as db:
            events = select(QQNotification.id).where(QQNotification.character_id == character.id)
            rows = db.exec(select(QQDelivery).where(QQDelivery.notification_id.in_(events),
                QQDelivery.status == "pending", QQDelivery.deleted == False)).all()
        binding = self.ensure_admin(character) if character.admin_qq and rows else None
        with Session(self.store.engine) as db:
            changed = set()
            for row in rows:
                changed.add(row.session_id)
                if binding is None:
                    row.status = "cancelled"
                else:
                    row.session_id = binding.session_id
                    changed.add(binding.session_id)
                db.add(row)
            if character.admin_qq is None:
                db.exec(update(QQNotification).where(QQNotification.character_id == character.id).values(cancelled=True))
            self.store.advance_history(db, changed)
            db.commit()

    async def send_pending(self, character_id):
        while self.service.connected(character_id) and (delivery := self.next_delivery(character_id)):
            if not self.state.characters.get(character_id).connection_enabled:
                return
            self.active_sends[delivery.id] = delivery.session_id
            try:
                async with self.service.send_lock(delivery.session_id):
                    current = self.store.get(QQDelivery, delivery.id)
                    if current is None or current.deleted or current.status != "pending":
                        continue
                    # An admin edit may have moved this intent while it waited for another send.
                    if current.session_id != delivery.session_id:
                        continue
                    if not self.service.connected(character_id) or not self.state.characters.get(character_id).connection_enabled:
                        return
                    await self.service.transmit(current, {"type": "text", "data": {"text": current.text}})
                    self.store.save(current)
            except ToolExecutionError:
                pass  # transmit persisted the terminal outcome; program sends never pause or retry.
            finally:
                self.active_sends.pop(delivery.id, None)
