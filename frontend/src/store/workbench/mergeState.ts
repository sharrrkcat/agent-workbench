import type { WorkbenchState } from './state';

import { ApiError } from '../../api/http';

import type { Message } from '../../types/messages';
import type { HistoryPruned, Run, RunStep, RuntimeResponse } from '../../types/runs';

import type { ToolRunResponse } from '../../types/tools';

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  return error instanceof Error ? error.message : String(error || 'Request failed');
}

export function mergeMessages(existing: Message[], incoming: Message[]): Message[] {
  const byId = new Map(existing.map((item) => [item.message_id, item]));
  for (const item of incoming) {
    const previous = byId.get(item.message_id);
    if (previous && item.metadata?.streaming && (!previous.metadata?.streaming || Number(previous.metadata.stream_seq || 0) > Number(item.metadata.stream_seq || 0))) continue;
    byId.set(item.message_id, item);
  }
  return [...byId.values()].sort((a, b) => compareTime(a.created_at, b.created_at));
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
  return [...byId.values()].sort((a, b) => compareTime(a.created_at, b.created_at));
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

export function compareTime(a: string, b: string): number {
  return older(a, b) ? -1 : older(b, a) ? 1 : 0;
}

export function retainedMessages(state: WorkbenchState, messages: Message[]): Message[] {
  const messageIds = new Set(state.deletedMessageIds);
  const runIds = new Set(state.deletedRunIds);
  return messages.filter((message) => !messageIds.has(message.message_id) && !runIds.has(message.run_id || ''));
}

export function pruneHistoryState(state: WorkbenchState, change: HistoryPruned): Partial<WorkbenchState> {
  const deletedMessageIds = [...new Set([...state.deletedMessageIds, ...change.deleted_message_ids])];
  const deletedRunIds = [...new Set([...state.deletedRunIds, ...change.deleted_run_ids])];
  const next = { ...state, deletedMessageIds, deletedRunIds };
  return {
    deletedMessageIds, deletedRunIds,
    messages: retainedMessages(next, state.messages),
    runs: state.runs.filter((run) => !deletedRunIds.includes(run.run_id)),
    stepsByRunId: Object.fromEntries(Object.entries(state.stepsByRunId).filter(([id]) => !deletedRunIds.includes(id))),
    sourceMessageId: deletedMessageIds.includes(state.sourceMessageId || '') ? null : state.sourceMessageId,
    resolvingApprovals: state.resolvingApprovals.filter((id) => !deletedRunIds.includes(id)),
    messageVersion: state.messageVersion + 1,
    runVersion: state.runVersion + 1,
    sessionVersion: state.sessionVersion + 1,
  };
}

export function runtimeResponseState(state: WorkbenchState, response: RuntimeResponse): Partial<WorkbenchState> {
  if (response.session?.session_id !== state.currentSession?.session_id) return {};
  const pruned = response.deleted_message_ids && response.deleted_run_ids
    ? pruneHistoryState(state, { deleted_message_ids: response.deleted_message_ids, deleted_run_ids: response.deleted_run_ids }) : {};
  const next = { ...state, ...pruned };
  if (response.run && response.session) {
    return { ...pruned, ...toolResponseState(next, { run: response.run, session: response.session, messages: response.messages || [] }) };
  }
  return { ...pruned, messages: mergeMessages(next.messages, retainedMessages(next, response.messages || [])), messageVersion: next.messageVersion + 1 };
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
  if (state.currentSession?.session_id !== response.run.session_id || state.deletedRunIds.includes(response.run.run_id)) return {};
  const previous = state.runs.find((run) => run.run_id === response.run.run_id);
  const acceptSession = !previous || !older(response.run.updated_at, previous.updated_at);
  return {
    runs: mergeRuns(state.runs, [response.run]),
    stepsByRunId: mergeSteps(state.stepsByRunId, response.run.steps || []),
    messages: mergeMessages(
      state.messages,
      retainedMessages(state, response.messages.filter((m) => m.session_id === response.run.session_id)),
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
    runVersion: state.runVersion + 1,
    sessionVersion: state.sessionVersion + 1,
  };
}
