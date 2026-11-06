"""Exercise confirmed facts and isolated recall using an installed model."""

import argparse
import asyncio
import json
from pathlib import Path
import time
from uuid import uuid4

from ai_workbench.api.deps import build_runtime_state
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import ModelProfileStore, ProviderProfileStore, LocalRuntimeSettingsStore
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.schema.character import COGITA_CHARACTER_ID
from ai_workbench.core.schema.persona import Persona
from ai_workbench.core.time import utc_now
from ai_workbench.db.database import get_engine


async def smoke(root, profile_id, model_ref, window):
    engine = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    state = build_runtime_state(root=root, use_memory=True)
    supervisor = state.runtime_supervisor
    supervisor.store = RuntimeStore(engine)
    supervisor.settings = state.local_runtime_settings = LocalRuntimeSettingsStore(engine)
    output = root / 'build/durable-memory-smoke' / utc_now().strftime('%Y%m%d-%H%M%S') / 'report.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'started_at': utc_now().isoformat(), 'success': False, 'cases': []}
    try:
        if profile_id:
            original = ModelProfileStore(engine).get(profile_id)
            if original.source.type == 'provider':
                state.provider_profiles.create(ProviderProfileStore(engine).get(original.source.provider_profile_id))
            profile = original.model_copy(deep=True, update={'id': str(uuid4()), 'alias': 'durable-memory-smoke',
                'parameters': {**original.parameters, 'max_tokens': 1024, 'temperature': 0}, 'context_window_tokens': window})
            if profile.source.type == 'local':
                supervisor.assert_available()
                profile.source.execution_options['context_size'] = window
        else:
            supervisor.assert_available()
            profile = ModelProfile(name='Durable memory acceptance', alias='durable-memory-smoke', kind='llm',
                model_ref=model_ref, parameters={'max_tokens': 1024, 'temperature': 0},
                source={'type': 'local', 'execution_options': {'device': 'cuda', 'context_size': window}})
        profile.request_options.streaming = False
        profile = state.model_profiles.create(profile)
        state.app_settings.patch({'auto_generate_session_titles': False})
        report.update(model_ref=profile.model_ref, source=profile.source.type, window=window)
        def session(**overrides):
            return state.chat_service.create_session(COGITA_CHARACTER_ID, {'overrides': {
                'model_profile_id': profile.id, 'harness_enabled': True, 'reasoning': False,
                'tools_allowed': [], 'memory_learning': 'automatic', **overrides}})

        async def run(name, owner, prompt):
            started = time.monotonic()
            result = await state.chat_runner.run(session_id=owner.session_id, text=prompt)
            steps = state.runs.list_steps(result.run_id)
            calls = [step for step in steps if step.kind == 'model']
            snapshots = []
            for step in calls:
                try:
                    snapshots.append(state.runs.get_context_snapshot(step.step_id))
                except KeyError:
                    pass  # Dispatch can fail before a request snapshot is created.
            run_record = state.runs.get_run(result.run_id)
            wire = json.dumps([{'messages': snapshot.request.messages, 'tools': snapshot.request.tools}
                for snapshot in snapshots], ensure_ascii=False, default=lambda value: value.model_dump(mode='json'))
            model_context_clean = all(marker.lower() not in wire.lower() for marker in (
                '[User-message ID:', 'character', 'persona', 'session=', 'session_id', 'pool',
                'revision', 'source_message_ids', 'pending',
                run_record.character_id, run_record.persona_id, owner.session_id))
            case = {'name': name, 'success': result.success, 'error_code': result.error_code,
                'error': result.error, 'answer': result.data, 'elapsed_seconds': time.monotonic() - started,
                'model_calls': len(calls), 'tools': [step.metadata.get('tool_name') for step in steps if step.kind == 'tool'],
                'memory_outcome': run_record.metadata.get('memory'), 'model_context_clean': model_context_clean,
                'usage': [step.metadata.get('llm') for step in calls],
                'requests': [snapshot.model_dump(mode='json') for snapshot in snapshots if snapshot is not None]}
            report['cases'].append(case)
            print(f"{name}: success={result.success}, calls={len(calls)}, memory={case['memory_outcome']}", flush=True)
            return case

        source = session()
        saved = await run('confirmed_fact', source,
            'Please use memory_write to remember this confirmed preference: I prefer oolong tea. '
            'My tea cupboard label is CEDAR-184. Save this as one fact.')
        entries = state.memory.list().items
        report['saved_count'] = len(entries)
        follow_up = await run('same_conversation_recall', source,
            'Which tea do I prefer? Answer briefly.')
        recalled = await run('sibling_recall', session(memory_learning='manual', harness_enabled=False),
            'Which tea do I prefer, and what is my tea cupboard label? Answer only from confirmed facts, otherwise say unknown.')
        other = state.personas.create(Persona(name='Memory acceptance second user'))
        isolated = await run('other_persona', session(persona_id=other.id, memory_learning='manual', harness_enabled=False),
            'What is my tea cupboard label? Use only facts attributed to me; say unknown if unavailable.')
        before = state.memory.list().total
        await run('unconfirmed_suggestion', source,
            'Suggest another tea I might try. This is only a suggestion request: I have not tried or accepted your recommendation. '
            'Do not treat your suggestion as my preference.')
        report['unconfirmed_count_unchanged'] = state.memory.list().total == before
        isolated_wire = json.dumps(isolated['requests'], ensure_ascii=False)
        report['other_persona_excluded'] = 'CEDAR-184' not in isolated_wire
        report['success'] = (all(case['success'] and case['model_context_clean'] for case in report['cases']) and len(entries) == 1
            and saved['memory_outcome'] == {'status': 'saved', 'count': 1}
            and 'oolong' in str(follow_up['answer']).lower()
            and 'CEDAR-184' in str(recalled['answer']) and 'oolong' in str(recalled['answer']).lower()
            and report['other_persona_excluded'] and report['unconfirmed_count_unchanged'])
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(output, flush=True)
        await state.model_manager.close()
        await supervisor.close()
        engine.dispose()
    if not report['success']:
        raise RuntimeError('Durable memory acceptance failed; inspect the saved report.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    model = parser.add_mutually_exclusive_group(required=True)
    model.add_argument('--profile-id', help='Use a representative saved configuration; provider inference is billable.')
    model.add_argument('--model-ref', help='Existing representative GGUF directory relative to data/models; do not use a 0.8B LLM.')
    parser.add_argument('--window', type=int, default=16384)
    args = parser.parse_args()
    asyncio.run(smoke(args.root.resolve(), args.profile_id, args.model_ref, args.window))
