"""Exercise rolling compaction with an installed GGUF and isolated memory records."""
import argparse
import asyncio
import json
import re
from pathlib import Path
import time

from ai_workbench.api.deps import build_runtime_state
from ai_workbench.core.schema.character import COGITA_CHARACTER_ID
from ai_workbench.core.models.runtimes.store import RuntimeStore
from ai_workbench.core.models.schema import ModelProfile
from ai_workbench.core.models.store import LocalRuntimeSettingsStore
from ai_workbench.db.database import get_engine


async def smoke(root, model_ref, device, manual=False, harness=False):
    engine = get_engine(f"sqlite:///{root / 'data/cogita.db'}")
    state = build_runtime_state(root=root, use_memory=True)
    supervisor = state.runtime_supervisor
    supervisor.store = RuntimeStore(engine)
    state.local_runtime_settings = supervisor.settings = LocalRuntimeSettingsStore(engine)
    report = {'model_ref': model_ref, 'device': device, 'manual': manual, 'harness': harness, 'cycles': []}
    folder = 'harness-compaction-smoke' if harness else 'manual-compaction-smoke' if manual else 'context-compaction-smoke'
    output = root / f'build/{folder}/report.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        supervisor.assert_available()
        report['runtime_version'] = supervisor.release.version
        state.app_settings.patch({'auto_generate_session_titles': False})
        profile = state.model_profiles.create(ModelProfile(name='Compaction acceptance', alias='compaction-smoke',
            kind='llm', model_ref=model_ref, parameters={'temperature': 0, 'max_tokens': 128},
            request_options={'streaming': False}, source={'type': 'local',
                'execution_options': {'device': device, 'context_size': 4096}}))
        if harness:
            try:
                await asyncio.wait_for(smoke_harness(state, profile, report, output), timeout=300)
            except (Exception, asyncio.CancelledError) as exc:
                report['error'] = type(exc).__name__ + ': ' + str(exc)
                if report.get('run_id'):
                    report['calls'] = [step.model_dump(mode='json') for step in state.runs.list_steps(report['run_id'])]
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                raise
            return
        session = state.chat_service.create_session(COGITA_CHARACTER_ID, {'overrides': {'model_profile_id': profile.id, 'harness_enabled': False,
            'reasoning': False, 'tools_allowed': [], 'context_policy': {'compaction': {
                'enabled': not manual, 'trigger_percent': 25, 'target_percent': 15, 'max_summary_tokens': 512}}}})
        report['context_policy'] = state.chat_service.resolve(session).context_policy.model_dump()
        facts = [
            'The character code is CEDAR. The budget is exactly 42 EUR. Do not send email.',
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
                text='Briefly list the character code, current budget, deadline, owner and the forbidden action. Do not invent missing facts.')
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


async def smoke_harness(state, profile, report, output):
    """Use scripted completed tools, real summary generation and a real final answer."""
    from ai_workbench.core.context_snapshot import capture_context
    from ai_workbench.core.harness.schema import HarnessState
    from ai_workbench.core.models.chat_support import chat_reasoning_mode
    from ai_workbench.core.models.context_budget import ChatContextBudget
    from ai_workbench.core.models.llm_metrics import LLMCallMetrics
    from ai_workbench.core.models.schema import ChatRequest

    session = state.chat_service.create_session(COGITA_CHARACTER_ID, {'overrides': {'model_profile_id': profile.id, 'harness_enabled': False,
        'reasoning': False, 'tools_allowed': [], 'context_policy': {'history_enabled': False, 'compaction': {
            'trigger_percent': 25, 'target_percent': 15, 'max_summary_tokens': 512}}}})
    config = state.chat_service.resolve(session)
    question = 'List the character code, current budget, deadline, owner and forbidden action from completed tool results. Keep exact values.'
    user = state.messages.add_message(session.session_id, 'user', question)
    context, _, trace = await state.chat_runner._build_context(session, config, question, user.message_id, [])
    run = state.runs.create_run('chat', config.character_id, config.persona_id, session.session_id, metadata={'input_message_id': user.message_id},
        config_snapshot=config.model_dump(mode='json'))
    state.runs.update_status(run.run_id, 'RUNNING')
    facts = [
        'The character code is CEDAR. The budget is exactly 42 EUR. Do not send email.',
        'Confirmed correction: the current budget is 47 EUR, replacing 42 EUR. The deadline is 2026-12-15.',
        'The owner is Mei. Keep the deadline 2026-12-15 and the prohibition on sending email.',
        'All facts have been collected. Report the confirmed character information without inventing other decisions.',
    ]
    report.update(run_id=run.run_id, scripted_tool_rounds=True, context_policy=state.chat_service.resolve(session).context_policy.model_dump())
    async with state.model_manager.check_chat_inputs(profile, tools=True, vision=False, reasoning=False) as support:
        continuation = HarnessState(base_messages=context, context_trace=trace,
            reasoning=chat_reasoning_mode(profile, support, False), summary_reasoning=chat_reasoning_mode(profile, support, False))
        base = ChatRequest(model=profile.alias, messages=context, reasoning=continuation.reasoning, tools=[{'type': 'function',
            'function': {'name': 'acceptance_result', 'description': 'Return a recorded character fact.',
                'parameters': {'type': 'object', 'properties': {'index': {'type': 'integer'}}, 'required': ['index']}}}])
        for number, fact in enumerate(facts):
            continuation.transcript.extend([
                {'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'fact_{number}', 'type': 'function',
                    'function': {'name': 'acceptance_result', 'arguments': json.dumps({'index': number})}}]},
                {'role': 'tool', 'tool_call_id': f'fact_{number}', 'content': json.dumps({'status': 'success',
                    'content': fact + '\nUninformative padding: ' + 'x ' * 1300})},
            ])
            continuation.rounds += 1
            state.runs.update_harness_state(run.run_id, continuation.model_dump(mode='json'))
            started = time.monotonic()
            request, actual_trace, warning = await state.chat_runner.harness_loop.compaction.prepare(base=base,
                trace=trace, config=config, profile=profile, run=run, state=continuation)
            steps = state.runs.list_steps(run.run_id)
            report['cycles'].append({'round': number + 1, 'seconds': round(time.monotonic() - started, 2),
                'warning': warning, 'summary': continuation.compaction.model_dump() if continuation.compaction else None,
                'calls': [step.model_dump(mode='json') for step in steps if step.kind == 'compaction']})
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'round': number + 1, 'seconds': report['cycles'][-1]['seconds'],
                'summary_through_round': continuation.compaction.through_round if continuation.compaction else None,
                'summary_calls': len(steps), 'warning': warning}), flush=True)
        step = state.runs.create_step(run.run_id, 'model', status='running', label='Final acceptance answer')
        metrics = LLMCallMetrics()
        budget = ChatContextBudget(config.context_limits, actual_trace)
        capture = capture_context(state.runs, step.step_id, budget.trace, profile, config.context_policy, budget=budget)
        response = await state.model_manager.chat(profile.id, request.model_copy(update={'tool_choice': 'none'}),
            metrics=metrics, budget=budget, capture=capture)
        answer = response.message.content if isinstance(response.message.content, str) else ''
        message = state.messages.add_message(session.session_id, 'assistant', answer, run_id=run.run_id, parent_message_id=user.message_id)
        state.runs.update_step(step.step_id, status='completed', metadata={'llm': metrics.snapshot(profile.id, profile.alias, message.message_id).model_dump(mode='json')})
        committed = [item for item in state.runs.list_steps(run.run_id) if item.metadata.get('run_compaction')]
        report.update(answer=answer, finish_reason=response.finish_reason, committed_summaries=len(committed),
            final_budget=budget.stats.model_dump(), fact_presence={value: value in answer for value in ['CEDAR', '47', '2026-12-15', 'Mei']},
            email_prohibition=bool(re.search(r"(do not|don't|no|never|must not|forbidden|prohibited).{0,45}(email|e-mail)", answer, re.I)))
        report['success'] = len(committed) == 3 and all(report['fact_presence'].values()) and report['email_prohibition'] and response.finish_reason == 'stop'
        state.runs.update_status(run.run_id, 'DONE' if report['success'] else 'FAILED')
        state.runs.update_harness_state(run.run_id, {})
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(str(output), flush=True)
        if not report['success']:
            raise RuntimeError('Repeated Harness compaction or factual-retention acceptance failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--model-ref', required=True, help='Existing representative GGUF directory; do not use a 0.8B LLM.')
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--manual', action='store_true', help='Run one manual compaction followed by an ordinary answer.')
    mode.add_argument('--harness', action='store_true', help='Compact scripted tool rounds and generate a final answer within 300 seconds.')
    args = parser.parse_args()
    asyncio.run(smoke(args.root.resolve(), args.model_ref, args.device, args.manual, args.harness))
