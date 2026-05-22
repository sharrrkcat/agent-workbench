import { useEffect, useState } from 'react';
import { ChatInput } from './components/ChatInput';
import { ChatHeader } from './components/ChatHeader';
import { ChatView } from './components/ChatView';
import { ErrorBanner } from './components/ErrorBanner';
import { FilePreviewModal } from './components/FilePreviewModal';
import { ImagePreviewModal } from './components/ImagePreviewModal';
import { PetOverlay } from './components/PetOverlay';
import { SessionSidebar } from './components/SessionSidebar';
import { SettingsPage } from './components/SettingsPage';
import { StatusBar } from './components/StatusBar';
import { createWebSocketUrl } from './api/client';
import { useWorkbenchStore } from './store/useWorkbenchStore';
import type { ImagePreview } from './utils/images';
import type { FilePreview } from './components/MessageBubble';
import type { KnowledgeSettingsSubsection, SettingsInitialTarget, SettingsSection, WorldbookSettingsSubsection } from './components/settings/SettingsNav';

export default function App() {
  const { currentSession, initialize, refreshCurrent, applyRuntimeEvent } = useWorkbenchStore();
  const [, setLocationKey] = useState(() => currentLocationKey());
  const [wsUnavailable, setWsUnavailable] = useState(false);
  const [previewImage, setPreviewImage] = useState<ImagePreview | null>(null);
  const [previewFile, setPreviewFile] = useState<FilePreview | null>(null);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  useEffect(() => {
    const onPopState = () => setLocationKey(currentLocationKey());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    if (!currentSession || wsUnavailable) return;
    let opened = false;
    const socket = new WebSocket(createWebSocketUrl(currentSession.session_id));
    let closed = false;
    function requestNextEvent() {
      if (!closed && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'next_event' }));
      }
    }
    const handleOpen = () => {
      opened = true;
      socket.send(JSON.stringify({ type: 'ping' }));
      requestNextEvent();
    };
    const handleMessage = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type && payload.type !== 'pong') {
          applyRuntimeEvent(payload);
          if (!['message_started', 'message_delta', 'run_metrics'].includes(payload.type)) {
            void refreshCurrent().catch(() => undefined);
          }
          requestNextEvent();
        }
      } catch {
        // Ignore malformed development messages.
      }
    };
    const handleError = () => {
      if (!opened) {
        setWsUnavailable(true);
      }
    };
    socket.addEventListener('open', handleOpen);
    socket.addEventListener('message', handleMessage);
    socket.addEventListener('error', handleError);
    return () => {
      closed = true;
      socket.removeEventListener('open', handleOpen);
      socket.removeEventListener('message', handleMessage);
      socket.removeEventListener('error', handleError);
      socket.close();
    };
  }, [currentSession?.session_id, refreshCurrent, applyRuntimeEvent, wsUnavailable]);

  useEffect(() => {
    if (!currentSession || !wsUnavailable) return;
    const timer = window.setInterval(() => {
      void refreshCurrent().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [currentSession?.session_id, refreshCurrent, wsUnavailable]);

  function navigate(nextPath: string, state: Record<string, unknown> = {}) {
    window.history.pushState(state, '', nextPath);
    setLocationKey(currentLocationKey());
  }

  const settingsTarget = explicitSettingsTarget();
  if (window.location.pathname === '/settings' || window.location.hash.startsWith('#settings')) {
    return <SettingsPage initialTarget={settingsTarget} onBack={() => navigate('/')} />;
  }

  return (
    <div className="app-shell">
      <SessionSidebar onOpenSettings={() => navigate('/settings')} />
      <main className="workspace">
        <ChatHeader
          onOpenSettings={(target) => {
            if (target?.section === 'knowledge') {
              navigate('/settings?tab=knowledge&subsection=knowledge_bases', {
                settingsTab: 'knowledge',
                settingsSubsection: 'knowledge_bases',
              });
              return;
            }
            if (target?.section === 'worldbook') {
              navigate('/settings?tab=worldbook&subsection=worldbooks', {
                settingsTab: 'worldbook',
                settingsSubsection: 'worldbooks',
              });
              return;
            }
            navigate('/settings');
          }}
        />
        <ErrorBanner />
        <ChatView onPreviewImage={setPreviewImage} onPreviewFile={setPreviewFile} />
        <PetOverlay />
        <ChatInput onPreviewImage={setPreviewImage} />
        <StatusBar />
      </main>
      <ImagePreviewModal image={previewImage} onClose={() => setPreviewImage(null)} />
      <FilePreviewModal file={previewFile} onClose={() => setPreviewFile(null)} />
    </div>
  );
}

function currentLocationKey(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}:${JSON.stringify(window.history.state || {})}`;
}

function explicitSettingsTarget(): SettingsInitialTarget {
  const sections: SettingsSection[] = ['general', 'appearance', 'models', 'knowledge', 'worldbook', 'agents', 'capabilities', 'data', 'diagnostics', 'developer', 'about'];
  const params = new URLSearchParams(window.location.search);
  const queryTab = params.get('tab');
  const querySubsection = params.get('subsection');
  const hashMatch = window.location.hash.match(/^#settings:([a-z-]+)$/);
  const stateTab = window.history.state?.settingsTab;
  const stateSubsection = window.history.state?.settingsSubsection;
  const candidate = queryTab || hashMatch?.[1] || stateTab;
  const normalizedCandidate = candidate === 'llm' ? 'models' : candidate;
  const section = sections.includes(normalizedCandidate as SettingsSection) ? (normalizedCandidate as SettingsSection) : 'general';
  const subsection = querySubsection || stateSubsection;
  const target: SettingsInitialTarget = { section };
  if (section === 'models' && ['provider-profiles', 'providers'].includes(subsection)) {
    target.llmSubsection = 'providers';
  }
  if (section === 'models' && ['model-profiles', 'llm-model-profiles', 'models'].includes(subsection)) {
    target.llmSubsection = 'models';
  }
  if (section === 'models' && ['embedding-models', 'embedding-model-profiles', 'embedding_models'].includes(subsection)) {
    target.llmSubsection = 'embedding_models';
    target.knowledgeSubsection = 'embedding_models';
  }
  if (section === 'models' && ['reranker-models', 'reranker-model-profiles', 'reranker_models'].includes(subsection)) {
    target.llmSubsection = 'reranker_models';
  }
  if (candidate === 'knowledge' && ['embedding-models', 'embedding-model-profiles', 'embedding_models'].includes(subsection)) {
    target.section = 'models';
    target.llmSubsection = 'embedding_models';
    target.knowledgeSubsection = 'embedding_models';
  }
  if (candidate === 'knowledge' && ['reranker-models', 'reranker-model-profiles', 'reranker_models'].includes(subsection)) {
    target.section = 'models';
    target.llmSubsection = 'reranker_models';
  }
  if (section === 'knowledge' && ['defaults', 'embedding_models', 'knowledge_bases'].includes(subsection)) {
    target.knowledgeSubsection = subsection as KnowledgeSettingsSubsection;
  }
  if (section === 'worldbook' && ['defaults', 'worldbooks'].includes(subsection)) {
    target.worldbookSubsection = subsection as WorldbookSettingsSubsection;
  }
  return target;
}
