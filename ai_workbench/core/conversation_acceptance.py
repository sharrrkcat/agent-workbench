"""Accept identity, user input and its Run at one persistence boundary."""

from ai_workbench.core.chat_service import ChatError
from ai_workbench.db.models import SessionRecord


class ConversationAcceptance:
    def __init__(self, chat_service, messages, memory_store):
        self.chat = chat_service
        self.messages = messages
        self.store = memory_store

    def accept(self, session_id, *, kind="chat", text="", attachments=None, input_message_id=None,
               client_message_id=None, persona_id=None, resolved_config=None, tool_name=None):
        with self.store.transaction(conversation=True) as db:
            session = self.chat.sessions.get_session(session_id)
            self.chat.assert_idle(session_id)
            config = resolved_config or self.chat.resolve(session, persona_id=persona_id)
            if session.kind == "normal":
                selected = self.chat.selected_persona_id(session)
                if config.persona_id != selected:
                    raise ChatError("PERSONA_LOCKED", "The accepted input must use this Session's Persona.", 409)
                if db is not None:
                    row = db.get(SessionRecord, session_id)
                    row.bound_persona_id = selected
                    db.add(row)
                else:
                    self.chat.sessions.update_session(session_id, {"bound_persona_id": selected})
                config.sources.persona = "binding"
            transaction_args = {"transaction": db} if db is not None else {}
            user = None
            if kind == "chat":
                if input_message_id:
                    user = self.messages.get_message(input_message_id)
                    if (user.session_id != session_id or user.role != "user"
                        or session.kind == "normal" and user.speaker_id != config.persona_id):
                        raise ChatError("MESSAGE_SESSION_MISMATCH", "Input must belong to the bound conversation identity.")
                else:
                    user = self.messages.add_message(session_id=session_id, role="user", content=text,
                        speaker_id=config.persona_id, metadata={"attachments": attachments or [],
                            "client_message_id": client_message_id or None, "input_source": "chat"}, **transaction_args)
            metadata = {"configuration": config.public_summary(), "harness": bool(config.harness_enabled and config.tools_allowed)}
            if kind == "tool":
                metadata.update(tool_name=tool_name, direct=True, harness=True)
            else:
                metadata["input_message_id"] = user.message_id
                if session.kind == "qqbot":
                    metadata["qq_reply"] = {"sent_count": 0, "message_limit": config.qq_reply_message_limit,
                        "limit_reached": False, "skipped": False}
            run = self.chat.runs.create_run(kind=kind, character_id=config.character_id,
                persona_id=config.persona_id, session_id=session_id, metadata=metadata,
                config_snapshot=config.model_dump(mode="json"), **transaction_args)
            return config, user, run
