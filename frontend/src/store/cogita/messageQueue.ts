import type { Attachment, Message } from '../../types/messages';
import type { Run } from '../../types/runs';
import { compareTime, older, terminal } from './mergeState';

export type ComposerAttachment = Attachment & {
  status: 'uploading' | 'ready' | 'error';
  attachment?: Attachment;
  preview?: string | null;
  error?: string;
};

export type QueuedMessage = { id: string; content: string; attachments: Attachment[] };
export type QueueRun = Pick<Run, 'run_id' | 'status' | 'created_at' | 'updated_at'>;
export type MessageQueue = {
  projectId: string | null;
  items: QueuedMessage[];
  editing: { id: string; content: string; attachments: ComposerAttachment[] } | null;
  paused: 'stopped' | 'failed' | 'submission' | 'unconfirmed' | null;
  submission: { clientId: string; itemId?: string; accepted: boolean; pending: boolean; boundary?: string } | null;
  run: QueueRun | null;
};

export const queueRun = ({ run_id, status, created_at, updated_at }: QueueRun): QueueRun =>
  ({ run_id, status, created_at, updated_at });

export function emptyQueue(projectId: string | null, run?: Run): MessageQueue {
  return { projectId, items: [], editing: null, paused: null, submission: null, run: run ? queueRun(run) : null };
}

/** Observe before history trimming: acceptance and the last run outlive the visible page. */
export function mergeQueueRuntime(queues: Record<string, MessageQueue>, runs: Run[], messages: Message[]) {
  let result = queues;
  for (const [sessionId, queue] of Object.entries(queues)) {
    let next = queue;
    const submission = queue.submission;
    if (submission && !submission.accepted && messages.some((message) => message.session_id === sessionId &&
        message.role === 'user' && message.metadata?.client_message_id === submission.clientId)) {
      next = { ...next, submission: { ...submission, accepted: true },
        items: next.items.filter((item) => item.id !== submission.itemId) };
    }
    const run = runs.filter((item) => item.session_id === sessionId)
      .sort((a, b) => compareTime(a.created_at, b.created_at)).pop();
    const previous = next.run;
    if (run && (!previous || (run.run_id !== previous.run_id
      ? compareTime(run.created_at, previous.created_at) > 0
      : !older(run.updated_at, previous.updated_at) && !(terminal(previous.status) && !terminal(run.status)) &&
        (run.updated_at !== previous.updated_at || run.status !== previous.status)))) {
      const failed = ['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status);
      next = { ...next, run: queueRun(run), paused: failed ? next.paused ?? 'failed' : next.paused };
    }
    if (next !== queue) result = { ...result, [sessionId]: next };
  }
  return result;
}
