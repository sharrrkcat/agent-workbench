import type { LLMCallSnapshot } from '../../types/llmMetrics';
import type { Reply } from './turns';
import { terminal } from '../../store/cogita/mergeState';

export function buildReplyMetrics(reply: Reply, now = Date.now()) {
  if (reply.run.kind !== 'chat') return null;
  const steps = reply.steps.filter((step) => step.kind === 'model').sort((a, b) => a.order - b.order);
  const calls = steps.flatMap((step) => step.metadata?.llm ? [step.metadata.llm] : []);
  if (!calls.length) return null;

  const sum = (read: (call: LLMCallSnapshot) => number | null | undefined) => {
    const values = calls.map(read).filter((value): value is number => value != null);
    return values.length ? values.reduce((total, value) => total + value, 0) : null;
  };
  const complete = ['DONE', 'WAITING_FOR_USER'].includes(reply.run.status) && steps.every((step) => {
    const call = step.metadata?.llm;
    return step.status === 'completed' && call?.completed && call.usage?.prompt_tokens != null &&
      call.usage.completion_tokens != null && call.usage.total_tokens != null;
  });
  const speedKnown = complete && calls.every(({ timing }) => timing.generation_tokens != null &&
    timing.generation_ms != null && timing.generation_ms > 0 && timing.tps_source != null);
  const firstResponses = calls.flatMap((call) => call.first_response_at ? [Date.parse(call.first_response_at)] : []);
  const start = Date.parse(reply.run.started_at || reply.run.created_at);
  const end = terminal(reply.run.status) ? Date.parse(reply.run.finished_at || reply.run.updated_at) : now;
  return {
    steps, complete,
    inputTokens: sum((call) => call.usage?.prompt_tokens),
    outputTokens: sum((call) => call.usage?.completion_tokens),
    firstResponseMs: firstResponses.length ? Math.max(0, Math.min(...firstResponses) - start) : null,
    totalMs: Math.max(0, end - start),
    tokensPerSecond: speedKnown ? sum((call) => call.timing.generation_tokens)! * 1000 /
      sum((call) => call.timing.generation_ms)! : null,
    estimated: speedKnown && calls.some((call) => call.timing.tps_source === 'estimated'),
  };
}
