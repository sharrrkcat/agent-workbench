"""Normal-owner removal and the selected memory destination share a transaction."""

from sqlalchemy import delete
from sqlmodel import select

from ai_workbench.core.attachments import delete_attachment_if_unreferenced
from ai_workbench.core.web_cache import delete_session_web_pages
from ai_workbench.db.models import (CharacterRecord, SessionRecord, MessageRecord, RunRecord,
    RunStepRecord, RunEventRecord, ContextCheckpointRecord, ContextRetrievalRecord)


def delete_normal_owner(state, choice, *, session_id=None, character_id=None):
    memory = state.memory
    with memory.store.transaction(conversation=True) as db:
        if session_id:
            owner = state.sessions.get_session(session_id).character_id
            ids = [session_id]
        else:
            owner = character_id
            state.character_service.assert_deletable(character_id)
            ids = [session.session_id for session in state.character_service.sessions(character_id)]
        memory.assert_character_idle(owner)
        attachments = set()
        for current_id in ids:
            attachments.update(state.messages.attachment_filenames(session_id=current_id))
            attachments.update(state.runs.context_attachment_ids(session_id=current_id))
        memory.apply_deletion(choice, session_id=session_id, character_id=character_id, transaction=db)
        for current_id in ids:
            memory.store.remove_session_dependencies(current_id, transaction=db)
        if db is not None:
            run_ids = select(RunRecord.run_id).where(RunRecord.session_id.in_(ids))
            db.exec(delete(RunStepRecord).where(RunStepRecord.run_id.in_(run_ids)))
            for model in (RunEventRecord, ContextCheckpointRecord, ContextRetrievalRecord, MessageRecord, RunRecord):
                db.exec(delete(model).where(model.session_id.in_(ids)))
            for current_id in ids:
                delete_session_web_pages(db, current_id)
            db.exec(delete(SessionRecord).where(SessionRecord.session_id.in_(ids)))
            if character_id:
                db.exec(delete(CharacterRecord).where(CharacterRecord.id == character_id))
        else:
            for current_id in ids:
                state.run_events.delete_session(current_id)
                state.runs.delete_session(current_id)
                state.messages.delete_session(current_id)
                state.sessions.delete_session(current_id)
            if character_id:
                state.characters.delete(character_id)
    for attachment_id in attachments:
        delete_attachment_if_unreferenced({"uri": "local://attachments/" + attachment_id}, state.messages,
            persona_store=state.personas, character_store=state.characters,
            knowledge_store=state.knowledge, run_store=state.runs, qq_store=state.qq.store)
    return ids
