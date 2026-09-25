import { create } from 'zustand';
import type { CogitaState } from './cogita/state';
import { createSessionActions } from './cogita/sessionActions';
import { createMessageActions } from './cogita/messageActions';
import { createRunActions } from './cogita/runActions';
import { handleRuntimeEvent } from './cogita/runtimeEvents';

export const useCogitaStore = create<CogitaState>((set, get, store) => ({
  sessions: [],
  currentSession: null,
  currentProjectId: null,
  lastOrdinarySessionId: null,
  initialized: false,
  messages: [],
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
  sourceMessageId: null,
  composerDraftText: '',
  loading: false,
  sending: false,
  resolvingApprovals: [],
  error: null,
  ...createSessionActions(set, get, store),
  ...createMessageActions(set, get, store),
  ...createRunActions(set, get, store),
  applyRuntimeEvent: (event) => handleRuntimeEvent(set, get, event),
  setSettings: (settings) => set((state) => ({ settings, settingsVersion: state.settingsVersion + 1 })),
}));
