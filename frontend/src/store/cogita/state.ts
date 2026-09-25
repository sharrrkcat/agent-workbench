import type { StateCreator, StoreApi } from 'zustand';

import type { GeneralSettings } from '../../types/settings';
import type { Message } from '../../types/messages';
import type { Run, RunStep, RuntimeEvent } from '../../types/runs';
import type { Session, SessionPatch } from '../../types/chat';
import type { ToolRunResponse } from '../../types/tools';

export type CogitaState = {
  sessions: Session[];
  currentSession: Session | null;
  currentProjectId: string | null;
  lastOrdinarySessionId: string | null;
  initialized: boolean;
  messages: Message[];
  runs: Run[];
  stepsByRunId: Record<string, RunStep[]>;
  settings: GeneralSettings | null;
  messageVersion: number;
  runVersion: number;
  sessionVersion: number;
  sessionEpoch: number;
  settingsVersion: number;
  deletedMessageIds: string[];
  deletedRunIds: string[];
  mutatingHistory: boolean;
  sourceMessageId: string | null;
  composerDraftText: string;
  loading: boolean;
  sending: boolean;
  resolvingApprovals: string[];
  error: string | null;
  initialize: (selectOrdinary?: boolean) => Promise<void>;
  refreshCurrent: () => Promise<void>;
  reloadSessions: (projectId?: string | null) => Promise<void>;
  selectSession: (id: string, projectId?: string | null) => Promise<void>;
  createSession: (projectId?: string | null) => Promise<Session | undefined>;
  activateLocation: (projectId: string | null, sessionId?: string | null) => Promise<void>;
  forgetProject: (projectId: string) => void;
  deleteSession: (id: string) => Promise<void>;
  updateSession: (patch: SessionPatch) => Promise<void>;
  sendMessage: (content: string, attachments?: Record<string, unknown>[]) => Promise<RuntimeEvent | undefined>;
  deleteMessage: (messageId: string) => Promise<void>;
  deleteRun: (runId: string) => Promise<void>;
  retryRun: (runId: string) => Promise<void>;
  editMessage: (messageId: string, content: string, rerun?: boolean) => Promise<void>;
  cancelRun: (runId: string) => Promise<void>;
  resolveApproval: (runId: string, decision: 'approve' | 'reject') => Promise<void>;
  callTool: (name: string, args: Record<string, unknown>) => Promise<ToolRunResponse | undefined>;
  applyRuntimeEvent: (event: RuntimeEvent) => void;
  setComposerDraftText: (text: string) => void;
  setSourceMessageId: (id: string | null) => void;
  setError: (error: string | null) => void;
  setSettings: (settings: GeneralSettings) => void;
};

export type CogitaActions<K extends keyof CogitaState> = StateCreator<
  CogitaState,
  [],
  [],
  Pick<CogitaState, K>
>;
export type CogitaSet = StoreApi<CogitaState>['setState'];
export type CogitaGet = StoreApi<CogitaState>['getState'];
