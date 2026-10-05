"""Project-scoped OneBot connections and durable FIFO execution."""
import asyncio
import base64
import logging
import time
from websockets.exceptions import InvalidStatus, WebSocketException
from sqlmodel import Session as DbSession
from pydantic import ValidationError
from ai_workbench.core.chat_service import ChatError
from ai_workbench.core.harness.schema import ToolSpec, ToolExecutionError
from ai_workbench.core.qq_protocol import OneBotConnection, normalize
from ai_workbench.core.qq_names import QQNames, model_batch_text
from ai_workbench.core.qq_history import QQHistory
from ai_workbench.core.qq_media import QQMediaService
from ai_workbench.core.qq_descriptions import QQDescriptionService
from ai_workbench.core.qq_generation import prepare_image
from ai_workbench.core.qq_icebreaker import QQIcebreaker, ICEBREAKER_SETTINGS
from ai_workbench.db.qq_models import QQBinding, QQMessage, QQBatch, QQDelivery

log = logging.getLogger(__name__)


class QQService:
    def __init__(self, state, store):
        self.state = state
        self.store = store
        self.history = QQHistory(state, store)
        self.connections = {}
        self.media = QQMediaService(state, store, self.connections)
        self.descriptions = QQDescriptionService(store, state.model_manager)
        self.names = QQNames(self.connections)
        self.tasks = {}
        self.workers = {}
        self.supervisor = None
        self.store.recover()
        self.icebreaker = QQIcebreaker(store)
        state.tool_registry.register(ToolSpec("qq_send_message", "Send one plain-text message to the current QQ conversation.",
            {"type": "object", "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 4000}},
             "required": ["text"], "additionalProperties": False}, lambda args, context: self.send(args, context), "network", False, False))
        state.tool_registry.register(ToolSpec("qq_skip_reply", "End this optional follow-up or icebreaker batch without replying. Available only before sending a reply.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            lambda args, context: self.skip(context), "safe", False, False))
        state.tool_registry.register(ToolSpec("qq_generate_image",
            "Generate and immediately send one image to the current QQ conversation. A successful send uses one reply slot. "
            "Only supply a drawing prompt; size, quality and style come from Project settings. Generation may take a while.",
            {"type": "object", "properties": {"prompt": {"type": "string", "minLength": 1, "maxLength": 32000, "pattern": r"\S"}},
             "required": ["prompt"], "additionalProperties": False}, lambda args, context: self.generate_image(args, context), "network", False, False))

    def start(self):
        self.supervisor = asyncio.create_task(self.run())

    async def close(self):
        for session_id in list(self.icebreaker.groups):
            self.icebreaker.reset_session(session_id)
        tasks = [*self.tasks.values(), *self.workers.values()]
        if self.supervisor:
            tasks.append(self.supervisor)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.media.close()
        await self.descriptions.close()
        await self.names.close()

    async def run(self):
        while True:
            self.media.tick()
            all_projects = [p for p in self.state.projects.list() if p.kind == "qqbot"]
            self.names.retain_projects({p.id for p in all_projects})
            projects = {p.id: p for p in all_projects if p.connection_enabled}
            for key in list(self.tasks):
                connection = self.connections[key]
                project = projects.get(key)
                if project is None or any(getattr(project, f) != getattr(connection.project, f)
                        for f in ("websocket_url", "access_token", "bot_account")):
                    self.icebreaker.reset_project(key)
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
                    self.tick_binding(project, binding, time.time())
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
            finally:
                self.icebreaker.reset_project(connection.project.id)
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
            values, keyword_text, media = normalize(event)
        except ValidationError:
            log.warning("Ignored malformed OneBot message for a bound conversation")
            return
        if not values["text"].strip():
            return
        now = time.time() if now is None else now
        # Synchronous transactions run without yielding: expiry wins at the exact deadline.
        self.tick_binding(project, binding, now)
        message_id = self.store.ingest(binding, QQMessage(session_id=binding.session_id, **values),
            keyword=any(k in keyword_text for k in project.keywords), now=now, media=media)
        if message_id:
            self.names.observe(binding, values["sender_id"], values["sender_name"])
            if project.icebreaker_enabled:
                current = self.store.get(QQBinding, binding.session_id)
                self.icebreaker.observe(project, current, self.connected(project.id), message_id, values["sender_id"], now)

    def connected(self, project_id):
        connection = self.connections.get(project_id)
        return connection is not None and connection.ready

    def tick_binding(self, project, binding, now):
        self.store.freeze(binding.session_id, project.batch_message_limit, now)
        if project.icebreaker_enabled or binding.session_id in self.icebreaker.groups:
            current = self.store.get(QQBinding, binding.session_id)
            self.icebreaker.tick(project, current, self.connected(project.id), now)

    def project_updated(self, previous, current):
        if current.kind == "qqbot" and any(getattr(previous, field) != getattr(current, field) for field in ICEBREAKER_SETTINGS):
            self.icebreaker.reset_project(current.id)
            for binding in self.store.bindings(current.id):
                self.icebreaker.sync(current, binding, self.connected(current.id), time.time())

    def check_icebreaker(self, batch):
        binding = self.store.get(QQBinding, batch.session_id)
        project = self.state.projects.get(binding.project_id)
        return self.icebreaker.check(batch, project, binding, self.connected(project.id), time.time())

    async def execute(self, batch):
        # A queued batch may have been emptied after the supervisor selected it.
        current = self.store.get(QQBatch, batch.id)
        if current is None or current.status != "queued":
            return
        batch.text = current.text
        binding = self.store.get(QQBinding, batch.session_id)
        if binding is None or binding.paused:
            return
        if not self.state.projects.get(binding.project_id).connection_enabled:
            return
        attempt = self.icebreaker.begin(batch) if batch.trigger_kind == "icebreaker" else None
        if batch.trigger_kind == "icebreaker" and attempt is None:
            return
        batch.status = "running"
        self.store.save(batch)
        def run_created(run_id):
            batch.run_id = run_id
            self.store.save(batch)
        try:
            if attempt is not None:
                self.check_icebreaker(batch)
            config = self.state.chat_service.resolve(self.state.sessions.get_session(batch.session_id))
            if attempt is not None:
                config = config.model_copy(update={"qq_reply_message_limit": 1})
            if config.context_policy.include_attachments == "explicit":
                await self.media.wait_batch(batch.id)
            records = self.store.batch_messages(batch.id)
            rows = await self.names.project(binding, config.qq_bot_account,
                [row.model_dump() for row in records], freeze=True, for_model=True)
            self.store.save_references(rows)
            for record, row in zip(records, rows):
                record.references_json = row["references_json"]
            text = model_batch_text(records)
            if attempt is not None:
                self.check_icebreaker(batch)
            user = self.state.messages.add_message(batch.session_id, role="user", content=text,
                metadata={"input_source": "qq", "qq_batch_id": batch.id, "qq_trigger_kind": batch.trigger_kind})
            batch.input_message_id = user.message_id
            self.store.save(batch)
            def context_ready(trace):
                if attempt is not None:
                    self.check_icebreaker(batch)
                    project = self.state.projects.get(binding.project_id)
                    self.store.start_icebreaker_cooldown(batch.session_id, time.time() + project.icebreaker_cooldown_seconds)
                self.descriptions.submit(config.qq_image_description_model_profile_id,
                    trace, self.state.app_settings.get().max_image_size_mb * 1024 * 1024)
            result = await self.state.chat_runner.run(session_id=batch.session_id, text=text,
                input_message_id=user.message_id, on_run_created=run_created, resolved_config=config,
                on_context_ready=context_ready)
            batch.run_id = result.run_id
            batch.status = "done" if result.success else (
                "cancelled" if result.error_code == "RUN_CANCELLED" else "failed")
            batch.error_code = result.error_code
            if attempt is not None and attempt.cancelled:
                batch.status, batch.error_code = "cancelled", "QQ_ICEBREAKER_CANCELLED"
            elif not result.success:
                self.store.pause(batch.session_id, result.error_code or "QQ_RUN_FAILED")
        except asyncio.CancelledError:
            batch.status, batch.error_code = "cancelled", "RUN_CANCELLED"
            if attempt is not None and attempt.cancelled:
                batch.error_code = "QQ_ICEBREAKER_CANCELLED"
            else:
                self.store.pause(batch.session_id, "RUN_CANCELLED")
        except Exception as exc:
            # A failed background job must leave a durable, visible pause, not a lost queue head.
            log.error("QQ batch execution failed (%s)", type(exc).__name__)
            batch.status, batch.error_code = "failed", "QQ_RUN_FAILED"
            self.store.pause(batch.session_id, "QQ_RUN_FAILED")
        finally:
            self.store.save(batch)
            if attempt is not None:
                self.icebreaker.finish(batch.id)

    def tool_batch(self, context):
        session = self.state.sessions.get_session(context.session_id)
        if session.kind != "qqbot" or not context.run_id or not context.tool_call_id:
            raise ToolExecutionError("TOOL_NOT_ALLOWED", "QQ tools require a QQBot run.")
        batch = self.store.active_batch(session.session_id)
        if batch is None or batch.run_id != context.run_id:
            raise ToolExecutionError("TOOL_NOT_ALLOWED", "QQ tools require the active batch run.")
        return session, batch

    async def skip(self, context):
        _, batch = self.tool_batch(context)
        if batch.trigger_kind not in {"followup", "icebreaker"} or self.store.has_sent(context.run_id):
            raise ToolExecutionError("TOOL_NOT_ALLOWED", "Only an unanswered optional batch can skip its reply.")
        if batch.trigger_kind == "icebreaker":
            self.check_icebreaker(batch)
        else:
            self.store.skip_participants(batch, time.time())
        return {"status": "skipped"}

    async def send(self, arguments, context):
        if not arguments["text"].strip():
            raise ToolExecutionError("TOOL_INVALID_ARGUMENTS", "Message cannot be blank.")
        return await self.deliver(arguments["text"], context)

    async def generate_image(self, arguments, context):
        self.tool_batch(context)
        if context.qq_image_generation_model_profile_id is None:
            raise ToolExecutionError("TOOL_NOT_ALLOWED", "Image generation is disabled for this QQBot run.")
        existing = self.store.delivery(context.run_id, context.tool_call_id)
        if existing:
            return self.delivery_receipt(existing)
        prepared = await prepare_image(self.state, arguments["prompt"], context)
        try:
            return await self.deliver(f"[生成的图片:{arguments['prompt']}]", context,
                prompt=arguments["prompt"], image=prepared)
        finally:
            self.media.cleanup(prepared.attachment_ids)

    @staticmethod
    def delivery_receipt(delivery):
        if delivery.status != "sent":
            raise ToolExecutionError("QQ_DELIVERY_NOT_REPLAYABLE", "A previous send must not be replayed.")
        return {"delivery_id": delivery.id, "message_id": delivery.external_id, "status": "sent",
            **({"content": delivery.text} if delivery.kind == "generated_image" else {})}

    async def deliver(self, text, context, *, prompt=None, image=None):
        session, batch = self.tool_batch(context)
        existing = self.store.delivery(context.run_id, context.tool_call_id)
        if existing:
            return self.delivery_receipt(existing)
        if batch.trigger_kind == "icebreaker":
            # No await separates this check, the durable intent and OneBot submission.
            self.check_icebreaker(batch).dispatched = True
        delivery = self.store.save(QQDelivery(session_id=session.session_id, run_id=context.run_id,
            tool_call_id=context.tool_call_id, text=text, created_at=time.time(),
            kind="generated_image" if image is not None else "text", prompt=prompt))
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
            segment = ({"type": "image", "data": {"file": "base64://" + base64.b64encode(image.data).decode("ascii")}}
                if image is not None else {"type": "text", "data": {"text": text}})
            result = await connection.call(action, {target: int(session.target_id),
                "message": [segment]})
            if not isinstance(result.get("message_id"), (str, int)):
                raise ValueError("Missing message id")
            delivery.external_id, delivery.status = str(result["message_id"]), "sent"
            # Persist confirmation and its historical reply in one SQLite transaction.
            with DbSession(self.store.engine) as db:
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                if image is not None:
                    delivery.asset_id = self.store.confirm_generated_asset(db, image.asset, prompt, session.session_id)
                transaction = {"transaction": db} if getattr(self.state.messages, "engine", None) is not None else {}
                message = self.state.messages.add_message(session.session_id, role="assistant", content=delivery.text,
                    speaker_id=self.state.runs.get_run(context.run_id).persona_id, run_id=context.run_id,
                    metadata={"qq_delivery_id": delivery.id, "qq_external_id": delivery.external_id}, **transaction)
                db.add(delivery)
                self.store.renew_participants(db, batch, time.time())
                db.commit()
                db.refresh(delivery)
            self.icebreaker.confirmed_send(session.session_id, time.time())
            self.state.events.emit("message_completed", session_id=session.session_id, run_id=context.run_id,
                message_id=message.message_id, payload={"message": message.model_dump(mode="json")})
            return self.delivery_receipt(delivery)
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
        self.icebreaker.reset_session(session_id)
        self.store.pause(session_id, "" if action == "resume" else "QQ_PAUSED")
        if action == "resume":
            self.icebreaker.sync(self.state.projects.get(binding.project_id), self.store.get(QQBinding, session_id),
                self.connected(binding.project_id), time.time())
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
