import type { Message, MessagePart, ToolCallPart, ToolResultPart } from '../../types/messages';
import type { Run, RunStep } from '../../types/runs';
import { compareTime, mergeRuns, terminal } from '../../store/workbench/mergeState';

export type ToolEntry = {
  call: ToolCallPart;
  message: Message;
  result?: ToolResultPart;
  resultMessage?: Message;
  step?: RunStep;
  approval?: RunStep;
};

export type ProcessingItem =
  | { kind: 'content'; id: string; part: MessagePart; message: Message }
  | { kind: 'tools'; id: string; calls: ToolEntry[] };

export type Reply = {
  run: Run;
  messages: Message[];
  steps: RunStep[];
  process: ProcessingItem[];
  answer?: Message;
  answerParts: MessagePart[];
};

export type ConversationItem =
  | { kind: 'message'; id: string; createdAt: string; message: Message }
  | { kind: 'reply'; id: string; createdAt: string; reply: Reply };

export function buildReply(run: Run, messages: Message[], steps: RunStep[]): Reply {
  const ordered = [...messages].sort((a, b) => compareTime(a.created_at, b.created_at));
  const answer = run.kind === 'chat' ? [...ordered].reverse().find((message) => message.role === 'assistant' &&
    !message.parts.some((part) => part.type === 'tool_call')) : undefined;
  const results = new Map<string, { part: ToolResultPart; message: Message }>();
  for (const message of ordered) {
    for (const part of message.parts) {
      if (part.type === 'tool_result') results.set(part.tool_call_id, { part, message });
    }
  }
  const process: ProcessingItem[] = [];
  for (const message of ordered) {
    if (message.role !== 'assistant') continue;
    for (const part of message.parts) {
      if (part.type === 'tool_call') {
        const result = results.get(part.tool_call_id);
        const entry: ToolEntry = { call: part, message, result: result?.part, resultMessage: result?.message,
          step: steps.find((step) => step.kind === 'tool' && step.metadata?.tool_call_id === part.tool_call_id),
          approval: [...steps].reverse().find((step) => step.kind === 'approval' && step.metadata?.tool_call_id === part.tool_call_id),
        };
        const last = process[process.length - 1];
        if (last?.kind === 'tools') last.calls.push(entry);
        else process.push({ kind: 'tools', id: part.tool_call_id, calls: [entry] });
      } else if (part.type !== 'tool_result' && (part.type === 'reasoning' || message !== answer)) {
        if ((part.type === 'text' || part.type === 'reasoning') && !part.text.trim()) continue;
        process.push({ kind: 'content', id: part.id, part, message });
      }
    }
  }
  return { run, messages: ordered, steps, process, answer,
    answerParts: answer?.parts.filter((part) => !['reasoning', 'tool_call', 'tool_result'].includes(part.type)) || [],
  };
}

export function buildConversation(sessionId: string, messages: Message[], runs: Run[], stepsByRunId: Record<string, RunStep[]>): ConversationItem[] {
  const currentMessages = messages.filter((message) => message.session_id === sessionId);
  const currentRuns = mergeRuns(currentMessages.flatMap((message) => message.run ? [message.run] : []),
    runs.filter((run) => run.session_id === sessionId));
  const byRun = new Map<string, Message[]>();
  for (const message of currentMessages) {
    if (message.run_id) byRun.set(message.run_id, [...(byRun.get(message.run_id) || []), message]);
  }
  const items: ConversationItem[] = currentMessages.filter((message) => message.role === 'user' || !message.run_id)
    .map((message) => ({ kind: 'message', id: message.message_id, createdAt: message.created_at, message }));
  for (const run of currentRuns) {
    items.push({ kind: 'reply', id: run.run_id, createdAt: run.created_at,
      reply: buildReply(run, byRun.get(run.run_id) || [], stepsByRunId[run.run_id] || run.steps || []),
    });
  }
  return items.sort((a, b) => compareTime(a.createdAt, b.createdAt) || (a.kind === b.kind ? 0 : a.kind === 'message' ? -1 : 1));
}

export function toolEntryStatus(entry: ToolEntry, run: Run): 'pending' | 'running' | 'waiting' | ToolResultPart['status'] {
  if (entry.result) return entry.result.status;
  if (entry.approval?.status === 'running' && run.status === 'WAITING_FOR_USER') return 'waiting';
  if (terminal(run.status)) return run.status === 'CANCELLED' ? 'cancelled' : 'error';
  return entry.step?.status === 'running' ? 'running' : 'pending';
}
