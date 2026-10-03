"""Native counting acceptance using the resident model and ordinary model lease."""
from contextlib import aclosing
import base64
from io import BytesIO

from PIL import Image

from ai_workbench.core.models.context_budget import ChatContextBudget
from ai_workbench.core.models.llm_metrics import LLMCallMetrics
from ai_workbench.core.models.schema import ChatRequest
from ai_workbench.core.schema.context_budget import ContextLimits
from ai_workbench.core.schema.context_snapshot import ContextSource, ContextTrace


async def validate_context_budget(manager, profile):
    output = BytesIO()
    Image.new('RGB', (64, 64), 'red').save(output, format='PNG')
    image = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()}}
    cases = {
        'text': {'messages': [{'role': 'user', 'content': 'Say hello.'}]},
        'image': {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Name the color.'}, image]}]},
        'tools': {'messages': [{'role': 'user', 'content': 'Say hello.'}], 'tools': [
            {'type': 'function', 'function': {'name': 'greet', 'description': 'Greet the user.', 'parameters': {'type': 'object', 'properties': {}}}}]},
        'tool_history': {'messages': [{'role': 'user', 'content': 'Continue from the result.'},
            {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'greet', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'c1', 'content': 'Hello.'}]},
    }
    adapter = manager._slots[manager.execution_key(profile)].adapter
    process = adapter.process
    results = []
    for name, values in cases.items():
        for reasoning in (False, True):
            for streaming in (False, True):
                trace = ContextTrace(sources=[ContextSource(id='current', kind='current_input', message_index=0)])
                budget = ChatContextBudget(ContextLimits(window_tokens=4096, output_tokens=16), trace)
                metrics = LLMCallMetrics()
                request = ChatRequest(model=profile.alias, stream=streaming, reasoning=reasoning, **values)
                if streaming:
                    async with aclosing(manager.chat_stream(profile.id, request, metrics=metrics, budget=budget)) as stream:
                        async for _ in stream:
                            pass
                else:
                    await manager.chat(profile.id, request, metrics=metrics, budget=budget)
                assert metrics.usage and metrics.usage.prompt_tokens == budget.stats.input_tokens, (name, reasoning, streaming, metrics.usage, budget.stats)
                assert budget.stats.input_tokens + budget.stats.output_tokens + budget.stats.margin_tokens <= budget.stats.window_tokens
                assert adapter.process is process and manager.status(profile.id).active == 0
                results.append({'case': name, 'reasoning': reasoning, 'stream': streaming,
                    'input_tokens': budget.stats.input_tokens, 'prompt_tokens': metrics.usage.prompt_tokens,
                    'window_tokens': budget.stats.window_tokens})
    return {'context_budget': 'passed', 'calls': results}
