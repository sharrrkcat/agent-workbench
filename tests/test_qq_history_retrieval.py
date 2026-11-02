"""QQ retrieval stays conversation-scoped and never changes confirmed sends."""
import json

from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.db.qq_models import QQBatch
from tests.test_qqbot import qq_client, configure_execution, child
from tests.test_qq_reply_policy import execute_batch
from tests.tool_fixtures import completion, ok, tool_call


def setup(client, state):
    policy = ContextPolicy(strategy='history_retrieval', retrieval={'trigger_percent': 40, 'target_percent': 25, 'max_checkpoint_tokens': 512})
    p, session, connection = configure_execution(client, state, reply_message_limit=1, context_policy=policy.model_dump())
    ok(client.patch(f"/api/models/profiles/{p['model_profile_id']}", json={'context_window_tokens': 16384}))
    return p, session, connection


def test_final_send_drains_checkpoint_and_commits_only_confirmed_history(qq_client):
    client, state, upstream = qq_client
    p, session, connection = setup(client, state)
    def respond(request):
        batch = state.qq.store.active_batch(session['session_id'])
        return completion(tool_call('qq_send_message', {'text': 'Confirmed 47 EUR'}, 'send'),
            tool_call('context_checkpoint_update', {'scope': 'memory', 'text': 'Budget 47 EUR was confirmed.',
                'references': [f'batch:{batch.id}']}, 'memory'),
            tool_call('qq_send_message', {'text': 'Must not be sent'}, 'extra'))
    upstream.turns = [respond]
    batch, run = execute_batch(client, state, p, session, text='bot budget 47 EUR')
    assert run.status == 'DONE', (run.error_code, run.error_message)
    assert len(connection.calls) == 1 and len(upstream.calls) == 1
    saved = state.sessions.get_retrieval_state(session['session_id'])
    assert saved.memory.text == 'Budget 47 EUR was confirmed.' and saved.memory.references == [f'batch:{batch.id}']
    assert run.metadata['qq_reply']['sent_count'] == 1
    assert run.metadata['qq_reply']['limit_reached']
    assert state.runs.get_harness_state(run.run_id) == {}
    other = child(client, p, '8899')
    assert state.sessions.get_retrieval_state(other['session_id']) is None


def test_cross_batch_retrieval_and_source_scope(qq_client):
    client, state, upstream = qq_client
    p, session, connection = setup(client, state)
    upstream.turns = [completion(tool_call('qq_send_message', {'text': 'FIRST_CONFIRMED'}, 'first'), content='PRIVATE_EXECUTION_TEXT')]
    first, run = execute_batch(client, state, p, session, text='bot UNIQUE_INPUT=47')
    assert run.status == 'DONE'
    def inspect(request):
        data = json.loads(request['messages'][-1]['content'])['data']
        assert 'UNIQUE_INPUT=47' in data['text'] and 'FIRST_CONFIRMED' in data['text']
        assert 'PRIVATE_EXECUTION_TEXT' not in data['text']
        return completion(tool_call('qq_send_message', {'text': 'Recovered'}, 'second'))
    upstream.turns = [completion(tool_call('context_read', {'source_id': f'batch:{first.id}'}, 'read')), inspect]
    _, run = execute_batch(client, state, p, session, 2)
    assert run.status == 'DONE', (run.error_code, run.error_message)
    assert len(connection.calls) == 2
    ok(client.delete(f"/api/qq/sessions/{session['session_id']}/messages/{state.qq.store.batch_messages(first.id)[0].id}"))
    assert state.sessions.get_retrieval_state(session['session_id']) is None
