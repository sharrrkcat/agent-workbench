import { createHistoryActions } from './cogita/historyActions';
import { trimHistory } from './cogita/historyWindow';
import type { CogitaSet } from './cogita/state';
import { create } from 'zustand';
import type { CogitaState } from './cogita/state';
import { createSessionActions } from './cogita/sessionActions';
import { createMessageActions } from './cogita/messageActions';
import { createRunActions } from './cogita/runActions';
import { handleRuntimeEvent } from './cogita/runtimeEvents';

export const useCogitaStore = create<CogitaState>((rawSet, get, store) => {
  const set: CogitaSet = (patch: Parameters<CogitaSet>[0]) => rawSet((state) => {
    const change = typeof patch === 'function' ? patch(state) : patch;
    const next = { ...state, ...change };
    return { ...change, ...(('messages' in change || 'runs' in change || 'stepsByRunId' in change) ? trimHistory(next) : {}) };
  });
  return ({
  sessions: [],
  currentSession: null,
  sessionLoad: null,
  chatDraft: null,
  pendingKnowledge: null,
  currentProjectId: null,
  lastOrdinarySessionId: null,
  initialized: false,
  messages: [],
  historyWindow: null, historyLoading: false, historyFollowing: true, historyAnchor: null,
  runs: [],
  stepsByRunId: {},
  settings: null,
  messageVersion: 0,
  runVersion: 0,
  sessionVersion: 0,
  sessionEpoch: 0,
  settingsVersion: 0,
  deletedMessageIds: [],
  deletedRunIds: [],
  mutatingHistory: false,
  composerDraftText: '',
  loading: false,
  sending: false,
  awaitingAcceptance: false,
  pendingClientMessageId: null,
  resolvingApprovals: [],
  error: null,
  ...createSessionActions(set, get, store),
  ...createHistoryActions(set, get, store),
  ...createMessageActions(set, get, store),
  ...createRunActions(set, get, store),
  applyRuntimeEvent: (event) => handleRuntimeEvent(set, get, event),
  setSettings: (settings) => set((state) => ({ settings, settingsVersion: state.settingsVersion + 1 })),
});
});
