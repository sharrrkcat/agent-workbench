import { create } from 'zustand';
import type { WorkbenchState } from './workbench/state';
import { createSessionActions } from './workbench/sessionActions';
import { createMessageActions } from './workbench/messageActions';
import { createRunActions } from './workbench/runActions';
import { handleRuntimeEvent } from './workbench/runtimeEvents';

export const useWorkbenchStore = create<WorkbenchState>((set, get, store) => ({
  sessions: [],
  currentSession: null,
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
