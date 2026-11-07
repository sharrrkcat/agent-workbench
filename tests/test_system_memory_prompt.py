"""Actual system ordering, summary-only recall and entry-level budget trimming."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_workbench.core.context import add_chat_instructions
from ai_workbench.core.context_snapshot import append_system_block, prepend_system_block
from ai_workbench.core.memory_context import memory_units, remove_memory
from ai_workbench.core.memory_prompt import add_memory_section, replace_memory_index
from ai_workbench.core.models.chat_support import ChatSupport, Support
from ai_workbench.core.models.context_budget import ChatContextBudget
from ai_workbench.core.models.schema import ChatRequest, ModelProfile
from ai_workbench.core.models.token_counting import ReferenceTokenCounter
from ai_workbench.core.schema.context_budget import ContextLimits
from ai_workbench.core.schema.context_snapshot import ContextSource, ContextTrace
from ai_workbench.core.schema.memory import MEMORY_TOOL_NAMES, MemoryContextReference
from tests.test_characters import client_pair, character, child
from tests.test_context_detail import details
from tests.test_durable_memory import add
from tests.model_fixtures import configure_model
from tests.tool_fixtures import completion, ok, tool_call


@pytest.mark.parametrize('strategy', ['token_budget', 'message_window', 'history_retrieval'])
@pytest.mark.parametrize('history_enabled', [True, False])
def test_index_order_pools_and_explicit_body_reads(client_pair, strategy, history_enabled):
    client, upstream, _ = client_pair
    configure_model(client)
    owner = character(client, system_prompt='  Character 😀  ', harness_enabled=True,
        tools_allowed=['web_search'], memory_learning='automatic',
        context_policy={'strategy': strategy, 'history_enabled': history_enabled})
    ok(client.patch(f"/api/personas/{owner['persona_id']}", json={'background': '  Persona 😀  '}))
    own = add(client, owner, owner['persona_id'], summary='Tea preference 😀\n  concise', body='BODY-ONLY-ORCHID-842')
    other = character(client)
    published = add(client, other, owner['persona_id'], summary='General summary', body='GENERAL-BODY-ONLY')
    general = ok(client.post(f"/api/memories/{published['id']}/publish", json={'expected_revision': 1}))
    foreign_persona = ok(client.post('/api/personas', json={'name': 'Another user'}))
    foreign = add(client, owner, foreign_persona['id'], summary='Other user summary', body='OTHER-USER-BODY')
    session = child(client, owner)
    upstream.turns = [completion(tool_call('memory_read', {'ids': [own['id']]}, 'read')),
        completion(content='Read the body.')]
    result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'Read my tea details.'}))
    assert result['success'], result
    snapshots = details(client, result['run'])
    assert len(snapshots) == 2
    for snapshot, request in zip(snapshots, upstream.calls):
        assert snapshot['request'] == request
        system = request['messages'][0]['content']
        sections = ['Current date:', '# CHARACTER\n<character>\nCharacter 😀\n</character>',
            '# USER\n<user_persona>\nPersona 😀\n</user_persona>', '# MEMORY', '<memory_instruction>', '<memory_index>']
        if strategy == 'history_retrieval':
            sections.append('# HISTORY\n<history_instruction>')
        assert [system.index(section) for section in sections] == sorted(system.index(section) for section in sections)
        assert all(system.count(section) == 1 for section in sections)
        assert f"Your own:\n  - {own['id']}: Tea preference 😀 concise\nGeneral:\n  - {general['id']}: General summary" in system
        for absent in (own['body'], general['body'], published['id'], foreign['id'], foreign['summary'], 'Remembered fact'):
            assert absent not in system
        sources = {source['id']: source for source in snapshot['sources']}
        assert sources['memory-instruction']['kind'] == 'memory_instruction'
        assert sources['memory-index']['kind'] == 'memory_index'
        assert sources['memory:' + own['id']]['parent_id'] == 'memory-index'
        assert sources['memory:' + own['id']]['text'] == f"  - {own['id']}: Tea preference 😀 concise"
        for source in snapshot['sources']:
            if source['message_index'] == 0 and source['kind'] != 'system':
                assert system[source['start']:source['end']] == source['text']
            assert source['char_count'] == len(source['text'])
    assert own['body'] not in json.dumps(upstream.calls[0])
    read = next(message for message in upstream.calls[1]['messages'] if message.get('tool_call_id') == 'read')
    assert json.loads(read['content'])['data']['items'][0]['body'] == own['body']


@pytest.mark.parametrize('enabled,harness,learning,populated', [
    (True, True, 'automatic', False), (True, True, 'manual', True),
    (True, False, 'automatic', True), (False, True, 'automatic', True),
])
def test_memory_switches_preserve_the_index_shell(client_pair, monkeypatch, enabled, harness, learning, populated):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, system_prompt=' \n ', harness_enabled=harness, tools_allowed=[],
        memory_enabled=enabled, memory_learning=learning)
    entry = add(client, owner, owner['persona_id'], summary='A concise summary', body='BODY-ONLY') if populated else None
    if not enabled:
        def forbidden_query(*args, **kwargs):
            pytest.fail('Disabled memory must not query entries')
        monkeypatch.setattr(state.memory.store, 'query', forbidden_query)
    session = child(client, owner)
    result = ok(client.post(f"/api/sessions/{session['session_id']}/messages", json={'content': 'Hello'}))
    assert result['success'], result
    request = upstream.calls[-1]
    system = request['messages'][0]['content']
    assert system.startswith('# MEMORY\n') and system.count('<memory_index>') == 1
    assert '<character>' not in system and '<user_persona>' not in system
    assert ('<memory_instruction>' in system) == (enabled and harness and learning == 'automatic')
    assert bool(request.get('tools')) == (enabled and harness and learning == 'automatic')
    if not enabled:
        assert 'Memory is disabled.' in system and entry['id'] not in system
    elif entry:
        assert f"{entry['id']}: A concise summary" in system and entry['body'] not in system
    else:
        assert 'Memory index is empty.' in system
    assert 'General:\n  (empty)' in system
    assert [message['role'] for message in request['messages']] == ['system', 'user']


def test_unsupported_tools_omit_memory_instructions_but_keep_index(client_pair, monkeypatch):
    client, upstream, state = client_pair
    configure_model(client)
    owner = character(client, harness_enabled=True, tools_allowed=[], memory_learning='automatic')
    entry = add(client, owner, owner['persona_id'], summary='Usable summary', body='BODY-ONLY')
    @asynccontextmanager
    async def unsupported(*args, **kwargs):
        yield ChatSupport(tools=Support('unsupported'))
    monkeypatch.setattr(state.model_manager, 'check_chat_inputs', unsupported)
    result = ok(client.post(f"/api/sessions/{child(client, owner)['session_id']}/messages", json={'content': 'Hello'}))
    assert result['success'], result
    request = upstream.calls[-1]
    assert not request.get('tools')
    assert '<memory_instruction>' not in request['messages'][0]['content']
    assert entry['summary'] in request['messages'][0]['content']


def index_request():
    config = SimpleNamespace(system_prompt='Character 😀', character_id='owner', persona_background='Persona 中文',
        persona_id='user', session_kind='normal', memory_enabled=True)
    trace = ContextTrace(sources=[ContextSource(id='current', kind='current_input', message_index=0, role='user')])
    messages, _ = add_chat_instructions(config, [{'role': 'user', 'content': 'Current input'}], trace)
    messages = add_memory_section(config, messages, trace, MEMORY_TOOL_NAMES)
    messages, history = append_system_block(messages, trace, '# HISTORY\n<history_instruction>History</history_instruction>', 'instruction')
    history.id = 'history-instruction'
    messages, _ = prepend_system_block(messages, trace, 'Current date: today.', 'instruction')
    entries = [ContextSource(id='memory:' + memory_id, kind='durable_memory', role='system', reference_id=memory_id,
        name='Summary 中文😀 ' + memory_id, memory=MemoryContextReference(id=memory_id, revision=1,
            character_id='owner', persona_id='user', session_id=None, pool=pool, reason=reason))
        for memory_id, pool, reason in [('id-pin', 'general', 'pinned'), ('id-match', 'character', 'literal'),
            ('id-recent', 'character', 'recent')]]
    messages[0]['content'] = replace_memory_index(messages[0]['content'], trace, entries)
    messages.extend([{'role': 'assistant', 'content': '<think>kept reasoning</think>', 'tool_calls': [
        tool_call('memory_read', {'ids': ['id-match']}, 'read'), tool_call('lookup', {}, 'business')]},
        {'role': 'tool', 'tool_call_id': 'read', 'content': 'MEMORY BODY'},
        {'role': 'tool', 'tool_call_id': 'business', 'content': 'BUSINESS RESULT'}])
    trace.sources.extend([ContextSource(id='read-result', kind='durable_memory', role='tool', message_index=3),
        ContextSource(id='business-result', kind='tool_result', role='tool', message_index=4)])
    return ChatRequest(model='local', messages=messages), trace


@pytest.mark.parametrize('base_tokens,retained', [(200, ['id-pin']), (380, [])])
def test_native_budget_trims_entries_by_priority_preserving_system_and_mixed_calls(base_tokens, retained):
    request, trace = index_request()
    original_request, original_trace = request.model_dump(), trace.model_dump()
    async def count(payload):
        system = payload['messages'][0]['content']
        return base_tokens + 20 * sum(f'  - {key}:' in system for key in ('id-pin', 'id-match', 'id-recent')) + 100 * sum(
            message.get('tool_call_id') == 'read' for message in payload['messages'])
    adapter = SimpleNamespace(context_window=AsyncMock(return_value=512), count_input_tokens=count)
    profile = ModelProfile(name='local', alias='local', kind='llm', model_ref='llms/local', source={'type': 'local'})
    budget = ChatContextBudget(ContextLimits(window_tokens=512, output_tokens=100), trace)
    actual = asyncio.run(budget.prepare(profile, request, adapter, ReferenceTokenCounter()))
    system = actual.messages[0].content
    assert [source.reference_id for source in budget.trace.sources if source.memory] == retained
    assert 'Memory index is limited' in system and 'Memory index is empty.' not in system
    assert '# CHARACTER\n<character>\nCharacter 😀\n</character>' in system
    assert '# USER\n<user_persona>\nPersona 中文\n</user_persona>' in system
    assert '# MEMORY\n<memory_instruction>' in system and system.count('</memory_index>') == 1
    assert system.endswith('# HISTORY\n<history_instruction>History</history_instruction>')
    assert [call.id for call in actual.messages[2].tool_calls] == ['business']
    assert actual.messages[2].content == '<think>kept reasoning</think>'
    assert actual.messages[3].content == 'BUSINESS RESULT'
    assert not any(message.tool_call_id == 'read' for message in actual.messages)
    before = {source.id: source for source in trace.sources}
    for source in budget.trace.sources:
        if source.message_index == 0 and source.kind not in {'system', 'memory_index', 'durable_memory'}:
            old = before[source.id]
            assert system[source.start:source.end] == request.messages[0].content[old.start:old.end]
    assert next(source.message_index for source in budget.trace.sources if source.id == 'business-result') == 3
    assert request.model_dump() == original_request and trace.model_dump() == original_trace
    assert budget.stats.input_tokens <= budget.stats.input_budget_tokens


def test_removing_one_index_entry_keeps_tool_pairs_and_other_pool_entries():
    request, trace = index_request()
    facts, _ = memory_units(request, trace)
    actual, provenance = remove_memory(request, trace, [facts[0]])
    assert actual.messages[1:] == request.messages[1:]
    assert 'General:\n  (empty)' in actual.messages[0].content
    assert [source.reference_id for source in provenance.sources if source.memory] == ['id-match', 'id-recent']
    for source in provenance.sources:
        if source.memory:
            assert actual.messages[0].content[source.start:source.end] == f'  - {source.reference_id}: {source.name}'
