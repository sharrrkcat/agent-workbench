import type { StateCreator, StoreApi } from 'zustand';

import type { GeneralSettings } from '../../types/settings';
import type { Attachment, Message } from '../../types/messages';
import type { ComposerAttachment, MessageQueue } from './messageQueue';
import type { Run, RunStep, RuntimeEvent } from '../../types/runs';
import type { ChatDraft, Session, SessionPatch } from '../../types/chat';
import type { HistoryWindow } from '../../types/history';
import type { HistoryLoad } from './historyWindow';

export type CogitaState = {
  sessions: Session[];
  currentSession: Session | null;
  sessionLoad: { sessionId: string; characterId: string; status: 'loading' | 'ready' | 'error'; error: string | null } | null;
  chatDraft: ChatDraft | null;
  currentCharacterId: string | null;
  initialized: boolean;
  conversationVisible: boolean;
  setConversationVisible: (visible: boolean) => void;
  messages: Message[];
  historyWindow: HistoryWindow | null;
  historyLoading: boolean;
  historyFollowing: boolean;
  historyAnchor: string | null;
  loadHistory: (direction: HistoryLoad, cursor?: string) => Promise<void>;
  setHistoryAnchor: (cursor: string | null) => void;
  setHistoryFollowing: (following: boolean) => void;
  runs: Run[];
  stepsByRunId: Record<string, RunStep[]>;
  settings: GeneralSettings | null;
  messageVersion: number;
  runVersion: number;
  qqRefreshVersion: number;
  sessionVersion: number;
  sessionEpoch: number;
  settingsVersion: number;
  deletedMessageIds: string[];
  deletedRunIds: string[];
  mutatingHistory: boolean;
  composerDraftText: string;
  messageQueues: Record<string, MessageQueue>;
  queueTarget: string | null;
  savingSessionIds: string[];
  loading: boolean;
  sending: boolean;
  awaitingAcceptance: boolean;
  pendingClientMessageId: string | null;
  resolvingApprovals: string[];
  error: string | null;
  initialize: (selectDefault?: boolean) => Promise<void>;
  refreshCurrent: () => Promise<void>;
  reloadSessions: (characterId?: string | null) => Promise<void>;
  selectSession: (id: string, characterId?: string | null) => Promise<void>;
  retrySession: () => Promise<void>;
  startDraft: (characterId?: string | null) => Promise<void>;
  saveDraft: (patch: SessionPatch) => void;
  activateLocation: (characterId: string | null, sessionId?: string | null) => Promise<void>;
  deactivateConversation: () => void;
  forgetCharacter: (characterId: string) => void;
  deleteSession: (id: string) => Promise<void>;
  updateSession: (patch: SessionPatch) => Promise<boolean>;
  sendMessage: (content: string, attachments?: Record<string, unknown>[], queueItemId?: string) => Promise<boolean>;
  enqueueMessage: (content: string, attachments?: Attachment[]) => boolean;
  beginQueuedEdit: (id: string) => boolean;
  saveQueuedEdit: () => boolean;
  setQueuedEditAttachments: (sessionId: string, id: string, change: (items: ComposerAttachment[]) => ComposerAttachment[]) => void;
  deleteQueuedMessage: (id: string) => void;
  resumeMessageQueue: () => Promise<void>;
  dispatchQueuedMessage: () => Promise<void>;
  reconcileMessageQueue: (sessionId: string) => Promise<boolean>;
  observeQueueRun: (run: Run) => void;
  deleteMessage: (messageId: string) => Promise<void>;
  deleteRun: (runId: string) => Promise<void>;
  retryRun: (runId: string) => Promise<void>;
  compactContext: () => Promise<boolean>;
  editMessage: (messageId: string, content: string, attachmentIds: string[], rerun?: boolean) => Promise<boolean>;
  cancelRun: (runId: string) => Promise<void>;
  resolveApproval: (runId: string, decision: 'approve' | 'reject') => Promise<void>;
  applyRuntimeEvent: (event: RuntimeEvent) => void;
  setComposerDraftText: (text: string) => void;
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
