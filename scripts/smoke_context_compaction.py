"""Exercise rolling compaction with an installed GGUF and isolated memory records."""
import argparse
import asyncio
import json
from pathlib import Path
import time

from ai_workbench.api.deps import build_runtime_state
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import LocalRuntimeSettingsStore
from ai_workbench.db.database import get_engine


async def smoke(root, model_ref, device, manual=False):
    engine = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    state = build_runtime_state(root=root, use_memory=True)
    supervisor = state.runtime_supervisor
    supervisor.store = RuntimeStore(engine)
    state.local_runtime_settings = supervisor.settings = LocalRuntimeSettingsStore(engine)
    report = {'model_ref': model_ref, 'device': device, 'manual': manual, 'cycles': []}
    output = root / ('build/manual-compaction-smoke/report.json' if manual else 'build/context-compaction-smoke/report.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        supervisor.assert_available()
        report['runtime_version'] = supervisor.release.version
        state.app_settings.patch({'auto_generate_session_titles': False})
        profile = state.model_profiles.create(ModelProfile(name='Compaction acceptance', alias='compaction-smoke',
            kind='llm', model_ref=model_ref, parameters={'temperature': 0, 'max_tokens': 128},
            request_options={'streaming': False}, source={'type': 'local',
                'execution_options': {'device': device, 'context_size': 4096}}))
        session = state.chat_service.create_session({'model_profile_id': profile.id, 'harness_enabled': False,
            'reasoning': False, 'tools_allowed': [], 'context_policy': {'compaction': {
                'enabled': not manual, 'trigger_percent': 25, 'target_percent': 15, 'max_summary_tokens': 512}}})
        report['context_policy'] = session.context_policy.model_dump()
        facts = [
            'The project code is CEDAR. The budget is exactly 42 EUR. Do not send email.',
            'Correction: the budget is now 47 EUR, replacing 42 EUR. The deadline is 2026-12-15.',
            'The owner is Mei. Keep the deadline 2026-12-15 and the prohibition on sending email.',
        ]
        previous_id = None
        for cycle, fact in enumerate(facts[:1] if manual else facts):
            for index in range(6):
                user = state.messages.add_message(session.session_id, 'user', fact + '\n' +
                    f'Planning note {cycle}-{index}. ' + 'We discussed routine scheduling with no additional decisions. ' * 16)
                state.messages.add_message(session.session_id, 'assistant', 'Noted.', parent_message_id=user.message_id)
            started = time.monotonic()
            manual_run = None
            manual_seconds = None
            if manual:
                manual_run = state.runtime.manual_compaction.start(state.sessions.get_session(session.session_id))
                await state.active_runs._tasks[manual_run.run_id]
                manual_run = state.runs.get_run(manual_run.run_id)
                manual_seconds = round(time.monotonic() - started, 2)
                if manual_run.status != 'DONE' or manual_run.metadata['compaction']['status'] != 'compacted':
                    report['cycles'].append({'success': False, 'elapsed_seconds': manual_seconds,
                        'run': manual_run.model_dump(mode='json'),
                        'calls': [s.model_dump(mode='json') for s in state.runs.list_steps(manual_run.run_id)]})
                    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                    raise RuntimeError(f'Manual compaction acceptance failed: {manual_run.error_code}; report: {output}')
            result = await state.chat_runner.run(session_id=session.session_id,
                text='Briefly list the project code, current budget, deadline, owner and the forbidden action. Do not invent missing facts.')
            checkpoint = state.sessions.get_context_checkpoint(session.session_id)
            steps = (state.runs.list_steps(manual_run.run_id) if manual_run else []) + state.runs.list_steps(result.run_id)
            row = {'cycle': cycle + 1, 'success': result.success, 'elapsed_seconds': round(time.monotonic() - started, 2),
                'error_code': result.error_code, 'checkpoint': checkpoint.model_dump(mode='json') if checkpoint else None,
                'calls': [s.model_dump(mode='json') for s in steps if s.kind in {'model', 'compaction'}],
                'answer': [m.model_dump(mode='json') for m in state.messages.messages_for_run(result.run_id)]}
            if manual_run:
                answer_step = next(step for step in steps if step.kind == 'model')
                actual = state.runs.get_context_snapshot(answer_step.step_id)
                row.update(manual_seconds=manual_seconds, manual_run=manual_run.model_dump(mode='json'),
                    summary_used=any(source.kind == 'summary' and source.compaction.checkpoint_id == checkpoint.checkpoint_id
                                     for source in actual.sources))
            report['cycles'].append(row)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'cycle': cycle + 1, 'success': result.success, 'seconds': row['elapsed_seconds'],
                'before': checkpoint.input_tokens_before if checkpoint else None,
                'after': checkpoint.input_tokens_after if checkpoint else None}), flush=True)
            if not result.success or not checkpoint or checkpoint.checkpoint_id == previous_id:
                raise RuntimeError(f'Compaction acceptance failed: {result.error_code}')
            previous_id = checkpoint.checkpoint_id
            if manual:
                assert row['summary_used']
            for step in steps:
                if step.kind in {'model', 'compaction'}:
                    budget = step.metadata['context']['budget']
                    assert budget['input_tokens'] <= budget['input_budget_tokens']
        print(str(output), flush=True)
    finally:
        await state.model_manager.close()
        await supervisor.close()
        engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--model-ref', default='llms/Qwen3.5-0.8B-GGUF')
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    parser.add_argument('--manual', action='store_true', help='Run one manual compaction followed by an ordinary answer.')
    args = parser.parse_args()
    asyncio.run(smoke(args.root.resolve(), args.model_ref, args.device, args.manual))
