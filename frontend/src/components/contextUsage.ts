import type { ModelProfile } from '../types/models';
import type { Run } from '../types/runs';

export function configuredContextWindow(profile: ModelProfile | undefined): number | null {
  if (!profile || profile.kind !== 'llm' || !profile.source) return null;
  return profile.source.type === 'local'
    ? Number(profile.source.execution_options.context_size ?? 4096)
    : profile.context_window_tokens ?? null;
}

export function latestContextUsage(runs: Run[], sessionId: string | undefined, profile: ModelProfile | undefined) {
  if (!sessionId || !profile) return null;
  const ordered = runs.filter((run) => run.session_id === sessionId && run.kind === 'chat')
    .flatMap((run) => (run.steps ?? []).map((step) => ({ run, step })))
    .sort((a, b) => a.run.created_at.localeCompare(b.run.created_at) || a.step.order - b.step.order);
  const latest = ordered.reverse().find(({ step }) => step.kind === 'model'
    && step.status !== 'pending' && step.status !== 'running');
  const budget = latest?.step.metadata?.context?.budget;
  const call = latest?.step.metadata?.llm;
  if (!budget || !call || call.model_profile_id !== profile.id
    || budget.configured_window_tokens !== configuredContextWindow(profile)) return null;
  const input = call.usage?.prompt_tokens ?? null;
  const output = call.usage?.completion_tokens ?? null;
  const used = input === null || output === null ? null : input + output;
  return { budget, used, ratio: used === null ? null : used / budget.window_tokens };
}
