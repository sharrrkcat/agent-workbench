"""Run real tool-driven retrieval acceptance in isolated in-memory conversations."""
import argparse
import asyncio
import json
from pathlib import Path
import time
from uuid import uuid4

from ai_workbench.api.deps import build_runtime_state
from ai_workbench.core.schema.character import COGITA_CHARACTER_ID
from ai_workbench.core.harness.schema import ToolSpec
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import ModelProfileStore, ProviderProfileStore, LocalRuntimeSettingsStore
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.time import utc_now
from ai_workbench.db.database import get_engine


async def smoke(root, profile_id, model_ref, device, window):
    engine = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    state = build_runtime_state(root=root, use_memory=True)
    supervisor = state.runtime_supervisor
    supervisor.store = RuntimeStore(engine)
    state.local_runtime_settings = supervisor.settings = LocalRuntimeSettingsStore(engine)
    report = {'started_at': utc_now().isoformat(), 'window': window, 'success': False}
    output = root / 'build/history-retrieval-smoke' / utc_now().strftime('%Y%m%d-%H%M%S') / 'report.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if profile_id:
            original = ModelProfileStore(engine).get(profile_id)
            if original.source.type == 'provider':
                state.provider_profiles.create(ProviderProfileStore(engine).get(original.source.provider_profile_id))
            profile = original.model_copy(update={'id': str(uuid4()), 'alias': 'history-retrieval-smoke',
                'parameters': {**original.parameters, 'max_tokens': 1024, 'temperature': 0}, 'context_window_tokens': window})
            if original.source.type == 'local':
                supervisor.assert_available()
                profile.source.execution_options['context_size'] = window
        else:
            supervisor.assert_available()
            profile = ModelProfile(name='History retrieval acceptance', alias='history-retrieval-smoke', kind='llm',
                model_ref=model_ref, parameters={'max_tokens': 1024, 'temperature': 0},
                source={'type': 'local', 'execution_options': {'device': device, 'context_size': window}})
        profile.request_options.streaming = False
        profile = state.model_profiles.create(profile)
        state.app_settings.patch({'auto_generate_session_titles': False})
        report.update(model_ref=profile.model_ref, source=profile.source.type)
        facts = ['Character code: CEDAR-184.', 'Corrected budget: 47 EUR, replacing 42 EUR.',
                 'Deadline: 2026-12-15.', 'Owner: Mei-Quinn.']
        probes = []
        async def probe(arguments, context):
            index = arguments['index']
            probes.append(index)
            print(f'probe {index}', flush=True)
            return {'fact': facts[index - 1], 'background': 'background detail ' * 1250}
        state.tool_registry.register(ToolSpec('acceptance_probe', 'Read one numbered acceptance fact. Call once per model response, in order 1 through 4.',
            {'type': 'object', 'properties': {'index': {'type': 'integer', 'minimum': 1, 'maximum': 4}},
             'required': ['index'], 'additionalProperties': False}, probe))
        session = state.chat_service.create_session(COGITA_CHARACTER_ID, {'overrides': {'model_profile_id': profile.id, 'harness_enabled': True,
            'reasoning': False, 'tools_allowed': ['acceptance_probe'], 'context_policy': {'strategy': 'history_retrieval',
                'retrieval': {'trigger_percent': 65, 'target_percent': 40, 'max_checkpoint_tokens': 512}}}})
        prompt = ('Complete this acceptance task using the tools. Do not send email. First save a brief progress checkpoint. '
            'Call acceptance_probe for indexes 1, 2, 3 and 4, exactly once each and only one probe per response. '
            'Context may reset; use the checkpoints and the original records to continue without repeating probes. '
            'After all four probes, use context_list(scope=run) and context_read to read the original FIRST probe result. '
            'Update conversation memory with the verified facts and original source IDs, then answer with the character code, '
            'corrected budget, deadline, owner, and the email restriction. Keep checkpoint bodies below 300 tokens.')
        reset_times = []
        first_reset_at = None
        prepare = state.chat_runner.retrieval.prepare_loop
        async def measure_reset(*args, **kwargs):
            nonlocal first_reset_at
            previous = args[-1].retrieval.session.window_id
            started = time.monotonic()
            value = await prepare(*args, **kwargs)
            if args[-1].retrieval.session.window_id != previous:
                reset_times.append((time.monotonic() - started) * 1000)
                first_reset_at = first_reset_at or time.monotonic()
            return value
        state.chat_runner.retrieval.prepare_loop = measure_reset
        start = time.monotonic()
        result = await state.chat_runner.run(session_id=session.session_id, text=prompt)
        report['elapsed_seconds'] = time.monotonic() - start
        report['reset_elapsed_ms'] = reset_times
        report['recovery_elapsed_seconds'] = time.monotonic() - first_reset_at if first_reset_at is not None else None
        steps = state.runs.list_steps(result.run_id)
        resets = [step for step in steps if step.metadata.get('operation') == 'reset']
        calls = [step for step in steps if step.kind == 'model']
        tools = [step.metadata.get('tool_name') for step in steps if step.kind == 'tool']
        memory = state.sessions.get_retrieval_state(session.session_id)
        answer = result.data if isinstance(result.data, str) else ''
        report.update(run_status=state.runs.get_run(result.run_id).status, error_code=result.error_code,
            error_message=result.error,
            probes=probes, resets=[step.metadata['reset'] for step in resets], model_calls=len(calls), tool_names=tools,
            answer=answer, memory_committed=bool(memory and memory.memory.text),
            usage=[step.metadata.get('llm') for step in calls],
            fact_presence={value: value in answer for value in ['CEDAR-184', '47', '2026-12-15', 'Mei-Quinn']})
        report['tool_results'] = [row.model_dump(mode='json') for row in state.messages.messages_for_run(result.run_id) if row.role == 'tool']
        report['requests'] = [state.runs.get_context_snapshot(step.step_id).model_dump(mode='json') for step in calls
            if state.runs.get_context_snapshot(step.step_id) is not None]
        report['token_cost'] = {key: sum(((item or {}).get('usage') or {}).get(key, 0) or 0 for item in report['usage'])
            for key in ['prompt_tokens', 'completion_tokens', 'total_tokens']}
        first_probe = next((row for row in report['tool_results'] if row['metadata'].get('tool') == 'acceptance_probe'), None)
        read_calls = [call for snapshot in report['requests'] for message in snapshot['request']['messages']
            for call in message.get('tool_calls') or [] if call['function']['name'] == 'context_read']
        report['read_first_probe'] = bool(first_probe and any(json.loads(call['function']['arguments']).get('source_id') in {
            'message:' + first_probe['message_id'], 'call:' + first_probe['metadata']['tool_call_id']} for call in read_calls))
        report['success'] = (result.success and probes == [1, 2, 3, 4] and len(resets) >= 3
            and report['read_first_probe'] and 'context_checkpoint_update' in tools and report['memory_committed']
            and all(report['fact_presence'].values()) and not any(step.kind == 'compaction' for step in steps))
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(str(output), flush=True)
        await state.model_manager.close()
        await supervisor.close()
        engine.dispose()
    if not report['success']:
        raise RuntimeError('Real-model history retrieval acceptance failed; inspect the saved report.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--profile-id', help='Reuse a saved model/provider configuration without changing it; inference is billable for providers.')
    parser.add_argument('--model-ref', default='llms/Qwen3.5-0.8B-GGUF')
    parser.add_argument('--device', choices=['cuda', 'cpu'], default='cuda')
    parser.add_argument('--window', type=int, default=8192)
    args = parser.parse_args()
    asyncio.run(smoke(args.root.resolve(), args.profile_id, args.model_ref, args.device, args.window))
