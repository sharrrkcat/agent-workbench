import type { CogitaState } from './state';
import { terminal } from './mergeState';

export function compactCommand(text: string): 'none' | 'prefix' | 'compact' | 'invalid' {
  const value = text.trim();
  if (value === '/compact') return 'compact';
  if (/^\/compact\s/.test(value)) return 'invalid';
  return value.startsWith('/') && '/compact'.startsWith(value) ? 'prefix' : 'none';
}

export function compactUnavailable(state: CogitaState): string | null {
  const session = state.currentSession;
  if (!session) return 'draft';
  if (state.sessionLoad && state.sessionLoad.status !== 'ready' || state.historyLoading) return 'loading';
  if (state.sending || state.awaitingAcceptance || state.mutatingHistory || session.waiting_run_id ||
      state.runs.some((run) => run.session_id === session.session_id && !terminal(run.status))) return 'busy';
  const queue = state.messageQueues[session.session_id];
  if (queue?.items.length || queue?.editing || queue?.submission) return 'queued';
  if (state.savingSessionIds.includes(session.session_id)) return 'saving';
  const policy = session.effective.context_policy;
  if (!('history_enabled' in policy) || !policy.history_enabled || policy.strategy !== 'token_budget') return 'policy';
  if (!session.effective.model_profile_id) return 'model';
  return null;
}
