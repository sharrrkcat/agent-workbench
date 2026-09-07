import type { Session } from './chat';
import type { Message } from './messages';

export type RunStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'CANCELLING'
  | 'WAITING_FOR_USER'
  | 'DONE'
  | 'FAILED'
  | 'CANCELLED'
  | 'INTERRUPTED';

export type RunKind = 'chat' | 'tool';

export type RunStepKind = 'context' | 'model' | 'save' | 'approval' | 'tool';

export type RunStepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export type RunStep = {
  step_id: string;
  run_id: string;
  kind: RunStepKind;
  parent_step_id?: string | null;
  label: string;
  status: RunStepStatus;
  message?: string;
  order: number;
  started_at?: string | null;
  finished_at?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type Run = {
  run_id: string;
  session_id: string;
  kind: RunKind;
  status: RunStatus;
  persona_id: string;
  current_step?: string;
  stage?: string;
  progress_message?: string;
  progress_current?: number | null;
  progress_total?: number | null;
  cancel_requested?: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  error?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  steps?: RunStep[];
};

export type RunEvent = {
  event_id: string;
  run_id: string;
  session_id: string;
  type: string;
  message?: string;
  payload?: Record<string, unknown>;
  created_at: string;
};

export type RuntimeResponse = {
  success: boolean;
  data?: unknown;
  error?: string | null;
  error_code?: string | null;
  run?: Run | null;
  session?: Session;
  messages?: Message[];
};

export type RuntimeEvent = {
  type: string;
  session_id: string;
  run_id?: string;
  message_id?: string;
  payload?: Record<string, unknown>;
  created_at?: string;
};
