import type { WorkbenchState } from './state';

import { ApiError } from '../../api/http';

import type { Message } from '../../types/messages';
import type { Run, RunStep } from '../../types/runs';

import type { ToolRunResponse } from '../../types/tools';

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  return error instanceof Error ? error.message : String(error || 'Request failed');
}

export function mergeMessages(existing: Message[], incoming: Message[]): Message[] {
  const byId = new Map(existing.map((item) => [item.message_id, item]));
  for (const item of incoming) byId.set(item.message_id, item);
  return [...byId.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
}

export function mergeRuns(existing: Run[], incoming: Run[]): Run[] {
  const byId = new Map(existing.map((item) => [item.run_id, item]));
  for (const item of incoming) {
    const previous = byId.get(item.run_id);
    if (
      previous &&
      (older(item.updated_at, previous.updated_at) || (terminal(previous.status) && !terminal(item.status)))
    )
      continue;
    byId.set(item.run_id, { ...item, steps: item.steps || previous?.steps });
  }
  return [...byId.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
}

export function terminal(status: Run['status']): boolean {
  return ['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(status);
}

export function older(incoming: string, current: string): boolean {
  const delta = Date.parse(incoming) - Date.parse(current);
  if (delta !== 0) return delta < 0;
  // Server timestamps have microseconds; Date.parse alone loses their order.
  const fraction = (value: string) => (value.match(/\.(\d+)/)?.[1] || '').padEnd(9, '0');
  return fraction(incoming) < fraction(current);
}

export function mergeSteps(existing: Record<string, RunStep[]>, steps: RunStep[]): Record<string, RunStep[]> {
  const result = { ...existing };
  for (const step of steps) {
    const rows = result[step.run_id] || [];
    const previous = rows.find((item) => item.step_id === step.step_id);
    if (
      previous &&
      (older(step.updated_at, previous.updated_at) ||
        (['completed', 'failed', 'skipped'].includes(previous.status) && ['pending', 'running'].includes(step.status)))
    )
      continue;
    result[step.run_id] = [...rows.filter((item) => item.step_id !== step.step_id), step].sort(
      (a, b) => a.order - b.order,
    );
  }
  return result;
}

export function toolResponseState(state: WorkbenchState, response: ToolRunResponse): Partial<WorkbenchState> {
  if (state.currentSession?.session_id !== response.run.session_id) return {};
  const previous = state.runs.find((run) => run.run_id === response.run.run_id);
  const acceptSession = !previous || !older(response.run.updated_at, previous.updated_at);
  return {
    runs: mergeRuns(state.runs, [response.run]),
    stepsByRunId: mergeSteps(state.stepsByRunId, response.run.steps || []),
    messages: mergeMessages(
      state.messages,
      response.messages.filter((m) => m.session_id === response.run.session_id),
    ),
    currentSession:
      acceptSession && !older(response.session.updated_at, state.currentSession.updated_at)
        ? response.session
        : state.currentSession,
    sessions: acceptSession
      ? state.sessions.map((s) =>
          s.session_id === response.session.session_id && !older(response.session.updated_at, s.updated_at)
            ? response.session
            : s,
        )
      : state.sessions,
    messageVersion: state.messageVersion + 1,
    sessionVersion: state.sessionVersion + 1,
  };
}
