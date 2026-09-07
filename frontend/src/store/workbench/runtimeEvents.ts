import type { WorkbenchSet, WorkbenchGet } from './state';
import { mergeRuns, mergeSteps, older, terminal, pruneHistoryState } from './mergeState';

import { applyMessageEvent } from '../messageStream';

import type { Run, RunStep, RuntimeEvent } from '../../types/runs';
import type { Session } from '../../types/chat';

export function handleRuntimeEvent(set: WorkbenchSet, get: WorkbenchGet, event: RuntimeEvent): void {
  if (event.type === 'session_updated' && event.payload?.session) {
    const session = event.payload.session as Session;
    set((state) => ({
      currentSession: state.currentSession?.session_id === session.session_id ? session : state.currentSession,
      sessions: state.sessions.map((s) => (s.session_id === session.session_id ? session : s)),
      sessionVersion: state.sessionVersion + 1,
    }));
    return;
  }
  if (event.type === 'model_status' && event.payload?.model_profile_id) {
    return;
  }
  if (event.session_id !== get().currentSession?.session_id) return;
  const payload = event.payload || {};
  if (event.type === 'history_pruned') {
    const messageIds = payload.deleted_message_ids;
    const runIds = payload.deleted_run_ids;
    if (Array.isArray(messageIds) && messageIds.every((id) => typeof id === 'string') &&
        Array.isArray(runIds) && runIds.every((id) => typeof id === 'string')) {
      set((state) => pruneHistoryState(state, { deleted_message_ids: messageIds, deleted_run_ids: runIds }));
    }
    return;
  }
  if (get().deletedMessageIds.includes(event.message_id || '') || get().deletedRunIds.includes(event.run_id || '')) return;
  if (
    ['message_updated', 'message_started', 'message_delta', 'message_completed', 'tool_call_created', 'tool_result_created'].includes(
      event.type,
    )
  ) {
    if (
      event.type === 'message_started' &&
      get().runs.some(
        (r) => r.run_id === event.run_id && ['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(r.status),
      )
    )
      return;
    set((state) => ({ messages: applyMessageEvent(state.messages, event), messageVersion: state.messageVersion + 1 }));
    return;
  }
  if (['run_failed', 'run_cancelled'].includes(event.type)) {
    set((state) => ({
      messages: state.messages.filter((m) => m.run_id !== event.run_id || !m.metadata?.streaming),
      messageVersion: state.messageVersion + 1,
    }));
  }
  if (payload.run) {
    const incoming = payload.run as Run;
    if (incoming.session_id !== event.session_id || get().deletedRunIds.includes(incoming.run_id)) return;
    set((state) => {
      const previous = state.runs.find((run) => run.run_id === incoming.run_id);
      if (
        previous &&
        (older(incoming.updated_at, previous.updated_at) || (terminal(previous.status) && !terminal(incoming.status)))
      )
        return {};
      const session = state.currentSession;
      const currentSession = session
        ? {
            ...session,
            waiting_run_id:
              incoming.status === 'WAITING_FOR_USER'
                ? incoming.run_id
                : session.waiting_run_id === incoming.run_id
                  ? null
                  : session.waiting_run_id,
          }
        : null;
      return {
        runs: mergeRuns(state.runs, [incoming]),
        runVersion: state.runVersion + 1,
        currentSession,
        sessionVersion: state.sessionVersion + 1,
        sessions: currentSession
          ? state.sessions.map((s) => (s.session_id === currentSession.session_id ? currentSession : s))
          : state.sessions,
      };
    });
  }
  if (event.type === 'run_step_updated' || event.type === 'run_step_created') {
    const step = payload.step as RunStep | undefined;
    if (!step || get().deletedRunIds.includes(step.run_id)) return;
    set((state) => ({ stepsByRunId: mergeSteps(state.stepsByRunId, [step]), runVersion: state.runVersion + 1 }));
  }
  if (['run_started', 'run_completed', 'run_failed', 'run_cancelled'].includes(event.type)) void get().refreshCurrent();
}
