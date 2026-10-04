"""Project-scoped OneBot connections and durable FIFO execution."""
import asyncio
import logging
import time
from websockets.exceptions import InvalidStatus, WebSocketException
from sqlmodel import Session as DbSession
from pydantic import ValidationError
from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.harness.schema import ToolSpec, ToolExecutionError
from ai_workbench.core.qq_protocol import OneBotConnection, normalize
from ai_workbench.core.qq_names import QQNames
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery

log = logging.getLogger(__name__)


class QQService:
    def __init__(self, state, store):
        self.state = state
        self.store = store
        self.connections = {}
        self.names = QQNames(self.connections)
        self.tasks = {}
        self.workers = {}
        self.supervisor = None
        self.store.recover()
        state.tool_registry.register(ToolSpec("qq_send_message", "Send one plain-text message to the current QQ conversation.",
            {"type": "object", "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 4000}},
             "required": ["text"], "additionalProperties": False}, lambda args, context: self.send(args, context), "network", False, False))

    def start(self):
        self.supervisor = asyncio.create_task(self.run())

    async def close(self):
        tasks = [*self.tasks.values(), *self.workers.values()]
        if self.supervisor:
            tasks.append(self.supervisor)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.names.close()

    async def run(self):
        while True:
            all_projects = [p for p in self.state.projects.list() if p.kind == "qqbot"]
            self.names.retain_projects({p.id for p in all_projects})
            projects = {p.id: p for p in all_projects if p.connection_enabled}
            for key in list(self.tasks):
                connection = self.connections[key]
                project = projects.get(key)
                if project is None or any(getattr(project, f) != getattr(connection.project, f)
                        for f in ("websocket_url", "access_token", "bot_account")):
                    task = self.tasks.pop(key)
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    self.connections.pop(key)
            for key in list(self.workers):
                if key not in projects and self.workers[key].done():
                    self.workers.pop(key).result()
            for key, project in projects.items():
                if key not in self.tasks:
                    connection = OneBotConnection(project, lambda event, pid=key: self.ingest(pid, event))
                    self.connections[key] = connection
                    self.tasks[key] = asyncio.create_task(self.connect(connection))
                for binding in self.store.bindings(key):
                    self.store.freeze(binding.session_id, project.batch_message_limit, time.time())
                worker = self.workers.get(key)
                if worker is None or worker.done():
                    if worker is not None:
                        worker.result()
                    if self.connections[key].ready:
                        batch = self.store.next_batch(key)
                        if batch:
                            self.workers[key] = asyncio.create_task(self.execute(batch))
            await asyncio.sleep(0.1)

    async def connect(self, connection):
        while True:
            try:
                connection.status = "connecting"
                await connection.run()
            except ToolExecutionError as exc:
                connection.status = exc.code
            except InvalidStatus as exc:
                connection.status = "QQ_AUTH_FAILED" if exc.response.status_code in (401, 403) else "QQ_CONNECTION_FAILED"
            except (OSError, WebSocketException, ValueError, asyncio.TimeoutError):
                connection.status = "QQ_CONNECTION_FAILED"
            connection.ready = False
            await asyncio.sleep(3)

    async def ingest(self, project_id, event, *, now=None):
        project = self.state.projects.get(project_id)
        if str(event.get("self_id")) != project.bot_account:
            return
        own = str(event.get("user_id")) == project.bot_account or event.get("post_type") == "message_sent"
        kind = {"group": "group", "private": "friend"}.get(event.get("message_type"))
        if kind is None:
            return
        target = str(event.get("group_id") if kind == "group" else
            event.get("target_id", event.get("user_id")) if own else event.get("user_id"))
        binding = self.store.binding(project_id, kind, target)
        if binding is None:
            return
        if own:
            self.store.reconcile_echo(binding.session_id, str(event.get("message_id")))
            return
        try:
            values, keyword_text = normalize(event)
        except ValidationError:
            log.warning("Ignored malformed OneBot message for a bound conversation")
            return
        now = time.time() if now is None else now
        # Synchronous transactions run without yielding: expiry wins at the exact deadline.
        self.store.freeze(binding.session_id, project.batch_message_limit, now)
        if self.store.ingest(binding, QQMessage(session_id=binding.session_id, **values),
                trigger=kind == "friend" or any(k in keyword_text for k in project.keywords), now=now):
            self.names.observe(binding, values["sender_id"], values["sender_name"])

    async def execute(self, batch):
        binding = self.store.get(QQBinding, batch.session_id)
        if binding is None or binding.paused:
            return
        if not self.state.projects.get(binding.project_id).connection_enabled:
            return
        batch.status = "running"
        self.store.save(batch)
        def run_created(run_id):
            batch.run_id = run_id
            self.store.save(batch)
        try:
            config = self.state.chat_service.resolve(self.state.sessions.get_session(batch.session_id))
            rows = await self.names.project(binding, config.qq_bot_account,
                [row.model_dump() for row in self.store.batch_messages(batch.id)], freeze=True, for_model=True)
            self.store.save_references(rows)
            text = "\n".join(f"[{row['timestamp']}][{row['sender_name']}（QQ:{row['sender_id']}）]:{row['text']}" for row in rows)
            user = self.state.messages.add_message(batch.session_id, role="user", content=text,
                metadata={"input_source": "qq", "qq_batch_id": batch.id})
            batch.input_message_id = user.message_id
            self.store.save(batch)
            result = await self.state.chat_runner.run(session_id=batch.session_id, text=text,
                input_message_id=user.message_id, on_run_created=run_created, resolved_config=config)
            batch.run_id = result.run_id
            batch.status = "done" if result.success else (
                "cancelled" if result.error_code == "RUN_CANCELLED" else "failed")
            batch.error_code = result.error_code
            if not result.success:
                self.store.pause(batch.session_id, result.error_code or "QQ_RUN_FAILED")
        except asyncio.CancelledError:
            batch.status, batch.error_code = "cancelled", "RUN_CANCELLED"
            self.store.pause(batch.session_id, "RUN_CANCELLED")
        except Exception as exc:
            # A failed background job must leave a durable, visible pause, not a lost queue head.
            log.error("QQ batch execution failed (%s)", type(exc).__name__)
            batch.status, batch.error_code = "failed", "QQ_RUN_FAILED"
            self.store.pause(batch.session_id, "QQ_RUN_FAILED")
        finally:
            self.store.save(batch)

    async def send(self, arguments, context):
        session = self.state.sessions.get_session(context.session_id)
        if session.kind != "qqbot" or not context.run_id or not context.tool_call_id:
            raise ToolExecutionError("TOOL_NOT_ALLOWED", "QQ sending requires a QQBot run.")
        if not arguments["text"].strip():
            raise ToolExecutionError("TOOL_INVALID_ARGUMENTS", "Message cannot be blank.")
        existing = self.store.delivery(context.run_id, context.tool_call_id)
        if existing:
            if existing.status == "sent":
                return {"delivery_id": existing.id, "message_id": existing.external_id, "status": "sent"}
            raise ToolExecutionError("QQ_DELIVERY_NOT_REPLAYABLE", "A previous send must not be replayed.")
        delivery = self.store.save(QQDelivery(session_id=session.session_id, run_id=context.run_id,
            tool_call_id=context.tool_call_id, text=arguments["text"], created_at=time.time()))
        connection = self.connections.get(session.project_id)
        try:
            if connection is None or not connection.ready:
                raise ToolExecutionError("QQ_DISCONNECTED", "QQ is disconnected.")
            if not self.state.projects.get(session.project_id).connection_enabled:
                raise ToolExecutionError("QQ_DISABLED", "QQ connection is disabled.")
            delivery.status = "sending"
            self.store.save(delivery)
            action = "send_group_msg" if session.target_kind == "group" else "send_private_msg"
            target = "group_id" if session.target_kind == "group" else "user_id"
            result = await connection.call(action, {target: int(session.target_id),
                "message": [{"type": "text", "data": {"text": arguments["text"]}}]})
            if not isinstance(result.get("message_id"), (str, int)):
                raise ValueError("Missing message id")
            delivery.external_id, delivery.status = str(result["message_id"]), "sent"
            # Persist confirmation and its historical reply in one SQLite transaction.
            with DbSession(self.store.engine) as db:
                transaction = {"transaction": db} if getattr(self.state.messages, "engine", None) is not None else {}
                message = self.state.messages.add_message(session.session_id, role="assistant", content=delivery.text,
                    speaker_id=self.state.runs.get_run(context.run_id).persona_id, run_id=context.run_id,
                    metadata={"qq_delivery_id": delivery.id, "qq_external_id": delivery.external_id}, **transaction)
                db.add(delivery)
                db.commit()
                db.refresh(delivery)
            self.state.events.emit("message_completed", session_id=session.session_id, run_id=context.run_id,
                message_id=message.message_id, payload={"message": message.model_dump(mode="json")})
            return {"delivery_id": delivery.id, "message_id": delivery.external_id, "status": "sent"}
        except ToolExecutionError as exc:
            delivery.status, delivery.error_code = "failed", exc.code
            self.store.save(delivery)
            self.store.pause(session.session_id, exc.code)
            raise
        except (OSError, WebSocketException, ValueError, asyncio.TimeoutError, asyncio.CancelledError) as exc:
            delivery.status, delivery.error_code = "unknown", "QQ_DELIVERY_UNKNOWN"
            self.store.save(delivery)
            self.store.pause(session.session_id, delivery.error_code)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ToolExecutionError(delivery.error_code, "QQ send result is unknown; automatic resend is disabled.") from exc

    def create_session(self, project_id, values):
        if self.state.projects.get(project_id).kind != "qqbot":
            raise ChatError("PROJECT_TYPE_INVALID", "Choose a QQBot Project.", 422)
        if self.store.binding(project_id, values["target_kind"], values["target_id"]):
            raise ChatError("QQ_TARGET_BOUND", "This conversation already has a Session.", 409)
        session = self.state.sessions.create_session(kind="qqbot", project_id=project_id, **values)
        self.store.save(QQBinding(session_id=session.session_id, project_id=project_id,
            target_kind=session.target_kind, target_id=session.target_id))
        return session

    def control(self, session_id, action):
        binding = self.store.get(QQBinding, session_id)
        if binding is None:
            raise ChatError("SESSION_NOT_FOUND", "QQ Session does not exist.", 404)
        if action == "resume":
            self.assert_idle(session_id)
        self.store.pause(session_id, "" if action == "resume" else "QQ_PAUSED")
        if action == "stop":
            task = self.workers.get(binding.project_id)
            # Cancel only the worker serving this Session.
            active = self.store.active_batch(session_id)
            if active is not None and task:
                if active.run_id:
                    from ai_workbench.core.schema.run import RunStatus
                    run = self.state.runs.get_run(active.run_id)
                    if run.status not in {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}:
                        self.state.runs.update_status(active.run_id, RunStatus.CANCELLING, cancel_requested=True)
                task.cancel()
        return self.store.get(QQBinding, session_id)

    def assert_idle(self, session_id):
        if self.store.active_batch(session_id):
            raise ChatError("SESSION_BUSY", "Stop the active QQ batch first.", 409)
