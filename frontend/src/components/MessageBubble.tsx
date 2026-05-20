import { Children, cloneElement, isValidElement, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactElement, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { BookOpen, BookOpenText, Check, ChevronDown, ChevronRight, Circle, CircleAlert, Clock3, Copy, ExternalLink, FileText, Globe, Loader2, Minus, Pencil, RefreshCw, RotateCcw, Search, Send, Trash2, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ActionFormBlock, ActionFormField, Agent, Attachment, CommandButtonsBlock, FileAttachment, FileContentPayload, GeneralSettings, ImageAttachment, ImagePayload, KnowledgeChunk, Message, MessagePart, Run, RunStep, WorldbookEntry } from '../types';
import { api } from '../api/client';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { ActionButtons } from './ActionButtons';
import { AgentAvatar } from './AgentAvatar';
import { formatMessageTime, parseServerTime } from '../utils/time';
import { resolveAttachmentUrl, safeImageUrl, type ImagePreview } from '../utils/images';
import { getResolvedAgentDisplay } from '../utils/agents';
import { parseKnowledgeCitationToken } from '../utils/knowledgeCitations';
import { formatApiError, getRunStatusLabel, getRunStepLabel } from '../i18n/formatters';
import { AppModal, Chip } from './ui';
import { MessagePartsRenderer, hasRenderableParts, hasWideMessageParts } from './messages/MessagePartsRenderer';

export type FilePreview = {
  url: string;
  name: string;
  mime_type: string;
  size: number;
  language?: string | null;
};

type RunStepNode = RunStep & { children: RunStepNode[] };

export function MessageBubble({ message, onPreviewImage, onPreviewFile }: { message: Message; onPreviewImage: (image: ImagePreview) => void; onPreviewFile: (file: FilePreview) => void }) {
  const { t } = useTranslation(['chat', 'common', 'runs', 'errors']);
  const agents = useWorkbenchStore((state) => state.agents);
  const deleteMessage = useWorkbenchStore((state) => state.deleteMessage);
  const retryMessage = useWorkbenchStore((state) => state.retryMessage);
  const editMessage = useWorkbenchStore((state) => state.editMessage);
  const setError = useWorkbenchStore((state) => state.setError);
  const pendingMessageActionId = useWorkbenchStore((state) => state.pendingMessageActionId);
  const storeRun = useWorkbenchStore((state) => (message.run_id ? state.runsById[message.run_id] : undefined));
  const storeRunSteps = useWorkbenchStore((state) => (message.run_id ? state.stepsByRunId[message.run_id] : undefined));
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(copyableMessageContent(message));
  const [contextModalOpen, setContextModalOpen] = useState(false);
  const [contextModalInitial, setContextModalInitial] = useState<{ tab?: ContextTab; targetRef?: string } | null>(null);
  const [citationModal, setCitationModal] = useState<KnowledgeCitationSelection | null>(null);

  if (message.metadata?.event_type) {
    return <SystemEventSeparator message={message} />;
  }

  if ((hasErrorPart(message) || message.client_error || message.metadata?.success === false) && !hasProducerIdentity(message)) {
    return <InlineErrorBlock message={message} />;
  }

  const agent = message.agent_id ? agents.find((item) => item.id === message.agent_id) : undefined;
  const agentDisplay = getResolvedAgentDisplay(agent);
  const isUser = message.role === 'user';
  const isCommand = message.role === 'command' || message.speaker_type === 'capability' || Boolean(message.command_name);
  const kind = isUser ? 'user' : isCommand ? 'command' : 'agent';
  const isAgentMessage = message.role === 'assistant' || message.role === 'agent';
  const hasWidePart = !isUser && hasWideMessageParts(message.parts);
  const operationPending = pendingMessageActionId === message.message_id;
  const metricsLabel = isAgentMessage ? formatMetrics(message.metadata?.llm_metrics, Boolean(message.metadata?.interrupted), t) : '';
  const reasoningContent = isAgentMessage ? extractReasoningContent(message.metadata) : '';
  const runSteps = storeRunSteps || messageRunSteps(message);
  const messageRun = storeRun || message.run;
  const contextMetadata = isAgentMessage ? normalizeContextMetadata({ message_metadata: message.metadata, run_metadata: messageRun?.metadata, steps: runSteps }) : {};
  const runKnowledge = contextMetadata.knowledge ? knowledgeRetrievalSummaryFromNormalized(contextMetadata.knowledge) : null;
  const canViewContext = Boolean(contextMetadata.memory?.injected || contextMetadata.knowledge?.canViewSnippets || (contextMetadata.worldbook?.injected && contextMetadata.worldbook.entryRefs.length) || contextMetadata.web?.sourceRefs.length);
  if (!editing && !message.client_status && !hasVisibleRun(messageRun) && !hasRenderableMessage(message, reasoningContent)) {
    return null;
  }

  useEffect(() => {
    if (!editing) setEditValue(copyableMessageContent(message));
  }, [editing, message.parts]);

  async function copyMessage() {
    try {
      await navigator.clipboard.writeText(copyableMessageContent(message));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1300);
    } catch (error) {
      setError(error, 'Failed to copy message');
    }
  }

  function confirmDelete() {
    const confirmed = window.confirm(t('chat:confirmDelete', { defaultValue: 'Delete this message?\nThis only removes the selected message.' }));
    if (!confirmed) return;
    void deleteMessage(message.message_id);
  }

  async function saveEdit() {
    const next = editValue.trim();
    if (!next || operationPending) return;
    try {
      await editMessage(message.message_id, next);
      setEditing(false);
    } catch {
      // The store surfaces the floating error.
    }
  }

  return (
    <article className={`message-row ${kind} ${hasWidePart ? 'message-has-wide-part' : ''} ${editing ? 'message-editing' : ''}`}>
      {!isUser ? <AgentAvatar agent={agentDisplay} label={message.command_name || undefined} /> : null}
      <div className="message-stack">
        <MessageHeader message={message} agent={agent} agentName={agentDisplay.name} kind={kind} modelLabel={resolvedModelLabel(message)} modelMismatch={hasModelMismatch(message)} />
        <div className={`message ${kind} ${hasWidePart ? 'message-has-wide-part' : ''} ${editing ? 'message-editing' : ''} ${message.client_status ? message.client_status : ''}`}>
          {editing ? (
            <div className="message-edit-form">
              <textarea value={editValue} onChange={(event) => setEditValue(event.target.value)} rows={Math.min(8, Math.max(3, editValue.split(/\r\n|\r|\n/).length))} />
              <div>
                <button type="button" onClick={() => setEditing(false)} disabled={operationPending}>
                  {t('common:cancel')}
                </button>
                <button type="button" className="primary" onClick={() => void saveEdit()} disabled={!editValue.trim() || operationPending}>
                  {t('chat:actions.saveSubmit', { defaultValue: 'Save & submit' })}
                </button>
              </div>
            </div>
          ) : (
            <>
              {reasoningContent ? <ThoughtBlock content={reasoningContent} streaming={message.client_status === 'streaming'} /> : null}
              <MessageContent
                message={message}
                kind={kind}
                contextMetadata={contextMetadata}
                onOpenKnowledgeCitation={setCitationModal}
                onOpenWebCitation={(refId) => {
                  setContextModalInitial({ tab: 'web', targetRef: refId });
                  setContextModalOpen(true);
                }}
                onPreviewImage={onPreviewImage}
                onPreviewFile={onPreviewFile}
              />
              <RunStepsPanel run={messageRun} steps={runSteps} runKnowledge={runKnowledge} />
            </>
          )}
          {message.client_status === 'pending' ? (
            <div className="message-status">
              <Clock3 size={13} />
              {t('chat:status.sending', { defaultValue: 'Sending' })}
            </div>
          ) : null}
          {message.client_status === 'streaming' ? (
            <div className="message-status">
              <Clock3 size={13} />
              {t('chat:status.streaming', { defaultValue: 'Streaming' })}
            </div>
          ) : null}
          <ActionButtons actions={message.available_actions} />
        </div>
        {!message.client_status && !editing ? (
          <div className="message-hover-actions" aria-label={t('chat:actions.messageActions', { defaultValue: 'Message actions' })}>
            <button type="button" onClick={() => void copyMessage()} disabled={operationPending} title={t('common:copy')}>
              {copied ? <Check size={13} /> : <Copy size={13} />}
              {copied ? <span>{t('chat:actions.copied', { defaultValue: 'Copied' })}</span> : ''}
            </button>
            {isAgentMessage ? (
              <button type="button" onClick={() => void retryMessage(message.message_id)} disabled={operationPending} title={t('chat:actions.retry', { defaultValue: 'Retry' })}>
                <RefreshCw size={13} className={operationPending ? 'spin' : undefined} />
              </button>
            ) : null}
            {isUser ? (
              <button type="button" onClick={() => setEditing(true)} disabled={operationPending} title={t('common:edit')}>
                <Pencil size={13} />
              </button>
            ) : null}
            {isUser || isAgentMessage || isCommand ? (
              <button type="button" className="danger" onClick={confirmDelete} disabled={operationPending} title={t('common:delete')}>
                <Trash2 size={13} />
              </button>
            ) : null}
            {canViewContext ? (
              <button type="button" onClick={() => { setContextModalInitial(null); setContextModalOpen(true); }} disabled={operationPending} title={t('chat:actions.viewInjectedContext')}>
                <BookOpen size={13} />
              </button>
            ) : null}
            {metricsLabel ? <span className="message-metrics">{metricsLabel}</span> : null}
          </div>
        ) : null}
      </div>
      {contextModalOpen ? <InjectedContextModal context={contextMetadata} initialTab={contextModalInitial?.tab} targetRef={contextModalInitial?.targetRef} onClose={() => setContextModalOpen(false)} /> : null}
      {citationModal ? <KnowledgeCitationModal selection={citationModal} onClose={() => setCitationModal(null)} /> : null}
    </article>
  );
}

type KnowledgeSnippetRef = {
  index: string;
  chunk_id: string;
  knowledge_base_id?: string;
  knowledge_base_name?: string;
  source_id?: string;
  source_title?: string;
  rank?: number;
  heading_path?: string;
  vector_score?: number;
  keyword_score?: number;
  rrf_score?: number;
  rerank_score?: number;
};

type KnowledgeSnippet = KnowledgeSnippetRef & {
  chunk?: KnowledgeChunk;
  error?: string;
};

type KnowledgeRetrievalSummary = {
  source?: string;
  kbLabels: string[];
  injected?: boolean;
  resultCount?: number;
  embeddingLabel?: string;
  embeddingDimension?: number | string;
  vectorCandidateCount?: number;
  keywordCandidateCount?: number;
  mergedCandidateCount?: number;
  rerankerUsed?: boolean;
  rerankerFailed?: boolean;
  rerankerInputCount?: number;
  rerankerOutputCount?: number;
  warnings: string[];
};

type KbSearchResult = {
  rank?: number;
  knowledge_base_id?: string;
  knowledge_base_name?: string;
  source_id?: string;
  title?: string;
  heading_path?: string;
  content?: string;
  vector_score?: number | null;
  keyword_score?: number | null;
  rrf_score?: number | null;
  rerank_score?: number | null;
};

type KbSearchDebug = {
  embedding_groups?: { embedding_model_profile_id?: string; knowledge_base_ids?: string[]; candidate_count?: number }[];
  keyword_candidate_count?: number;
  merged_candidate_count?: number;
  reranker_used?: boolean;
  reranker_failed?: boolean;
  warnings?: string[];
};

type KbSearchResponse = {
  query?: string;
  results: KbSearchResult[];
  debug?: KbSearchDebug;
  error?: { code?: string; message?: string };
};

type WebSearchResult = {
  rank?: number;
  title?: string;
  url?: string;
  domain?: string;
  snippet?: string;
  published_at?: string | null;
  source?: string;
};

type WebSearchResponse = {
  kind?: string;
  schema?: string;
  query?: string;
  provider?: string;
  searched_at?: string;
  results: WebSearchResult[];
  warnings: string[];
};

type CoreMemoryContextSummary = {
  enabled?: boolean;
  injected?: boolean;
  contentChars?: number;
  skippedReason?: string;
  warnings: string[];
};

type KnowledgeContextSummary = {
  injected?: boolean;
  snippetCount?: number;
  snippetRefs: KnowledgeSnippetRef[];
  kbNames: string[];
  rerankerSummary?: string;
  warnings: string[];
  canViewSnippets: boolean;
  retrieval?: KnowledgeRetrievalSummary;
};

type WorldbookEntryRef = {
  index: string;
  worldbook_id?: string;
  worldbook_name?: string;
  entry_id: string;
  entry_name?: string;
  activation_mode?: 'always' | 'keyword' | string;
  matched_keywords: string[];
  matched_by_recursion?: boolean;
  recursion_depth?: number;
  injected_index?: number;
  warnings: string[];
};

type WorldbookContextSummary = {
  enabled?: boolean;
  injected?: boolean;
  matchedEntryCount?: number;
  injectedEntryCount?: number;
  recursionDepth?: number;
  recursionRoundsUsed?: number;
  entryRefs: WorldbookEntryRef[];
  warnings: string[];
};

type WebContextSummary = {
  enabled?: boolean;
  attempted?: boolean;
  injected?: boolean;
  provider?: string;
  resultCount?: number;
  sourceRefs: WebSourceRef[];
  query?: string;
  querySource?: string;
  skippedReason?: string;
  truncated?: boolean;
  resolverUsed?: boolean;
  resolverReason?: string;
  resolverConfidence?: string;
  searchDiagnostics?: WebSearchContextDiagnostics;
  pageFetchEnabled?: boolean;
  pagesAttempted?: number;
  pagesFetched?: number;
  pagesFailed?: number;
  pageFetchWarnings: string[];
  pageExcerptGate?: PageExcerptGateSummary;
  candidateJudge?: WebCandidateJudgeSummary;
  warnings: string[];
};

type WebSearchContextDiagnostics = {
  filteredCount?: number;
  dedupedCount?: number;
  filtersApplied?: Record<string, boolean>;
  warnings: string[];
};

type WebCandidateJudgeSummary = {
  enabled?: boolean;
  used?: boolean;
  mode?: string;
  schema?: string;
  candidateCount?: number;
  retainedCount?: number;
  rejectedCount?: number;
  unjudgedCount?: number;
  invalidItemCount?: number;
  fallbackUsed?: boolean;
  warnings: string[];
};

type PageExcerptGateSummary = {
  enabled?: boolean;
  backend?: string;
  attempted?: number;
  accepted?: number;
  rejected?: number;
  failed?: number;
  stoppedReason?: string;
  warnings: string[];
};

type WebSourceRef = {
  ref_id: string;
  rank?: number;
  title?: string;
  url?: string;
  domain?: string;
  published_at?: string | null;
  source?: string;
  snippet?: string;
  snippet_preview?: string;
  page_fetch_status?: string;
  page_title?: string;
  page_excerpt_preview?: string;
  page_excerpt_chars?: number;
  page_fetch_warning?: string;
  page_excerpt_gate_status?: string;
  page_excerpt_quality?: string;
  page_excerpt_confidence?: string;
  page_excerpt_coverage?: string;
  page_excerpt_gate_reason?: string;
  page_excerpt_gate_warning?: string;
  page_excerpt_injected?: boolean;
  candidate_judge_state?: string;
  candidate_judge_relevance?: string;
  candidate_judge_role?: string;
  candidate_judge_confidence?: string;
  candidate_judge_reason?: string;
};

type NormalizedContextMetadata = {
  memory?: CoreMemoryContextSummary;
  knowledge?: KnowledgeContextSummary;
  worldbook?: WorldbookContextSummary;
  web?: WebContextSummary;
};

type ContextTab = 'knowledge' | 'worldbook' | 'memory' | 'web';

type KnowledgeCitationSelection = {
  token: string;
  labels: string[];
  refs: KnowledgeSnippetRef[];
  missingLabels: string[];
};

type WorldbookEntryState = {
  ref: WorldbookEntryRef;
  entry?: WorldbookEntry;
  loading?: boolean;
  error?: string;
  missing?: boolean;
};

function InjectedContextModal({ context, initialTab, targetRef, onClose }: { context: NormalizedContextMetadata; initialTab?: ContextTab; targetRef?: string; onClose: () => void }) {
  const { t } = useTranslation(['chat', 'common']);
  const tabs = contextModalTabs(context);
  const [activeTab, setActiveTab] = useState<ContextTab>(() => (initialTab && tabs.includes(initialTab) ? initialTab : tabs[0] || 'knowledge'));
  const title = tabs.length > 1 ? t('chat:contextModal.title') : tabLabel(tabs[0] || 'knowledge', t);
  const subtitle = contextModalSubtitle(context, t);

  useEffect(() => {
    if (!tabs.includes(activeTab) && tabs.length) setActiveTab(tabs[0]);
  }, [activeTab, tabs]);

  return (
    <AppModal
      open
      width="large"
      title={title}
      subtitle={subtitle}
      closeLabel={t('common:close')}
      className="knowledge-snippets-modal context-modal"
      bodyClassName="context-modal-body"
      onClose={onClose}
    >
      {tabs.length > 1 ? (
        <div className="context-sources-tabs context-modal-tabs" role="tablist">
          {tabs.map((tab) => (
            <button key={tab} type="button" role="tab" className={activeTab === tab ? 'active' : ''} onClick={() => setActiveTab(tab)}>
              {tab === 'worldbook' ? <BookOpenText size={14} /> : tab === 'web' ? <Globe size={14} /> : <BookOpen size={14} />}
              {tabLabel(tab, t)}
            </button>
          ))}
        </div>
      ) : null}
      <div className="knowledge-snippets-body context-modal-scroll">
        {!tabs.length ? <p className="knowledge-snippets-state">{t('chat:contextModal.noContext')}</p> : null}
        {activeTab === 'memory' && context.memory ? <MemoryContextTab summary={context.memory} /> : null}
        {activeTab === 'knowledge' && context.knowledge ? <KnowledgeSnippetsTab refs={context.knowledge.snippetRefs} /> : null}
        {activeTab === 'worldbook' && context.worldbook ? <WorldbookEntriesTab refs={context.worldbook.entryRefs} /> : null}
        {activeTab === 'web' && context.web ? <WebSourcesTab refs={context.web.sourceRefs} targetRef={targetRef} /> : null}
      </div>
    </AppModal>
  );
}

function MemoryContextTab({ summary }: { summary: CoreMemoryContextSummary }) {
  const { t } = useTranslation(['chat']);
  const [settings, setSettings] = useState<GeneralSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    api.getGeneralSettings()
      .then((nextSettings) => {
        if (!cancelled) setSettings(nextSettings);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : t('chat:contextModal.failedToLoadCoreMemory'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const content = settings?.core_memory_content || '';
  return (
    <section className="context-modal-section">
      <div className="context-modal-section-heading">
        <div>
          <strong>{t('chat:contextModal.coreMemory')}</strong>
          <small>{t('chat:contextModal.showingCurrentCoreMemory')}</small>
        </div>
        <div className="knowledge-snippet-scores">
          <span>{summary.injected ? t('chat:contextModal.injected') : t('chat:contextModal.skipped')}</span>
          <span>{t('chat:contextModal.chars', { count: content.length || summary.contentChars || 0 })}</span>
          {summary.skippedReason ? <span>{summary.skippedReason}</span> : null}
          {summary.warnings.length ? <span>{t('chat:contextModal.warningsCount', { count: summary.warnings.length })}</span> : null}
        </div>
      </div>
      {loading ? <p className="knowledge-snippets-state">{t('chat:contextModal.loadingCoreMemory')}</p> : null}
      {error ? <p className="knowledge-snippets-state error">{error}</p> : null}
      {!loading && !error ? <pre className="knowledge-snippet-content context-content-block">{content || t('chat:contextModal.emptyCoreMemory')}</pre> : null}
      {summary.warnings.length ? <WarningList warnings={summary.warnings} /> : null}
    </section>
  );
}

function KnowledgeSnippetsTab({ refs }: { refs: KnowledgeSnippetRef[] }) {
  const { t } = useTranslation(['chat']);
  const [snippets, setSnippets] = useState<KnowledgeSnippet[]>(() => refs.map((ref) => ({ ...ref })));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.allSettled(refs.map((ref) => api.getKnowledgeChunk(ref.chunk_id)))
      .then((results) => {
        if (cancelled) return;
        setSnippets(refs.map((ref, index) => {
          const result = results[index];
          if (result?.status === 'fulfilled') return { ...ref, chunk: result.value };
          const reason = result?.status === 'rejected' && result.reason instanceof Error ? result.reason.message : t('chat:contextModal.failedToLoadKnowledgeSnippets');
          return { ...ref, error: reason };
        }));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refs, t]);

  return (
    <>
      {loading ? <p className="knowledge-snippets-state">{t('chat:contextModal.loadingKnowledgeSnippets')}</p> : null}
      {!loading && !snippets.length ? <p className="knowledge-snippets-state">{t('chat:contextModal.noKnowledgeSnippets')}</p> : null}
      {!loading
        ? snippets.map((snippet) => (
            <article className="knowledge-snippet-card" key={`${snippet.index}:${snippet.chunk_id}`}>
              <div className="knowledge-snippet-heading">
                <span>{snippet.index}</span>
                <div>
                  <strong>{snippet.chunk?.knowledge_base_name || snippet.knowledge_base_name || snippet.knowledge_base_id || t('chat:contextModal.knowledgeBase')}</strong>
                  <small>{snippet.chunk?.source_title || snippet.source_title || snippet.source_id || t('chat:contextModal.source')}</small>
                  {snippet.chunk?.heading_path || snippet.heading_path ? <small>{snippet.chunk?.heading_path || snippet.heading_path}</small> : null}
                </div>
              </div>
              {snippet.error ? <p className="knowledge-snippets-state error">{t('chat:contextModal.knowledgeSnippetUnavailable')}: {snippet.error}</p> : <pre className="knowledge-snippet-content">{snippet.chunk?.content || ''}</pre>}
              <div className="knowledge-snippet-scores">
                {scoreLabel(t('chat:contextModal.rank'), snippet.rank)}
                {scoreLabel(t('chat:contextModal.vector'), snippet.vector_score)}
                {scoreLabel(t('chat:contextModal.keyword'), snippet.keyword_score)}
                {scoreLabel(t('chat:contextModal.rrf'), snippet.rrf_score)}
                {scoreLabel(t('chat:contextModal.rerank'), snippet.rerank_score)}
                {scoreLabel(t('chat:contextModal.chunk'), snippet.chunk?.chunk_index)}
              </div>
            </article>
          ))
        : null}
    </>
  );
}

function KnowledgeCitationModal({ selection, onClose }: { selection: KnowledgeCitationSelection; onClose: () => void }) {
  const { t } = useTranslation(['chat', 'common']);
  const subtitle = selection.labels.length > 1
    ? t('chat:citations.snippetsSubtitle', { labels: selection.labels.join(', ') })
    : t('chat:citations.snippetSubtitle', { label: selection.labels[0] || selection.token });

  return (
    <AppModal
      open
      width="large"
      title={t('chat:citations.modalTitle')}
      subtitle={subtitle}
      closeLabel={t('common:close')}
      className="knowledge-snippets-modal context-modal"
      bodyClassName="context-modal-body"
      onClose={onClose}
    >
      <div className="knowledge-snippets-body context-modal-scroll">
        {selection.missingLabels.length ? (
          <p className="knowledge-snippets-state error">
            {t('chat:citations.unavailableLabels', { labels: selection.missingLabels.join(', ') })}
          </p>
        ) : null}
        <KnowledgeSnippetsTab refs={selection.refs} />
      </div>
    </AppModal>
  );
}

function WorldbookEntriesTab({ refs }: { refs: WorldbookEntryRef[] }) {
  const { t } = useTranslation(['chat']);
  const [items, setItems] = useState<WorldbookEntryState[]>(() => refs.map((ref) => ({ ref, loading: true })));

  useEffect(() => {
    let cancelled = false;
    setItems(refs.map((ref) => ({ ref, loading: true })));
    Promise.allSettled(refs.map((ref) => api.getWorldbookEntry(ref.entry_id)))
      .then((results) => {
        if (cancelled) return;
        setItems(refs.map((ref, index) => {
          const result = results[index];
          if (result?.status === 'fulfilled') return { ref, entry: result.value, loading: false };
          const message = result?.status === 'rejected' && result.reason instanceof Error ? result.reason.message : t('chat:contextModal.failedToLoadWorldbookEntry');
          return { ref, loading: false, missing: message.includes('not found') || message.includes('NOT_FOUND'), error: message };
        }));
      });
    return () => {
      cancelled = true;
    };
  }, [refs, t]);

  if (!refs.length) return <p className="knowledge-snippets-state">{t('chat:contextModal.noWorldbookEntries')}</p>;

  return (
    <>
      {items.map((item) => {
        const entry = item.entry;
        const ref = item.ref;
        return (
          <article className="knowledge-snippet-card context-entry-card" key={`${ref.index}:${ref.entry_id}`}>
            <div className="knowledge-snippet-heading">
              <span>{ref.index}</span>
              <div>
                <strong>{entry?.name || ref.entry_name || ref.entry_id}</strong>
                <small>{ref.worldbook_name || ref.worldbook_id || t('chat:contextModal.worldbook')}</small>
                <small>{t('chat:contextModal.showingCurrentEntryContent')}</small>
              </div>
            </div>
            <div className="knowledge-snippet-scores">
              <Chip tone={activationModeTone(entry?.activation_mode || ref.activation_mode)}>{activationModeLabel(entry?.activation_mode || ref.activation_mode, t)}</Chip>
              {ref.matched_keywords.length ? <span>{t('chat:contextModal.matchedKeywords')}: {ref.matched_keywords.join(', ')}</span> : null}
              {ref.recursion_depth !== undefined ? <span>{t('chat:contextModal.recursion')}: {ref.recursion_depth}</span> : null}
              {ref.matched_by_recursion ? <span>{t('chat:contextModal.matchedByRecursion')}</span> : null}
            </div>
            {item.loading ? <p className="knowledge-snippets-state">{t('chat:contextModal.loadingWorldbookEntry')}</p> : null}
            {!item.loading && item.missing ? <p className="knowledge-snippets-state error">{t('chat:contextModal.worldbookEntryMissing')}</p> : null}
            {!item.loading && !item.missing && item.error ? <p className="knowledge-snippets-state error">{t('chat:contextModal.failedToLoadWorldbookEntry')}: {item.error}</p> : null}
            {!item.loading && entry ? <pre className="knowledge-snippet-content context-content-block">{entry.content || ''}</pre> : null}
            {ref.warnings.length ? <WarningList warnings={ref.warnings} /> : null}
          </article>
        );
      })}
    </>
  );
}

function WebSourcesTab({ refs, targetRef }: { refs: WebSourceRef[]; targetRef?: string }) {
  const { t } = useTranslation(['chat']);
  const targetRefElement = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!targetRefElement.current) return;
    targetRefElement.current.scrollIntoView({ block: 'nearest' });
  }, [targetRef]);

  if (!refs.length) return <p className="knowledge-snippets-state">{t('chat:contextModal.noWebSources')}</p>;

  return (
    <>
      {refs.map((ref) => {
        const highlighted = Boolean(targetRef && ref.ref_id === targetRef);
        return (
          <article
            className={`knowledge-snippet-card web-source-card ${highlighted ? 'targeted' : ''}`}
            key={ref.ref_id}
            ref={(element) => {
              if (highlighted) targetRefElement.current = element;
            }}
          >
            <div className="knowledge-snippet-heading web-source-heading">
              <span>{ref.ref_id}</span>
              <div>
                <strong>{ref.title || ref.url || ref.ref_id}</strong>
                <small>{ref.domain || t('chat:contextModal.domain')}</small>
                {ref.url ? <small>{t('chat:contextModal.sourceUrl')}: {ref.url}</small> : null}
              </div>
            </div>
            {ref.snippet_preview || ref.snippet ? <pre className="knowledge-snippet-content">{ref.snippet_preview || ref.snippet}</pre> : null}
            {ref.page_excerpt_preview && ref.page_excerpt_gate_status !== 'rejected' && ref.page_excerpt_gate_status !== 'failed' ? (
              <pre className="knowledge-snippet-content context-content-block">{ref.page_excerpt_preview}</pre>
            ) : null}
            <div className="knowledge-snippet-scores">
              {scoreLabel(t('chat:contextModal.rank'), ref.rank)}
              {ref.candidate_judge_state ? <Chip tone={ref.candidate_judge_state === 'retained' ? 'active' : 'neutral'}>{judgeStateLabel(ref.candidate_judge_state, t)}</Chip> : null}
              {ref.candidate_judge_relevance ? <Chip tone={ref.candidate_judge_relevance === 'high' ? 'active' : 'neutral'}>{t('chat:contextModal.relevance')}: {ref.candidate_judge_relevance}</Chip> : null}
              {ref.candidate_judge_role ? <Chip tone="neutral">{t('chat:contextModal.role')}: {ref.candidate_judge_role}</Chip> : null}
              {ref.candidate_judge_confidence ? <Chip tone={ref.candidate_judge_confidence === 'high' ? 'active' : 'neutral'}>{t('chat:contextModal.confidence')}: {ref.candidate_judge_confidence}</Chip> : null}
              {ref.page_fetch_status ? <Chip tone={pageFetchStatusTone(ref.page_fetch_status)}>{pageFetchStatusLabel(ref.page_fetch_status, t)}</Chip> : null}
              {ref.page_excerpt_gate_status ? <Chip tone={pageExcerptGateStatusTone(ref.page_excerpt_gate_status)}>{pageExcerptGateStatusLabel(ref.page_excerpt_gate_status, t)}</Chip> : null}
              {ref.page_excerpt_quality ? <Chip tone={ref.page_excerpt_quality === 'high' ? 'active' : 'neutral'}>{t('chat:contextModal.quality')}: {ref.page_excerpt_quality}</Chip> : null}
              {ref.page_excerpt_confidence ? <Chip tone={ref.page_excerpt_confidence === 'high' ? 'active' : 'neutral'}>{t('chat:contextModal.confidence')}: {ref.page_excerpt_confidence}</Chip> : null}
              {ref.page_excerpt_coverage ? <Chip tone={ref.page_excerpt_coverage === 'direct_answer' ? 'active' : 'neutral'}>{t('chat:contextModal.coverage')}: {ref.page_excerpt_coverage}</Chip> : null}
              {ref.source ? <span>{t('chat:contextModal.source')}: {ref.source}</span> : null}
              {ref.domain ? <span>{t('chat:contextModal.domain')}: {ref.domain}</span> : null}
              {ref.published_at ? <span>{t('chat:contextModal.published')}: {ref.published_at}</span> : null}
              {ref.page_title ? <span>{t('chat:contextModal.pageTitle')}: {ref.page_title}</span> : null}
              {ref.page_excerpt_chars !== undefined ? <span>{t('chat:contextModal.pageExcerptChars', { count: ref.page_excerpt_chars })}</span> : null}
              {ref.page_excerpt_gate_reason ? <span>{ref.page_excerpt_gate_reason}</span> : null}
              {ref.page_excerpt_gate_warning ? <span>{pageFetchWarningLabel(ref.page_excerpt_gate_warning, t)}</span> : null}
              {ref.candidate_judge_reason ? <span>{ref.candidate_judge_reason}</span> : null}
              {ref.page_fetch_warning ? <span>{pageFetchWarningLabel(ref.page_fetch_warning, t)}</span> : null}
              {ref.url ? (
                <a href={ref.url} target="_blank" rel="noreferrer noopener">
                  <ExternalLink size={12} />
                  {t('chat:contextModal.openSource')}
                </a>
              ) : null}
            </div>
          </article>
        );
      })}
    </>
  );
}

function judgeStateLabel(state: string, t: ReturnType<typeof useTranslation>['t']): string {
  const key = `chat:contextModal.candidateJudgeState.${state}`;
  const label = t(key);
  return label === key ? state : label;
}

function pageFetchStatusTone(status: string): 'neutral' | 'active' | 'warning' | 'danger' {
  if (status === 'fetched') return 'active';
  if (status === 'skipped') return 'neutral';
  if (status === 'timeout' || status === 'unsupported' || status === 'blocked') return 'warning';
  return 'danger';
}

function pageFetchStatusLabel(status: string, t: ReturnType<typeof useTranslation>['t']): string {
  const key = `chat:contextModal.pageFetchStatus.${status}`;
  const label = t(key);
  return label === key ? status : label;
}

function pageFetchWarningLabel(warning: string, t: ReturnType<typeof useTranslation>['t']): string {
  const key = `chat:contextModal.pageFetchWarnings.${warning}`;
  const label = t(key);
  return label === key ? warning : label;
}

function pageExcerptGateStatusTone(status: string): 'neutral' | 'active' | 'warning' | 'danger' {
  if (status === 'accepted') return 'active';
  if (status === 'rejected') return 'warning';
  if (status === 'failed') return 'danger';
  return 'neutral';
}

function pageExcerptGateStatusLabel(status: string, t: ReturnType<typeof useTranslation>['t']): string {
  const key = `chat:contextModal.pageExcerptGateStatus.${status}`;
  const label = t(key);
  return label === key ? status : label;
}

function WarningList({ warnings }: { warnings: string[] }) {
  return (
    <div className="run-step-knowledge-warnings">
      {warnings.map((warning, index) => (
        <span key={`${warning}-${index}`}>{warning}</span>
      ))}
    </div>
  );
}

function contextModalTabs(context: NormalizedContextMetadata): ContextTab[] {
  const tabs: ContextTab[] = [];
  if (context.knowledge?.canViewSnippets) tabs.push('knowledge');
  if (context.worldbook?.injected && context.worldbook.entryRefs.length) tabs.push('worldbook');
  if (context.web?.sourceRefs.length) tabs.push('web');
  if (context.memory?.injected) tabs.push('memory');
  return tabs;
}

function tabLabel(tab: ContextTab, t: ReturnType<typeof useTranslation>['t']): string {
  if (tab === 'memory') return t('chat:contextModal.memory');
  if (tab === 'worldbook') return t('chat:contextModal.worldbookEntries');
  if (tab === 'web') return t('chat:contextModal.webSources');
  return t('chat:contextModal.knowledgeSnippets');
}

function contextModalSubtitle(context: NormalizedContextMetadata, t: ReturnType<typeof useTranslation>['t']): string {
  const parts = [];
  if (context.memory?.injected) parts.push(t('chat:contextModal.memory'));
  if (context.knowledge?.canViewSnippets) parts.push(t('chat:contextModal.snippetsUsed', { count: context.knowledge.snippetRefs.length }));
  if (context.worldbook?.injected && context.worldbook.entryRefs.length) parts.push(t('chat:contextModal.entriesUsed', { count: context.worldbook.entryRefs.length }));
  if (context.web?.sourceRefs.length) parts.push(t('chat:contextModal.webResultsUsed', { count: context.web.sourceRefs.length }));
  return parts.join(' / ');
}

function activationModeLabel(mode: string | undefined, t: ReturnType<typeof useTranslation>['t']): string {
  if (mode === 'always') return t('chat:contextModal.alwaysActive');
  if (mode === 'keyword') return t('chat:contextModal.keywordTriggered');
  return mode || t('chat:contextModal.keywordTriggered');
}

function activationModeTone(mode: string | undefined): 'neutral' | 'active' | 'warning' | 'danger' {
  return mode === 'always' ? 'active' : 'neutral';
}

function normalizeContextMetadata(input: unknown): NormalizedContextMetadata {
  const records = collectContextRecords(input);
  const memoryContexts = records.flatMap((record) => [
    ...plainRecordArray(record.core_memory_contexts),
    ...(isPlainRecord(record.core_memory_context) ? [record.core_memory_context] : []),
  ]);
  const knowledgeContexts = records.flatMap((record) => [
    ...plainRecordArray(record.knowledge_contexts),
    ...(isPlainRecord(record.knowledge_context) ? [record.knowledge_context] : []),
  ]);
  const worldbookContexts = records.flatMap((record) => [
    ...plainRecordArray(record.worldbook_contexts),
    ...(isPlainRecord(record.worldbook_context) ? [record.worldbook_context] : []),
  ]);
  const webContexts = records.flatMap((record) => [
    ...plainRecordArray(record.web_contexts),
    ...(isPlainRecord(record.web_context) ? [record.web_context] : []),
  ]);

  const result: NormalizedContextMetadata = {};
  const memory = mergeMemoryContexts(memoryContexts);
  const knowledge = mergeKnowledgeContexts(knowledgeContexts);
  const worldbook = mergeWorldbookContexts(worldbookContexts);
  const web = mergeWebContexts(webContexts);
  if (memory) result.memory = memory;
  if (knowledge) result.knowledge = knowledge;
  if (worldbook) result.worldbook = worldbook;
  if (web) result.web = web;
  return result;
}

function collectContextRecords(input: unknown): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = [];
  function visit(value: unknown) {
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (!isPlainRecord(value)) return;
    records.push(value);
    if (isPlainRecord(value.message_metadata)) visit(value.message_metadata);
    if (isPlainRecord(value.run_metadata)) visit(value.run_metadata);
    if (Array.isArray(value.steps)) {
      value.steps.forEach((step) => {
        if (isPlainRecord(step)) visit(isPlainRecord(step.metadata) ? step.metadata : step);
      });
    }
    if (isPlainRecord(value.metadata)) visit(value.metadata);
  }
  visit(input);
  return records;
}

function mergeMemoryContexts(contexts: Record<string, unknown>[]): CoreMemoryContextSummary | undefined {
  if (!contexts.length) return undefined;
  const last = contexts[contexts.length - 1];
  return {
    enabled: booleanValue(last.enabled),
    injected: contexts.some((context) => context.injected === true),
    contentChars: maxNumber(contexts.map((context) => numberValue(context.content_chars))),
    skippedReason: textValue(last.skipped_reason),
    warnings: uniqueStrings(contexts.flatMap((context) => stringArray(context.warnings))),
  };
}

function mergeKnowledgeContexts(contexts: Record<string, unknown>[]): KnowledgeContextSummary | undefined {
  if (!contexts.length) return undefined;
  const snippetRefs = dedupeSnippetRefs(contexts.flatMap((context) => knowledgeSnippetRefs(context)));
  const retrievals = contexts.map(knowledgeRetrievalSummary).filter((item): item is KnowledgeRetrievalSummary => Boolean(item));
  const aggregateContext = contexts[contexts.length - 1];
  const retrieval = mergeKnowledgeRetrievalSummaries(retrievals);
  return {
    injected: contexts.some((context) => context.injected === true),
    snippetCount: snippetRefs.length || maxNumber(contexts.map((context) => numberValue(context.result_count))),
    snippetRefs,
    kbNames: uniqueStrings(contexts.flatMap((context) => [
      ...stringArray(context.knowledge_base_names),
      ...stringArray(context.knowledge_base_ids),
    ])),
    rerankerSummary: retrieval ? rerankerLabel(retrieval) : undefined,
    warnings: uniqueStrings(contexts.flatMap((context) => stringArray(context.warnings))),
    canViewSnippets: snippetRefs.length > 0,
    retrieval: retrieval || (aggregateContext ? knowledgeRetrievalSummary(aggregateContext) || undefined : undefined),
  };
}

function mergeWorldbookContexts(contexts: Record<string, unknown>[]): WorldbookContextSummary | undefined {
  if (!contexts.length) return undefined;
  const entryRefs = dedupeWorldbookRefs(contexts.flatMap((context) => worldbookEntryRefs(context)));
  return {
    enabled: contexts.some((context) => context.enabled === true),
    injected: contexts.some((context) => context.injected === true),
    matchedEntryCount: sumNumbers(contexts.map((context) => numberValue(context.matched_entry_count))),
    injectedEntryCount: entryRefs.length || sumNumbers(contexts.map((context) => numberValue(context.injected_entry_count))),
    recursionDepth: maxNumber(contexts.map((context) => numberValue(context.recursion_depth))),
    recursionRoundsUsed: maxNumber(contexts.map((context) => numberValue(context.recursion_rounds_used))),
    entryRefs,
    warnings: uniqueStrings(contexts.flatMap((context) => stringArray(context.warnings))),
  };
}

function mergeWebContexts(contexts: Record<string, unknown>[]): WebContextSummary | undefined {
  if (!contexts.length) return undefined;
  const last = contexts[contexts.length - 1];
  const resolver = firstPlainRecord(contexts.map((context) => context.resolver).reverse());
  const sourceRefs = dedupeWebSourceRefs(contexts.flatMap((context) => webSourceRefs(context)));
  return {
    enabled: booleanValue(last.enabled),
    attempted: contexts.some((context) => context.attempted === true),
    injected: contexts.some((context) => context.injected === true),
    provider: textValue(last.provider),
    resultCount: sourceRefs.length || maxNumber(contexts.map((context) => numberValue(context.result_count))),
    sourceRefs,
    query: textValue(last.query),
    querySource: textValue(last.query_source),
    skippedReason: textValue(last.skipped_reason),
    truncated: contexts.some((context) => context.truncated === true),
    resolverUsed: booleanValue(resolver?.used),
    resolverReason: textValue(resolver?.reason),
    resolverConfidence: textValue(resolver?.confidence),
    searchDiagnostics: mergeWebSearchDiagnostics(contexts.map((context) => context.search_diagnostics)),
    pageFetchEnabled: booleanValue(last.page_fetch_enabled),
    pagesAttempted: maxNumber(contexts.map((context) => numberValue(context.pages_attempted))),
    pagesFetched: maxNumber(contexts.map((context) => numberValue(context.pages_fetched))),
    pagesFailed: maxNumber(contexts.map((context) => numberValue(context.pages_failed))),
    pageFetchWarnings: uniqueStrings(contexts.flatMap((context) => stringArray(context.page_fetch_warnings))),
    pageExcerptGate: mergePageExcerptGate(contexts.map((context) => context.page_excerpt_gate)),
    candidateJudge: mergeWebCandidateJudge(contexts.map((context) => context.candidate_judge)),
    warnings: uniqueStrings(contexts.flatMap((context) => stringArray(context.warnings))),
  };
}

function mergeWebCandidateJudge(values: unknown[]): WebCandidateJudgeSummary | undefined {
  const records = values.filter(isPlainRecord);
  if (!records.length) return undefined;
  const last = records[records.length - 1];
  return {
    enabled: booleanValue(last.enabled),
    used: booleanValue(last.used),
    mode: textValue(last.mode),
    schema: textValue(last.schema),
    candidateCount: numberValue(last.candidate_count),
    retainedCount: numberValue(last.retained_count),
    rejectedCount: numberValue(last.rejected_count),
    unjudgedCount: numberValue(last.unjudged_count),
    invalidItemCount: numberValue(last.invalid_item_count),
    fallbackUsed: booleanValue(last.fallback_used),
    warnings: uniqueStrings(records.flatMap((record) => stringArray(record.warnings))),
  };
}

function mergePageExcerptGate(values: unknown[]): PageExcerptGateSummary | undefined {
  const records = values.filter(isPlainRecord);
  if (!records.length) return undefined;
  const last = records[records.length - 1];
  return {
    enabled: booleanValue(last.enabled),
    backend: textValue(last.backend),
    attempted: numberValue(last.attempted),
    accepted: numberValue(last.accepted),
    rejected: numberValue(last.rejected),
    failed: numberValue(last.failed),
    stoppedReason: textValue(last.stopped_reason),
    warnings: uniqueStrings(records.flatMap((record) => stringArray(record.warnings))),
  };
}

function mergeWebSearchDiagnostics(values: unknown[]): WebSearchContextDiagnostics | undefined {
  const records = values.filter(isPlainRecord);
  if (!records.length) return undefined;
  const filtersApplied = Object.assign({}, ...records.map((record) => isPlainRecord(record.filters_applied) ? record.filters_applied : {}));
  const filteredCount = sumNumbers(records.map((record) => numberValue(record.filtered_count)));
  const dedupedCount = sumNumbers(records.map((record) => numberValue(record.deduped_count)));
  const warnings = uniqueStrings(records.flatMap((record) => stringArray(record.warnings)));
  if (!filteredCount && !dedupedCount && !Object.values(filtersApplied).some(Boolean) && !warnings.length) return undefined;
  return {
    filteredCount,
    dedupedCount,
    filtersApplied: filtersApplied as Record<string, boolean>,
    warnings,
  };
}

function webSourceRefs(context: Record<string, unknown> | undefined): WebSourceRef[] {
  if (!isPlainRecord(context) || !Array.isArray(context.source_refs)) return [];
  const refs: WebSourceRef[] = [];
  context.source_refs.forEach((item, index) => {
    if (!isPlainRecord(item)) return;
    const refId = textValue(item.ref_id) || `W${index + 1}`;
    if (!/^W\d+$/.test(refId)) return;
    refs.push({
      ref_id: refId,
      rank: numberValue(item.rank),
      title: textValue(item.title),
      url: textValue(item.url),
      domain: textValue(item.domain),
      published_at: textValue(item.published_at) || null,
      source: textValue(item.source),
      snippet: textValue(item.snippet),
      snippet_preview: textValue(item.snippet_preview),
      page_fetch_status: textValue(item.page_fetch_status),
      page_title: textValue(item.page_title),
      page_excerpt_preview: textValue(item.page_excerpt_preview),
      page_excerpt_chars: numberValue(item.page_excerpt_chars),
      page_fetch_warning: textValue(item.page_fetch_warning),
      page_excerpt_gate_status: textValue(item.page_excerpt_gate_status),
      page_excerpt_quality: textValue(item.page_excerpt_quality),
      page_excerpt_confidence: textValue(item.page_excerpt_confidence),
      page_excerpt_coverage: textValue(item.page_excerpt_coverage),
      page_excerpt_gate_reason: textValue(item.page_excerpt_gate_reason),
      page_excerpt_gate_warning: textValue(item.page_excerpt_gate_warning),
      page_excerpt_injected: booleanValue(item.page_excerpt_injected),
      candidate_judge_state: textValue(item.candidate_judge_state),
      candidate_judge_relevance: textValue(item.candidate_judge_relevance),
      candidate_judge_role: textValue(item.candidate_judge_role),
      candidate_judge_confidence: textValue(item.candidate_judge_confidence),
      candidate_judge_reason: textValue(item.candidate_judge_reason),
    });
  });
  return refs;
}

function knowledgeSnippetRefs(context: Record<string, unknown> | undefined): KnowledgeSnippetRef[] {
  if (!isPlainRecord(context) || !Array.isArray(context.snippet_refs)) return [];
  const refs: KnowledgeSnippetRef[] = [];
  context.snippet_refs.forEach((item, index) => {
    if (!isPlainRecord(item) || typeof item.chunk_id !== 'string' || !item.chunk_id) return;
    refs.push({
        index: textValue(item.index) || `K${index + 1}`,
        chunk_id: item.chunk_id,
        knowledge_base_id: textValue(item.knowledge_base_id),
        knowledge_base_name: textValue(item.knowledge_base_name),
        source_id: textValue(item.source_id),
        source_title: textValue(item.source_title),
        rank: numberValue(item.rank),
        heading_path: textValue(item.heading_path),
        vector_score: numberValue(item.vector_score),
        keyword_score: numberValue(item.keyword_score),
        rrf_score: numberValue(item.rrf_score),
        rerank_score: numberValue(item.rerank_score),
    });
  });
  return refs;
}

function worldbookEntryRefs(context: Record<string, unknown> | undefined): WorldbookEntryRef[] {
  if (!isPlainRecord(context) || !Array.isArray(context.entry_refs)) return [];
  const refs: WorldbookEntryRef[] = [];
  context.entry_refs.forEach((item, index) => {
    if (!isPlainRecord(item) || typeof item.entry_id !== 'string' || !item.entry_id) return;
    refs.push({
      index: textValue(item.index) || `W${index + 1}`,
      worldbook_id: textValue(item.worldbook_id),
      worldbook_name: textValue(item.worldbook_name),
      entry_id: item.entry_id,
      entry_name: textValue(item.entry_name),
      activation_mode: textValue(item.activation_mode),
      matched_keywords: stringArray(item.matched_keywords),
      matched_by_recursion: booleanValue(item.matched_by_recursion),
      recursion_depth: numberValue(item.recursion_depth),
      injected_index: numberValue(item.injected_index),
      warnings: stringArray(item.warnings),
    });
  });
  return refs;
}

function dedupeSnippetRefs(refs: KnowledgeSnippetRef[]): KnowledgeSnippetRef[] {
  const seen = new Set<string>();
  return refs.filter((ref) => {
    const key = ref.chunk_id || `${ref.index}:${ref.source_id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map((ref, index) => ({ ...ref, index: ref.index || `K${index + 1}` }));
}

function dedupeWorldbookRefs(refs: WorldbookEntryRef[]): WorldbookEntryRef[] {
  const seen = new Set<string>();
  return refs.filter((ref) => {
    const key = ref.entry_id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map((ref, index) => ({ ...ref, index: ref.index || `W${index + 1}` }));
}

function dedupeWebSourceRefs(refs: WebSourceRef[]): WebSourceRef[] {
  const seen = new Set<string>();
  return refs.filter((ref) => {
    const key = ref.ref_id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function scoreLabel(label: string, value: number | undefined): ReactNode {
  if (value === undefined) return null;
  const display = Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
  return <span>{label}: {display}</span>;
}

function knowledgeCitationRefMap(refs: KnowledgeSnippetRef[] | undefined): Map<string, KnowledgeSnippetRef> {
  const result = new Map<string, KnowledgeSnippetRef>();
  (refs || []).forEach((ref, index) => {
    const label = /^K\d+$/.test(ref.index || '') ? ref.index : `K${index + 1}`;
    if (!result.has(label)) result.set(label, { ...ref, index: label });
  });
  return result;
}

function webCitationRefMap(refs: WebSourceRef[] | undefined): Map<string, WebSourceRef> {
  const result = new Map<string, WebSourceRef>();
  (refs || []).forEach((ref, index) => {
    const label = /^W\d+$/.test(ref.ref_id || '') ? ref.ref_id : `W${index + 1}`;
    if (!result.has(label)) result.set(label, { ...ref, ref_id: label });
  });
  return result;
}

function renderKnowledgeCitationChildren({
  children,
  refsByLabel,
  webRefsByLabel,
  onOpen,
  onOpenWeb,
  openLabel,
  openRangeLabel,
  openWebLabel,
}: {
  children: ReactNode;
  refsByLabel: Map<string, KnowledgeSnippetRef>;
  webRefsByLabel?: Map<string, WebSourceRef>;
  onOpen: (selection: KnowledgeCitationSelection) => void;
  onOpenWeb?: (refId: string) => void;
  openLabel: (label: string) => string;
  openRangeLabel: (labels: string) => string;
  openWebLabel?: (label: string) => string;
}): ReactNode {
  return Children.map(children, (child) => renderKnowledgeCitationNode(child, refsByLabel, webRefsByLabel, onOpen, onOpenWeb, openLabel, openRangeLabel, openWebLabel));
}

function renderKnowledgeCitationNode(
  node: ReactNode,
  refsByLabel: Map<string, KnowledgeSnippetRef>,
  webRefsByLabel: Map<string, WebSourceRef> | undefined,
  onOpen: (selection: KnowledgeCitationSelection) => void,
  onOpenWeb: ((refId: string) => void) | undefined,
  openLabel: (label: string) => string,
  openRangeLabel: (labels: string) => string,
  openWebLabel: ((label: string) => string) | undefined,
): ReactNode {
  if (typeof node === 'string') return splitKnowledgeCitationText(node, refsByLabel, webRefsByLabel, onOpen, onOpenWeb, openLabel, openRangeLabel, openWebLabel);
  if (!isValidElement(node)) return node;
  if (typeof node.type === 'string' && ['a', 'code', 'pre'].includes(node.type)) return node;
  const props = node.props as { children?: ReactNode };
  if (!props.children) return node;
  return cloneElement(
    node as ReactElement<{ children?: ReactNode }>,
    undefined,
    renderKnowledgeCitationChildren({ children: props.children, refsByLabel, webRefsByLabel, onOpen, onOpenWeb, openLabel, openRangeLabel, openWebLabel }),
  );
}

function splitKnowledgeCitationText(
  text: string,
  refsByLabel: Map<string, KnowledgeSnippetRef>,
  webRefsByLabel: Map<string, WebSourceRef> | undefined,
  onOpen: (selection: KnowledgeCitationSelection) => void,
  onOpenWeb: ((refId: string) => void) | undefined,
  openLabel: (label: string) => string,
  openRangeLabel: (labels: string) => string,
  openWebLabel: ((label: string) => string) | undefined,
): ReactNode {
  const tokenPattern = /\[(?:K\d+(?:\s*(?:,|-|–)\s*K\d+)*|W\d+)\]/g;
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(text))) {
    const token = match[0];
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    const webLabel = token.match(/^\[(W\d+)\]$/)?.[1];
    if (webLabel && webRefsByLabel?.has(webLabel) && onOpenWeb) {
      const ariaLabel = openWebLabel?.(webLabel) || webLabel;
      parts.push(
        <button
          key={`${token}:${match.index}`}
          type="button"
          className="knowledge-citation-badge web-citation-badge"
          aria-label={ariaLabel}
          title={ariaLabel}
          onClick={() => onOpenWeb(webLabel)}
        >
          {token}
        </button>,
      );
    } else {
      const parsed = parseKnowledgeCitationToken(token);
      if (!parsed) {
        parts.push(token);
      } else {
      const refs = parsed.labels.map((label) => refsByLabel.get(label)).filter((ref): ref is KnowledgeSnippetRef => Boolean(ref));
      const missingLabels = parsed.labels.filter((label) => !refsByLabel.has(label));
      if (!refs.length) {
        parts.push(token);
      } else {
        const ariaLabel = parsed.labels.length === 1 ? openLabel(parsed.labels[0]) : openRangeLabel(parsed.labels.join(', '));
        parts.push(
          <button
            key={`${token}:${match.index}`}
            type="button"
            className="knowledge-citation-badge"
            aria-label={ariaLabel}
            title={ariaLabel}
            onClick={() => onOpen({ token, labels: parsed.labels, refs, missingLabels })}
          >
            {token}
          </button>,
        );
      }
      }
    }
    lastIndex = match.index + token.length;
  }

  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length ? parts : text;
}

function ThoughtBlock({ content, streaming }: { content: string; streaming: boolean }) {
  const { t } = useTranslation(['renderers']);
  const [expanded, setExpanded] = useState(false);
  const contentRef = useRef<HTMLPreElement | null>(null);
  const autoScrollRef = useRef(true);

  useLayoutEffect(() => {
    if (!expanded || !streaming || !autoScrollRef.current) return;
    const container = contentRef.current;
    if (!container) return;
    window.requestAnimationFrame(() => {
      if (!autoScrollRef.current) return;
      container.scrollTop = container.scrollHeight;
    });
  }, [content, expanded, streaming]);

  function toggleExpanded() {
    setExpanded((current) => {
      const next = !current;
      if (next) autoScrollRef.current = true;
      return next;
    });
  }

  function handleThoughtScroll() {
    const container = contentRef.current;
    if (!container) return;
    autoScrollRef.current = container.scrollHeight - container.scrollTop - container.clientHeight < 160;
  }

  return (
    <section className={`thought-block ${expanded ? 'expanded' : ''}`}>
      <button className="thought-toggle" type="button" onClick={toggleExpanded} aria-expanded={expanded}>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span>{t('renderers:labels.thought')}</span>
        {streaming ? <small>{t('renderers:labels.thinking')}</small> : null}
      </button>
      {expanded ? (
        <pre className="thought-content" ref={contentRef} onScroll={handleThoughtScroll}>
          {content}
        </pre>
      ) : null}
    </section>
  );
}

function RunStepsPanel({ run, steps, runKnowledge, forceExpanded = false }: { run?: Run; steps: RunStep[]; runKnowledge?: KnowledgeRetrievalSummary | null; forceExpanded?: boolean }) {
  const { t } = useTranslation(['runs']);
  const cancelActiveRun = useWorkbenchStore((state) => state.cancelActiveRun);
  const activeRunId = useWorkbenchStore((state) => state.activeRunId);
  const expandedByRunId = useWorkbenchStore((state) => state.runStepsExpandedByRunId);
  const setRunStepsExpanded = useWorkbenchStore((state) => state.setRunStepsExpanded);
  const [, setNowTick] = useState(0);
  const active = run ? isActiveRunStatus(run.status) : steps.some((step) => step.status === 'running');
  const failed = run?.status === 'FAILED' || steps.some((step) => step.status === 'failed');
  const runId = run?.run_id || steps[0]?.run_id || '';
  const hasManualExpanded = Boolean(runId && Object.prototype.hasOwnProperty.call(expandedByRunId, runId));
  const expanded = hasManualExpanded ? expandedByRunId[runId] : forceExpanded || defaultRunStepsExpanded(run);
  const compactActive = active && !expanded && !hasManualExpanded && !forceExpanded;
  const compactFailed = failed && !expanded && !hasManualExpanded && !forceExpanded;
  const hasRunningStep = steps.some((step) => step.status === 'running' && step.started_at);

  useEffect(() => {
    if (!hasRunningStep) return;
    const interval = window.setInterval(() => setNowTick((current) => current + 1), 1000);
    return () => window.clearInterval(interval);
  }, [hasRunningStep]);

  if (!steps.length && !run && !runKnowledge) return null;
  const duration = runDurationLabel(run, steps);
  const progressSummary = run?.progress_total && run.progress_current !== undefined && run.progress_current !== null ? `${run.progress_current} / ${run.progress_total}` : '';
  const stepSummary = progressSummary || (steps.length ? t('runs:panel.stepCount', { count: steps.length }) : getRunStatusLabel(run?.status, t));
  const displaySummary = duration ? t('runs:panel.withDuration', { summary: stepSummary, duration }) : stepSummary;
  const canCancel = Boolean(run?.run_id && (activeRunId === run.run_id || active) && !run.cancel_requested && run.status !== 'CANCELLING');
  const stepTree = buildRunStepTree(steps);
  const activeStep = compactActive ? activeRunStep(stepTree) : null;
  const failedStep = compactFailed ? failedRunStep(stepTree, run, getRunStatusLabel(run?.status, t)) : null;

  return (
    <section className={`run-steps-panel ${expanded ? 'expanded' : compactActive || compactFailed ? 'compact-active' : 'collapsed'} ${failed ? 'failed' : ''}`}>
      <div className="run-steps-header">
        <button type="button" onClick={() => (runId ? setRunStepsExpanded(runId, !expanded) : undefined)} aria-expanded={expanded}>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span>{t('runs:panel.title')}: {displaySummary}</span>
        </button>
        {run?.status === 'CANCELLING' ? <small>{t('runs:panel.cancelling')}</small> : null}
        {canCancel ? (
          <button type="button" className="run-steps-stop" onClick={() => void cancelActiveRun()}>
            {t('runs:panel.stop')}
          </button>
        ) : null}
      </div>
      {expanded ? (
        <>
          {steps.length ? (
            <ol className="run-step-list">
              {stepTree.map((step) => <RunStepTreeItem step={step} key={step.step_id} depth={0} runKnowledge={runKnowledge} />)}
            </ol>
          ) : null}
        </>
      ) : compactActive && activeStep ? (
        <ol className="run-step-list run-step-active-list">
          <RunStepTreeItem step={activeStep} key={activeStep.step_id} depth={0} runKnowledge={runKnowledge} compact />
        </ol>
      ) : compactFailed && failedStep ? (
        <ol className="run-step-list run-step-active-list">
          <RunStepTreeItem step={failedStep} key={failedStep.step_id} depth={0} runKnowledge={runKnowledge} compact />
        </ol>
      ) : null}
    </section>
  );
}

function DebugRow({ label, value, wide = false }: { label: string; value: ReactNode; wide?: boolean }) {
  if (value === undefined || value === null || value === '') return null;
  return (
    <div className={wide ? 'wide' : undefined}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function RunStepTreeItem({ step, depth, runKnowledge, compact = false }: { step: RunStepNode; depth: number; runKnowledge?: KnowledgeRetrievalSummary | null; compact?: boolean }) {
  const { t } = useTranslation(['runs']);
  const duration = stepDurationLabel(step);
  const contextSummary = contextSummaryForStep(step, runKnowledge);
  const message = stepMessage(step, t);
  return (
    <li className={`run-step-item ${step.status} depth-${Math.min(depth, 4)}`}>
      <div className="run-step-row">
        <RunStepIcon status={step.status} />
        <span>
          <strong>{getRunStepLabel(step.label, t)}{duration ? ` / ${duration}` : ''}</strong>
          {message ? <small>{message}</small> : null}
        </span>
      </div>
      {contextSummary ? (
        <div className="run-step-knowledge-list">
          <ContextInjectedBlock summary={contextSummary} />
        </div>
      ) : null}
      {!compact && step.children.length ? (
        <ol className="run-step-children">
          {step.children.map((child) => <RunStepTreeItem step={child} key={child.step_id} depth={depth + 1} runKnowledge={runKnowledge} />)}
        </ol>
      ) : null}
    </li>
  );
}

function ContextInjectedBlock({ summary }: { summary: NormalizedContextMetadata }) {
  const { t } = useTranslation(['runs']);
  const knowledge = summary.knowledge?.retrieval;
  const warningCount = (summary.memory?.warnings.length || 0) + (summary.worldbook?.warnings.length || 0) + (summary.knowledge?.warnings.length || 0) + (summary.web?.warnings.length || 0);
  return (
    <div className="run-step-knowledge" aria-label={t('runs:contextSummary.title')}>
      <strong>{t('runs:contextSummary.title')}</strong>
      <div className="run-step-knowledge-grid">
        {summary.memory ? <DebugRow label={t('runs:contextSummary.memory')} value={memorySummaryLabel(summary.memory, t)} wide /> : null}
        {summary.worldbook ? <DebugRow label={t('runs:contextSummary.worldbook')} value={worldbookSummaryLabel(summary.worldbook, t)} wide /> : null}
        {knowledge || summary.knowledge ? <DebugRow label={t('runs:contextSummary.knowledge')} value={knowledgeSummaryLabel(summary.knowledge, t)} wide /> : null}
        {summary.web ? <DebugRow label={t('runs:contextSummary.web')} value={webSummaryLabel(summary.web, t)} wide /> : null}
        {knowledge?.kbLabels.length ? <DebugRow label={t('runs:contextSummary.kb')} value={knowledge.kbLabels.join(', ')} wide /> : null}
        {knowledge ? <DebugRow label={t('runs:contextSummary.embedding')} value={embeddingSummaryLabel(knowledge)} /> : null}
        {knowledge ? <DebugRow label={t('runs:contextSummary.vector')} value={knowledge.vectorCandidateCount} /> : null}
        {knowledge ? <DebugRow label={t('runs:contextSummary.keyword')} value={knowledge.keywordCandidateCount} /> : null}
        {knowledge ? <DebugRow label={t('runs:contextSummary.merged')} value={knowledge.mergedCandidateCount} /> : null}
        {knowledge ? <DebugRow label={t('runs:contextSummary.reranker')} value={rerankerLabel(knowledge, t)} /> : null}
        {warningCount ? <DebugRow label={t('runs:contextSummary.warnings')} value={warningCount} /> : null}
      </div>
      {warningCount ? (
        <div className="run-step-knowledge-warnings">
          {[...(summary.memory?.warnings || []), ...(summary.worldbook?.warnings || []), ...(summary.knowledge?.warnings || []), ...(summary.web?.warnings || [])].map((warning, index) => (
            <span key={`${warning}-${index}`}>{warning}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RunStepIcon({ status }: { status: string }) {
  if (status === 'completed') return <Check size={13} />;
  if (status === 'failed') return <XCircle size={13} />;
  if (status === 'running') return <Loader2 size={13} className="spin" />;
  if (status === 'skipped') return <Minus size={13} />;
  return <Circle size={12} />;
}

function messageRunSteps(message: Message): RunStep[] {
  return sortRunSteps([...(message.run_steps || message.run?.steps || [])]);
}

function stepMessage(step: RunStep, t: ReturnType<typeof useTranslation>['t']): string {
  if (step.status === 'failed') return step.error_message || step.message || 'failed';
  const intent = isPlainRecord(step.metadata?.intent_routing) ? step.metadata.intent_routing : undefined;
  if (intent?.web_context_usage === 'used_for_web_context') {
    return t('runs:stepMessages.intentUsedForWebContext', { intent: textValue(intent.predicted_intent) || 'web_query' });
  }
  const webPlan = isPlainRecord(step.metadata?.web_context_plan) ? step.metadata.web_context_plan : undefined;
  if (webPlan) return webContextPlanStepMessage(webPlan, t);
  return step.message || '';
}

function isActiveRunStatus(status: string): boolean {
  return ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(status);
}

function defaultRunStepsExpanded(run?: Run): boolean {
  if (!run) return false;
  return false;
}

function runDurationLabel(run: Run | undefined, steps: RunStep[]): string {
  const start = run?.started_at || steps.find((step) => step.started_at)?.started_at || run?.created_at;
  const end = run?.finished_at || (run && isActiveRunStatus(run.status) ? new Date().toISOString() : run?.updated_at);
  if (!start || !end) return '';
  const ms = parseDateMs(end) - parseDateMs(start);
  if (!Number.isFinite(ms) || ms < 0) return '';
  return formatDurationMs(ms);
}

function stepDurationLabel(step: RunStep): string {
  if (!step.started_at) return '';
  if (step.status === 'pending' || step.status === 'skipped') return '';
  const end = step.finished_at || (step.status === 'running' ? new Date().toISOString() : '');
  if (!end) return '';
  const ms = parseDateMs(end) - parseDateMs(step.started_at);
  if (!Number.isFinite(ms) || ms < 0) return '';
  return formatDurationMs(ms);
}

function formatDurationSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  return `${seconds.toFixed(2)}s`;
}

function formatDurationMs(ms: number): string {
  return formatDurationSeconds(ms / 1000);
}

function parseDateMs(value: string): number {
  const ms = parseServerTime(value).getTime();
  return Number.isNaN(ms) ? Number.NaN : ms;
}

function sortRunSteps(steps: RunStep[]): RunStep[] {
  return steps.sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || parseDateMs(a.started_at || a.created_at) - parseDateMs(b.started_at || b.created_at));
}

function buildRunStepTree(steps: RunStep[]): RunStepNode[] {
  const nodes = sortRunSteps([...steps]).map((step) => ({ ...step, children: [] as RunStepNode[] }));
  const byId = new Map(nodes.map((node) => [node.step_id, node]));
  const roots: RunStepNode[] = [];
  for (const node of nodes) {
    const parentId = node.parent_step_id || '';
    const parent = parentId ? byId.get(parentId) : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

function activeRunStep(roots: RunStepNode[]): RunStepNode | null {
  const nodes = flattenRunStepTree(roots);
  const running = nodes.filter((item) => item.step.status === 'running');
  if (running.length) return mostSpecificRecentStep(running);
  const pending = nodes.filter((item) => item.step.status === 'pending');
  if (pending.length) return mostRecentStep(pending);
  const latest = mostRecentStep(nodes);
  return latest;
}

function failedRunStep(roots: RunStepNode[], run: Run | undefined, fallbackLabel: string): RunStepNode | null {
  const nodes = flattenRunStepTree(roots);
  const failed = nodes.filter((item) => item.step.status === 'failed');
  if (failed.length) return mostSpecificRecentStep(failed);
  const message = run?.error_message || run?.error || '';
  const label = run?.current_step || run?.stage || fallbackLabel || run?.status || '';
  if (run && (message || label)) {
    return {
      step_id: `${run.run_id}:failed-summary`,
      run_id: run.run_id,
      label,
      status: 'failed',
      message,
      order: Number.MAX_SAFE_INTEGER,
      error_code: run.error_code || undefined,
      error_message: message || undefined,
      created_at: run.created_at,
      updated_at: run.updated_at,
      started_at: run.started_at,
      finished_at: run.finished_at,
      metadata: {},
      children: [],
    };
  }
  return mostRecentStep(nodes);
}

function flattenRunStepTree(roots: RunStepNode[], depth = 0): { step: RunStepNode; depth: number }[] {
  return roots.flatMap((step) => [{ step, depth }, ...flattenRunStepTree(step.children, depth + 1)]);
}

function mostSpecificRecentStep(items: { step: RunStepNode; depth: number }[]): RunStepNode {
  return [...items].sort((a, b) => b.depth - a.depth || compareRunStepRecency(b.step, a.step))[0].step;
}

function mostRecentStep(items: { step: RunStepNode; depth: number }[]): RunStepNode | null {
  return [...items].sort((a, b) => compareRunStepRecency(b.step, a.step) || b.depth - a.depth)[0]?.step || null;
}

function compareRunStepRecency(a: RunStep, b: RunStep): number {
  const aTime = parseDateMs(a.updated_at || a.finished_at || a.started_at || a.created_at);
  const bTime = parseDateMs(b.updated_at || b.finished_at || b.started_at || b.created_at);
  const safeATime = Number.isFinite(aTime) ? aTime : 0;
  const safeBTime = Number.isFinite(bTime) ? bTime : 0;
  return safeATime - safeBTime || (a.order ?? 0) - (b.order ?? 0);
}

function MessageHeader({
  message,
  agent,
  agentName,
  kind,
  modelLabel,
  modelMismatch,
}: {
  message: Message;
  agent?: Agent;
  agentName?: string;
  kind: 'user' | 'agent' | 'command';
  modelLabel?: string;
  modelMismatch?: boolean;
}) {
  const name = kind === 'user' ? 'You' : message.command_name || message.speaker_name || agentName || agent?.name || message.agent_id || 'Assistant';
  const action = message.action_id && message.action_id !== 'default' ? message.action_id : '';
  const secondary = modelLabel || action;

  return (
    <div className="message-meta">
      <div className="message-title">
        <span>{name}</span>
        {secondary ? <small className={modelMismatch ? 'model-mismatch' : undefined} title={modelTitle(message) || secondary}>{modelMismatch ? '! ' : ''}{truncateLabel(secondary)}</small> : null}
      </div>
      <time>{formatMessageTime(message.created_at)}</time>
    </div>
  );
}

function SystemEventSeparator({ message }: { message: Message }) {
  return (
    <article className="message-row system event">
      <div className="system-event-separator">{copyableMessageContent(message)}</div>
    </article>
  );
}

function InlineErrorBlock({ message }: { message: Message }) {
  const { t } = useTranslation(['errors', 'common', 'chat']);
  const error = normalizeError(message);
  const displayError = formatApiError({ code: error.code || 'RUN_FAILED', message: error.message }, t, t('errors:RUN_FAILED'));
  const dismissNotification = useWorkbenchStore((state) => state.dismissNotification);
  const setError = useWorkbenchStore((state) => state.setError);
  const pendingMessageActionId = useWorkbenchStore((state) => state.pendingMessageActionId);
  const storeRun = useWorkbenchStore((state) => (message.run_id ? state.runsById[message.run_id] : undefined));
  const storeRunSteps = useWorkbenchStore((state) => (message.run_id ? state.stepsByRunId[message.run_id] : undefined));
  const [copied, setCopied] = useState(false);
  const operationPending = pendingMessageActionId === message.message_id;
  const canDismiss = message.message_id.startsWith('run-error:') || message.metadata?.notification === true;
  const runSteps = storeRunSteps || messageRunSteps(message);

  async function copyNotification() {
    try {
      await navigator.clipboard.writeText(`${error.code || 'Notification'}: ${error.message || ''}`.trim());
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1300);
    } catch (copyError) {
      setError(copyError, 'Failed to copy notification');
    }
  }

  return (
    <article className="message-row system">
      <div className="system-notification-stack">
        <div className="inline-error-block">
          <CircleAlert size={16} />
          <div>
            <strong>{displayError.code || t('errors:RUN_FAILED')}</strong>
            <p>{displayError.message || t('errors:RUN_FAILED')}</p>
          </div>
        </div>
        <RunStepsPanel run={storeRun || message.run} steps={runSteps} forceExpanded />
        <div className="message-hover-actions system-notification-actions" aria-label={t('chat:actions.notificationActions', { defaultValue: 'Notification actions' })}>
          <button type="button" onClick={() => void copyNotification()} disabled={operationPending} title={t('common:copy')}>
            {copied ? <Check size={13} /> : <Copy size={13} />}
            {copied ? <span>{t('chat:actions.copied')}</span> : ''}
          </button>
          {canDismiss ? (
            <button type="button" className="danger" onClick={() => void dismissNotification(message.message_id)} disabled={operationPending} title={t('common:delete')}>
              <Trash2 size={13} />
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function MessageContent({
  message,
  kind,
  contextMetadata,
  onOpenKnowledgeCitation,
  onOpenWebCitation,
  onPreviewImage,
  onPreviewFile,
}: {
  message: Message;
  kind: 'user' | 'agent' | 'command';
  contextMetadata: NormalizedContextMetadata;
  onOpenKnowledgeCitation: (selection: KnowledgeCitationSelection) => void;
  onOpenWebCitation: (refId: string) => void;
  onPreviewImage: (image: ImagePreview) => void;
  onPreviewFile: (file: FilePreview) => void;
}) {
  if (hasErrorPart(message) || message.metadata?.success === false) {
    return <MessageErrorCard message={message} />;
  }
  if (kind === 'user') {
    return <UserMessageRenderer content={copyableMessageContent(message)} attachments={messageAttachments(message)} onPreviewImage={onPreviewImage} onPreviewFile={onPreviewFile} />;
  }
  const citationRefs = kind === 'agent' ? contextMetadata.knowledge?.snippetRefs : undefined;
  const webCitationRefs = kind === 'agent' ? contextMetadata.web?.sourceRefs : undefined;
  return (
    <MessagePartsRenderer
      parts={message.parts}
      message={message}
      renderMarkdown={(text) => <MarkdownRenderer content={text} knowledgeSnippetRefs={citationRefs} webSourceRefs={webCitationRefs} onOpenKnowledgeCitation={onOpenKnowledgeCitation} onOpenWebCitation={onOpenWebCitation} />}
      renderPlainText={(text) => <PlainTextRenderer content={text} />}
      renderJson={(data) => <JsonRenderer content={data} />}
      renderFile={(payload) => <FileContentRenderer payload={payload} />}
      renderImage={(image) => <ImageRenderer image={image} onPreviewImage={onPreviewImage} />}
      renderImageGallery={(images) => <ImageGalleryRenderer images={images} onPreviewImage={onPreviewImage} />}
      renderForm={(form, blockIndex) => <ActionFormRenderer form={form} messageId={message.message_id} blockIndex={blockIndex} />}
      renderCommandButtons={(block) => <CommandButtonsRenderer block={block} />}
    />
  );
}

function MessageErrorCard({ message }: { message: Message }) {
  const { t } = useTranslation(['errors']);
  const error = normalizeError(message);
  const displayError = formatApiError({ code: error.code || 'RUN_FAILED', message: error.message }, t, t('errors:RUN_FAILED'));
  const title = displayError.code || (message.speaker_type === 'capability' ? 'Command failed' : 'Agent failed');
  return (
    <div className="inline-error-block message-error-card">
      <CircleAlert size={16} />
      <div>
        <strong>{title}</strong>
        <p>{displayError.message || copyableMessageContent(message) || t('errors:RUN_FAILED')}</p>
      </div>
    </div>
  );
}

export function PlainTextRenderer({ content }: { content: unknown }) {
  return <div className="message-content plain-text">{contentToText(content)}</div>;
}

function UserMessageRenderer({ content, attachments, onPreviewImage, onPreviewFile }: { content: unknown; attachments: Attachment[]; onPreviewImage: (image: ImagePreview) => void; onPreviewFile: (file: FilePreview) => void }) {
  const { t } = useTranslation(['renderers']);
  const text = contentToText(content);
  const collapsible = shouldCollapseUserMessage(text);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setExpanded(false);
  }, [text]);

  return (
    <div className="user-message-content">
      {attachments.length ? <AttachmentGallery attachments={attachments} onPreviewImage={onPreviewImage} onPreviewFile={onPreviewFile} /> : null}
      {text ? <div className={`message-content plain-text ${collapsible && !expanded ? 'collapsed-user-content' : ''}`}>{text}</div> : null}
      {collapsible ? (
        <button className="message-expand-button" type="button" onClick={() => setExpanded((current) => !current)}>
          {expanded ? t('renderers:actions.showLess') : t('renderers:actions.showMore')}
        </button>
      ) : null}
    </div>
  );
}

function AttachmentGallery({ attachments, onPreviewImage, onPreviewFile }: { attachments: Attachment[]; onPreviewImage: (image: ImagePreview) => void; onPreviewFile: (file: FilePreview) => void }) {
  const { t } = useTranslation(['renderers']);
  return (
    <div className={`message-attachments ${attachments.length === 1 ? 'single' : 'multi'}`}>
      {attachments.map((attachment) =>
        attachment.type === 'image' ? (
          <figure className="message-attachment" key={attachment.id}>
            <button className="message-image-preview-trigger" type="button" onClick={() => onPreviewImage({ url: attachmentUrl(attachment), alt: attachment.name || t('renderers:labels.attachedImage'), title: attachment.name })}>
              <img src={attachmentUrl(attachment)} alt={attachment.name || t('renderers:labels.attachedImage')} loading="lazy" />
            </button>
          </figure>
        ) : attachment.type === 'file' ? (
          <button
            className="message-file-chip"
            key={attachment.id}
            type="button"
            onClick={() => {
              const url = resolveAttachmentUrl(attachment);
              if (url) {
                onPreviewFile({
                  url,
                  name: attachment.name || t('renderers:labels.file'),
                  mime_type: attachment.mime_type,
                  size: attachment.size,
                  language: languageForFilename(attachment.name),
                });
              }
            }}
            title={isPreviewableFile(attachment) ? t('renderers:actions.preview', { name: attachment.name }) : t('renderers:actions.previewUnavailable')}
            disabled={!isPreviewableFile(attachment) || !resolveAttachmentUrl(attachment)}
          >
            <FileText size={18} />
            <span>
              <strong>{attachment.name || t('renderers:labels.file')}</strong>
              <small>{fileKindLabel(attachment.mime_type, attachment.name)} / {formatBytes(attachment.size)}</small>
            </span>
          </button>
        ) : null,
      )}
    </div>
  );
}

export function MarkdownRenderer({
  content,
  knowledgeSnippetRefs,
  webSourceRefs,
  onOpenKnowledgeCitation,
  onOpenWebCitation,
}: {
  content: unknown;
  knowledgeSnippetRefs?: KnowledgeSnippetRef[];
  webSourceRefs?: WebSourceRef[];
  onOpenKnowledgeCitation?: (selection: KnowledgeCitationSelection) => void;
  onOpenWebCitation?: (refId: string) => void;
}) {
  const { t } = useTranslation(['chat']);
  const markdown = contentToText(content);
  const refsByLabel = knowledgeSnippetRefs?.length ? knowledgeCitationRefMap(knowledgeSnippetRefs) : new Map<string, KnowledgeSnippetRef>();
  const webRefsByLabel = webSourceRefs?.length ? webCitationRefMap(webSourceRefs) : undefined;
  const hasKnowledgeCitations = refsByLabel.size > 0 && Boolean(onOpenKnowledgeCitation);
  const hasWebCitations = Boolean(webRefsByLabel?.size && onOpenWebCitation);
  const hasCitations = hasKnowledgeCitations || hasWebCitations;
  const renderCitationText = hasCitations
    ? (children: ReactNode) => renderKnowledgeCitationChildren({
        children,
        refsByLabel,
        webRefsByLabel,
        onOpen: onOpenKnowledgeCitation || (() => undefined),
        onOpenWeb: onOpenWebCitation,
        openLabel: (label) => t('chat:citations.openSnippet', { label }),
        openRangeLabel: (labels) => t('chat:citations.openSnippets', { labels }),
        openWebLabel: (label) => t('chat:citations.openWebSource', { label }),
      })
    : undefined;
  const citationComponents = hasCitations && renderCitationText
    ? {
        p: ({ children, ...props }: { children?: ReactNode }) => (
          <p {...props}>{renderCitationText?.(children)}</p>
        ),
        li: ({ children, ...props }: { children?: ReactNode }) => (
          <li {...props}>{renderCitationText?.(children)}</li>
        ),
        blockquote: ({ children, ...props }: { children?: ReactNode }) => (
          <blockquote {...props}>{renderCitationText?.(children)}</blockquote>
        ),
        h1: ({ children, ...props }: { children?: ReactNode }) => <h1 {...props}>{renderCitationText?.(children)}</h1>,
        h2: ({ children, ...props }: { children?: ReactNode }) => <h2 {...props}>{renderCitationText?.(children)}</h2>,
        h3: ({ children, ...props }: { children?: ReactNode }) => <h3 {...props}>{renderCitationText?.(children)}</h3>,
        h4: ({ children, ...props }: { children?: ReactNode }) => <h4 {...props}>{renderCitationText?.(children)}</h4>,
        h5: ({ children, ...props }: { children?: ReactNode }) => <h5 {...props}>{renderCitationText?.(children)}</h5>,
        h6: ({ children, ...props }: { children?: ReactNode }) => <h6 {...props}>{renderCitationText?.(children)}</h6>,
        td: ({ children, ...props }: { children?: ReactNode }) => <td {...props}>{renderCitationText?.(children)}</td>,
        th: ({ children, ...props }: { children?: ReactNode }) => <th {...props}>{renderCitationText?.(children)}</th>,
      }
    : undefined;
  try {
    return (
      <div className="message-content markdown-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={citationComponents}>{markdown}</ReactMarkdown>
      </div>
    );
  } catch {
    return <PlainTextRenderer content={markdown} />;
  }
}

export function JsonRenderer({ content }: { content: unknown }) {
  const parsed = normalizeJsonContent(content);
  const webSearch = normalizeWebSearchResponse(parsed);
  if (webSearch) {
    return <WebSearchRenderer response={webSearch} />;
  }
  const kbSearch = normalizeKbSearchResponse(parsed);
  if (kbSearch) {
    return <KbSearchRenderer response={kbSearch} />;
  }
  if (typeof parsed === 'string') {
    return <pre className="message-content json-content">{parsed}</pre>;
  }
  return <pre className="message-content json-content">{JSON.stringify(parsed, null, 2)}</pre>;
}

function WebSearchRenderer({ response }: { response: WebSearchResponse }) {
  const { t } = useTranslation(['renderers']);
  const provider = response.provider || 'searxng';
  const warnings = response.warnings.filter((warning) => warning.trim().length > 0);

  return (
    <section className="message-content web-search-card">
      <header>
        <Search size={15} />
        <div>
          <strong>{t('renderers:webSearch.title')}</strong>
          <span>
            {response.query ? response.query : null}
            {response.query && provider ? ' / ' : null}
            {provider ? `${t('renderers:webSearch.provider')}: ${provider}` : null}
          </span>
        </div>
      </header>
      {!response.results.length ? (
        <div className="web-search-empty">{t('renderers:webSearch.noResults')}</div>
      ) : (
        <ol className="web-search-results">
          {response.results.map((result, index) => {
            const url = safeHttpUrl(result.url);
            const title = result.title || result.url || t('renderers:webSearch.untitledResult');
            return (
              <li key={`${result.rank || index}:${result.url || title}`}>
                <div className="web-search-rank">{result.rank || index + 1}</div>
                <div className="web-search-result-body">
                  <div className="web-search-result-heading">
                    <strong>{title}</strong>
                    {result.domain ? <span title={t('renderers:webSearch.domain')}>{result.domain}</span> : null}
                  </div>
                  {url ? (
                    <a className="web-search-url" href={url} target="_blank" rel="noreferrer" title={t('renderers:webSearch.openResult')}>
                      <ExternalLink size={12} />
                      <span>{url}</span>
                    </a>
                  ) : result.url ? (
                    <small className="web-search-url">{result.url}</small>
                  ) : null}
                  {result.snippet ? <p>{result.snippet}</p> : null}
                  <div className="web-search-meta-row">
                    {result.source ? <span>{result.source}</span> : null}
                    {result.published_at ? <span>{t('renderers:webSearch.published')}: {result.published_at}</span> : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {warnings.length ? (
        <div className="web-search-warnings">
          <strong>{t('renderers:webSearch.warnings')}</strong>
          {warnings.map((warning, index) => (
            <span key={`${warning}-${index}`}>{warning}</span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function KbSearchRenderer({ response }: { response: KbSearchResponse }) {
  const { t } = useTranslation(['renderers']);
  const [debugOpen, setDebugOpen] = useState(false);
  const errorMessage = response.error?.message;

  if (errorMessage) {
    return (
      <section className="message-content kb-search-card error">
        <header>
          <CircleAlert size={15} />
          <strong>{t('renderers:knowledgeSearch.failed')}</strong>
        </header>
        <p>{errorMessage}</p>
      </section>
    );
  }

  return (
    <section className="message-content kb-search-card">
      <header>
        <Search size={15} />
        <div>
          <strong>{t('renderers:knowledgeSearch.title')}</strong>
          {response.query ? <span>{response.query}</span> : null}
        </div>
      </header>
      {!response.results.length ? (
        <div className="kb-search-empty">{t('renderers:knowledgeSearch.noResults')}</div>
      ) : (
        <ol className="kb-search-results">
          {response.results.map((result, index) => (
            <li key={`${result.rank || index}:${result.knowledge_base_id || ''}:${result.source_id || ''}`}>
              <div className="kb-search-rank">{result.rank || index + 1}</div>
              <div className="kb-search-result-body">
                <div className="kb-search-result-heading">
                  <strong>{result.title || result.source_id || t('renderers:knowledgeSearch.untitledSource')}</strong>
                  <span>{result.knowledge_base_name || result.knowledge_base_id || t('renderers:knowledgeSearch.knowledgeBase')}</span>
                </div>
                {result.heading_path ? <small>{result.heading_path}</small> : null}
                <p>{result.content || ''}</p>
                <div className="kb-search-score-row">
                  {scoreLabel('vector', nullableNumber(result.vector_score))}
                  {scoreLabel('keyword', nullableNumber(result.keyword_score))}
                  {scoreLabel('rrf', nullableNumber(result.rrf_score))}
                  {scoreLabel('rerank', nullableNumber(result.rerank_score))}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
      {response.debug ? (
        <details className="kb-search-debug" open={debugOpen} onToggle={(event) => setDebugOpen(event.currentTarget.open)}>
          <summary>
            {debugOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            Debug
          </summary>
          <KbSearchDebugView debug={response.debug} />
        </details>
      ) : null}
    </section>
  );
}

function KbSearchDebugView({ debug }: { debug: KbSearchDebug }) {
  const groups = Array.isArray(debug.embedding_groups) ? debug.embedding_groups : [];
  const warnings = Array.isArray(debug.warnings) ? debug.warnings.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : [];
  return (
    <div className="kb-search-debug-body">
      <div className="knowledge-debug-grid">
        <DebugRow
          label="Embedding groups"
          value={
            groups.length
              ? groups.map((group) => `${group.embedding_model_profile_id || 'profile'} (${group.candidate_count ?? 0})`).join(', ')
              : 'none'
          }
          wide
        />
        <DebugRow label="Keyword candidates" value={debug.keyword_candidate_count} />
        <DebugRow label="Merged candidates" value={debug.merged_candidate_count} />
        <DebugRow label="Reranker used" value={debug.reranker_used === undefined ? undefined : debug.reranker_used ? 'yes' : 'no'} />
        <DebugRow label="Reranker failed" value={debug.reranker_failed === undefined ? undefined : debug.reranker_failed ? 'yes' : 'no'} />
      </div>
      {warnings.length ? (
        <div className="knowledge-debug-warnings">
          {warnings.map((warning, index) => (
            <span key={`${warning}-${index}`}>{warning}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function FileContentRenderer({ payload, variant = 'card', wrapLines }: { payload: FileContentPayload; variant?: 'card' | 'modal'; wrapLines?: boolean }) {
  const { t } = useTranslation(['renderers', 'common']);
  const setError = useWorkbenchStore((state) => state.setError);
  const [copied, setCopied] = useState(false);
  const filename = payload.filename?.trim() || t('renderers:labels.fileContent');
  const language = payload.language?.trim() || 'text';
  const size = typeof payload.size === 'number' && Number.isFinite(payload.size) ? formatBytes(payload.size) : '';
  const [cardWrapLines, setCardWrapLines] = useState(defaultWrapLines(filename, language));
  const isModal = variant === 'modal';
  const effectiveWrapLines = isModal && typeof wrapLines === 'boolean' ? wrapLines : cardWrapLines;

  async function copyFileContent() {
    try {
      await navigator.clipboard.writeText(payload.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1300);
    } catch (error) {
      setError(error, t('renderers:errors.copyFileContent'));
    }
  }

  return (
    <section className={`message-content file-content-card ${isModal ? 'modal' : 'card'}`}>
      {!isModal ? (
        <header className="file-content-header">
          <div className="file-content-title">
            <strong title={filename}>{filename}</strong>
            <span>{language}</span>
            {size ? <span>{size}</span> : null}
            {payload.truncated ? <span className="file-content-truncated">{t('renderers:labels.truncated')}</span> : null}
          </div>
          <div className="file-content-actions">
            <button type="button" className="file-content-wrap-toggle" onClick={() => setCardWrapLines((current) => !current)}>
              {effectiveWrapLines ? t('renderers:actions.noWrap') : t('renderers:actions.wrapLines')}
            </button>
            <button type="button" className="file-content-copy" onClick={() => void copyFileContent()} title={t('renderers:actions.copyFileContent')}>
              {copied ? <Check size={13} /> : <Copy size={13} />}
              <span>{copied ? t('renderers:labels.copied') : t('common:copy')}</span>
            </button>
          </div>
        </header>
      ) : null}
      {payload.truncated ? <div className="file-content-notice">{t('renderers:notices.contentTruncated')}</div> : null}
      <pre className={`file-content-body ${effectiveWrapLines ? 'wrap' : 'no-wrap'}`}>
        <code>{payload.content}</code>
      </pre>
    </section>
  );
}

function ImageRenderer({ image, onPreviewImage }: { image: ImagePayload | null; onPreviewImage: (image: ImagePreview) => void }) {
  if (!image) {
    return <PlainTextRenderer content="" />;
  }
  const url = safeImageUrl(image.url);
  if (!url) {
    return <PlainTextRenderer content={image.caption || image.alt || image.title || ''} />;
  }
  return (
    <figure className="message-content image-content">
      {image.title ? <figcaption className="image-title">{image.title}</figcaption> : null}
      <button className="message-image-preview-trigger" type="button" onClick={() => onPreviewImage({ url, alt: image.alt, title: image.title, caption: image.caption })}>
        <img src={url} alt={image.alt || image.title || image.caption || ''} loading="lazy" />
      </button>
      {image.caption ? <figcaption className="image-caption">{image.caption}</figcaption> : null}
    </figure>
  );
}

function ImageGalleryRenderer({ images, onPreviewImage }: { images: ImagePayload[]; onPreviewImage: (image: ImagePreview) => void }) {
  if (!images.length) {
    return <PlainTextRenderer content="" />;
  }
  return (
    <div className="message-content image-gallery">
      {images.map((image, index) => (
        <ImageRenderer key={`${image.url}-${index}`} image={image} onPreviewImage={onPreviewImage} />
      ))}
    </div>
  );
}

function CommandButtonsRenderer({ block }: { block: CommandButtonsBlock }) {
  const { t } = useTranslation(['renderers']);
  const sendMessage = useWorkbenchStore((state) => state.sendMessage);
  const sending = useWorkbenchStore((state) => state.sending);
  const buttons = block.buttons.filter((button) => button.label.trim() && button.message.trim());

  if (!buttons.length) return null;
  return (
    <div className="command-buttons" aria-label={t('renderers:labels.commandShortcuts')}>
      {buttons.map((button) => (
        <button key={`${button.label}:${button.message}`} type="button" onClick={() => void sendMessage(button.message)} disabled={sending} title={button.message}>
          <Send size={14} />
          <span>{button.label}</span>
        </button>
      ))}
    </div>
  );
}

function ActionFormRenderer({ form, messageId, blockIndex }: { form: ActionFormBlock; messageId: string; blockIndex: number }) {
  const { t } = useTranslation(['renderers']);
  const submitForm = useWorkbenchStore((state) => state.submitForm);
  const pendingActionKey = useWorkbenchStore((state) => state.pendingActionKey);
  const [values, setValues] = useState<Record<string, unknown>>(() => initialFormValues(form));
  const [error, setError] = useState<string>('');
  const [notice, setNotice] = useState<string>('');
  const [expanded, setExpanded] = useState(() => !initialActionFormCollapsed(form));
  const pending = pendingActionKey === `${messageId}:form:${form.form_id}`;
  const silent = form.submit.visibility === 'silent';
  const sections = groupActionFormFields(form);
  const collapsed = !expanded;
  const formDomKey = `${messageId}-${blockIndex}-${form.form_id}`;
  const collapsedMessage = form.ui?.collapsed_message || 'Click to expand.';
  const displayCollapsedMessage = form.ui?.collapsed_message || t('renderers:notices.clickToExpand', { defaultValue: collapsedMessage });

  useEffect(() => {
    setValues(initialFormValues(form));
    setError('');
    setNotice('');
    setExpanded(!initialActionFormCollapsed(form));
  }, [form]);

  function setFieldValue(field: ActionFormField, value: unknown) {
    setValues((current) => ({ ...current, [field.name]: value }));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!messageId || pending) return;
    setError('');
    setNotice('');
    try {
      const result = await submitForm(messageId, form.form_id, values, { silent });
      if (silent) {
        if (result && !result.success) {
          throw new Error(result.message || result.error || 'Form submission failed');
        }
        setNotice(result?.message || form.submit.success_message || 'Saved');
      }
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : t('renderers:notices.formSubmissionFailed');
      setError(message);
    }
  }

  if (collapsed) {
    return (
      <section className="action-form-card collapsed">
        <button type="button" className="action-form-collapse-toggle" onClick={() => setExpanded(true)} aria-expanded={false}>
          <ChevronRight size={14} />
          <span>
            <strong>{form.title}</strong>
            <small>{displayCollapsedMessage}</small>
          </span>
        </button>
      </section>
    );
  }

  return (
    <form className="action-form-card" onSubmit={(event) => void onSubmit(event)}>
      <header className="action-form-header">
        <div className="action-form-title-row">
          <button type="button" className="action-form-header-toggle" onClick={() => setExpanded(false)} aria-expanded={true} title={t('renderers:actions.collapse')}>
            <ChevronDown size={14} />
          </button>
          <strong>{form.title}</strong>
        </div>
        {form.description ? <p>{form.description}</p> : null}
      </header>
      <div className="action-form-sections">
        {sections.map((section) => (
          <section className={`action-form-section ${section.key === DEFAULT_FORM_SECTION_KEY ? 'default' : ''}`} key={section.key}>
            {section.title ? <h4>{section.title}</h4> : null}
            <div className="action-form-fields">
              {section.fields.map((field) => (
                <ActionFormFieldControl key={`${formDomKey}-${field.name}`} formDomKey={formDomKey} field={field} value={values[field.name]} onChange={(value) => setFieldValue(field, value)} />
              ))}
            </div>
          </section>
        ))}
      </div>
      {error ? <div className="action-form-error">{error}</div> : null}
      {notice ? <div className="action-form-notice">{notice}</div> : null}
      <div className="action-form-actions">
        <button type="button" onClick={() => setValues(initialFormValues(form))} disabled={pending}>
          <RotateCcw size={14} />
          <span>{t('renderers:actions.reset')}</span>
        </button>
        <button type="submit" className="primary" disabled={pending || !messageId}>
          {pending ? <Loader2 size={14} className="spin" /> : <Send size={14} />}
          <span>{pending ? t('renderers:actions.submitting') : form.submit.label || t('renderers:actions.submit')}</span>
        </button>
      </div>
    </form>
  );
}

function ActionFormFieldControl({ formDomKey, field, value, onChange }: { formDomKey: string; field: ActionFormField; value: unknown; onChange: (value: unknown) => void }) {
  const id = `action-form-${formDomKey}-${field.name}`;
  const label = field.label || field.name;
  const description = field.description || field.help || '';
  const span = resolveActionFormFieldSpan(field);
  const common = {
    id,
    name: field.name,
    required: field.required,
    placeholder: field.placeholder || undefined,
  };
  let control: ReactNode;
  if (field.type === 'textarea') {
    control = <textarea {...common} value={stringFormValue(value)} onChange={(event) => onChange(event.target.value)} rows={4} minLength={field.min_length ?? undefined} maxLength={field.max_length ?? undefined} />;
  } else if (field.type === 'integer' || field.type === 'float') {
    control = <input {...common} type="number" value={numberFormValue(value)} min={field.minimum ?? undefined} max={field.maximum ?? undefined} step={field.step ?? (field.type === 'integer' ? 1 : 'any')} onChange={(event) => onChange(event.target.value)} />;
  } else if (field.type === 'boolean') {
    control = <input {...common} type="checkbox" checked={value === true} onChange={(event) => onChange(event.target.checked)} />;
  } else if (field.type === 'enum') {
    control = (
      <select {...common} value={stringFormValue(value)} onChange={(event) => onChange(enumOptionValue(field, event.target.value))}>
        {(field.options || []).map((option) => (
          <option key={String(option.value)} value={String(option.value)}>
            {option.label || String(option.value)}
          </option>
        ))}
      </select>
    );
  } else if (field.type === 'json') {
    control = <textarea {...common} className="action-form-json" value={jsonFormValue(value)} onChange={(event) => onChange(event.target.value)} rows={5} />;
  } else {
    control = <input {...common} type="text" value={stringFormValue(value)} onChange={(event) => onChange(event.target.value)} minLength={field.min_length ?? undefined} maxLength={field.max_length ?? undefined} />;
  }
  return (
    <label className={`action-form-field span-${span} ${field.type === 'boolean' ? 'boolean action-form-checkbox' : ''}`} htmlFor={id}>
      <span>{label}</span>
      {control}
      {description ? <small>{description}</small> : null}
    </label>
  );
}

function initialActionFormCollapsed(form: ActionFormBlock): boolean {
  if (typeof form.ui?.collapsed === 'boolean') return form.ui.collapsed;
  return form.ui?.default_collapsed === true;
}

const DEFAULT_FORM_SECTION_KEY = '__default';

type ActionFormFieldSection = {
  key: string;
  title: string;
  fields: ActionFormField[];
};

function groupActionFormFields(form: ActionFormBlock): ActionFormFieldSection[] {
  const titleByKey = new Map((form.sections || []).filter((section) => section.key).map((section) => [section.key, section.title || titleFromSectionKey(section.key)]));
  const sections: ActionFormFieldSection[] = [];
  const byKey = new Map<string, ActionFormFieldSection>();
  for (const field of form.fields) {
    const key = field.ui?.section?.trim() || DEFAULT_FORM_SECTION_KEY;
    let section = byKey.get(key);
    if (!section) {
      section = { key, title: key === DEFAULT_FORM_SECTION_KEY ? '' : titleByKey.get(key) || titleFromSectionKey(key), fields: [] };
      byKey.set(key, section);
      sections.push(section);
    }
    section.fields.push(field);
  }
  return sections;
}

function resolveActionFormFieldSpan(field: ActionFormField): number {
  if (Number.isInteger(field.ui?.span) && field.ui?.span && field.ui.span >= 1 && field.ui.span <= 12) {
    return field.ui.span;
  }
  const name = field.name.toLowerCase();
  if (field.type === 'textarea' || field.type === 'json' || name.includes('prompt') || name.includes('description')) return 12;
  if (['seed', 'steps', 'cfg', 'cfg_scale', 'width', 'height', 'batch_size', 'denoise', 'sampler', 'sampler_name', 'scheduler'].includes(name)) return 4;
  if (name.includes('checkpoint') || name === 'ckpt_name' || name.includes('filename_prefix')) return 6;
  if (field.type === 'integer' || field.type === 'float' || field.type === 'boolean') return 4;
  if (field.type === 'enum') return 4;
  if (field.type === 'text') return 12;
  return 12;
}

function titleFromSectionKey(key: string): string {
  return key
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ');
}

function initialFormValues(form: ActionFormBlock): Record<string, unknown> {
  return Object.fromEntries(form.fields.map((field) => [field.name, field.value ?? field.default ?? defaultFormValue(field)]));
}

function defaultFormValue(field: ActionFormField): unknown {
  if (field.type === 'boolean') return false;
  if (field.type === 'json') return {};
  if (field.type === 'integer' || field.type === 'float') return '';
  return '';
}

function stringFormValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function numberFormValue(value: unknown): string | number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') return value;
  return '';
}

function jsonFormValue(value: unknown): string {
  if (typeof value === 'string') return value;
  return JSON.stringify(value ?? {}, null, 2);
}

function enumOptionValue(field: ActionFormField, selected: string): string | number | boolean {
  const option = (field.options || []).find((item) => String(item.value) === selected);
  return option ? option.value : selected;
}

export function contentToText(content: unknown): string {
  if (typeof content === 'string') {
    return unwrapJsonString(content);
  }
  if (content === null || content === undefined) {
    return '';
  }
  if (typeof content === 'object') {
    return JSON.stringify(content, null, 2);
  }
  return String(content);
}

function copyableMessageContent(message: Message): string {
  const partsText = copyablePartsContent(message.parts);
  return partsText !== null ? partsText : '';
}

function copyablePartsContent(parts: MessagePart[] | undefined): string | null {
  if (!hasRenderableParts(parts)) return null;
  const chunks = (parts || []).map(copyablePartContent).filter((item) => item.trim().length > 0);
  return chunks.length ? chunks.join('\n\n') : '';
}

function copyablePartContent(part: MessagePart): string {
  if (part.type === 'text') return part.text;
  if (part.type === 'json') return JSON.stringify(part.data, null, 2);
  if (part.type === 'file') {
    if (part.mode === 'inline_text') return part.content || '';
    return [part.filename, part.attachment_id, part.url].filter(Boolean).join(' ');
  }
  if (part.type === 'image') return [part.alt, part.url, part.attachment_id].filter(Boolean).join(' ');
  if (part.type === 'audio') return [part.title, part.filename, part.mime_type, part.url].filter(Boolean).join(' ');
  if (part.type === 'video') return [part.title, part.filename, part.mime_type, part.url].filter(Boolean).join(' ');
  if (part.type === 'media_group') {
    return (part.items || []).map((item) => [item.alt, item.url, item.attachment_id].filter(Boolean).join(' ')).filter(Boolean).join('\n');
  }
  if (part.type === 'form') return [part.title, part.description].filter(Boolean).join('\n');
  if (part.type === 'command_buttons') return (part.buttons || []).map((button) => `${button.label}: ${button.message}`).join('\n');
  if (part.type === 'notice') return part.text;
  if (part.type === 'error') return [part.code, part.message].filter(Boolean).join(': ');
  return '';
}

function messageAttachments(message: Message): Attachment[] {
  const attachments = message.metadata?.attachments;
  if (!Array.isArray(attachments)) return [];
  return attachments.filter(isAttachment);
}

function isAttachment(value: unknown): value is Attachment {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  const base =
    item.type === 'image' &&
    typeof item.id === 'string' &&
    typeof item.mime_type === 'string' &&
    typeof item.name === 'string' &&
    typeof item.size === 'number' &&
    ((typeof item.data_url === 'string' && Boolean(safeImageUrl(item.data_url))) ||
      (typeof item.uri === 'string' && Boolean(safeImageUrl(item.uri))));
  if (base) return true;
  if (item.type === 'file') {
    return typeof item.id === 'string' && typeof item.mime_type === 'string' && typeof item.name === 'string' && typeof item.size === 'number' && (typeof item.uri === 'string' || typeof item.data_url === 'string');
  }
  return (item.type === 'audio' || item.type === 'video') && typeof item.id === 'string' && typeof item.mime_type === 'string' && typeof item.name === 'string' && typeof item.size === 'number' && typeof item.uri === 'string';
}

function attachmentUrl(attachment: ImageAttachment): string {
  return resolveAttachmentUrl(attachment);
}

function isPreviewableFile(attachment: FileAttachment): boolean {
  const mimeType = attachment.mime_type.toLowerCase();
  const extension = basename(attachment.name)?.toLowerCase().match(/(\.[^.]+)$/)?.[1] || '';
  return mimeType.startsWith('text/') || ['application/json', 'application/xml', 'application/yaml', 'application/toml', 'application/sql'].includes(mimeType) || ['.txt', '.md', '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.yaml', '.yml', '.toml', '.xml', '.html', '.css', '.env', '.log', '.csv', '.sql', '.sh', '.ps1', '.bat', '.ini', '.cfg'].includes(extension);
}

function fileKindLabel(mimeType: string, name: string): string {
  const extension = basename(name)?.match(/(\.[^.]+)$/)?.[1]?.replace('.', '').toUpperCase();
  return extension || mimeType || 'FILE';
}

function normalizeImagePayload(content: unknown): ImagePayload | null {
  if (!content || typeof content !== 'object' || Array.isArray(content)) return null;
  const value = content as Record<string, unknown>;
  if (typeof value.url !== 'string' || !value.url.trim()) return null;
  return {
    url: value.url,
    alt: optionalString(value.alt),
    title: optionalString(value.title),
    caption: optionalString(value.caption),
  };
}

function normalizeImageGallery(content: unknown): ImagePayload[] {
  if (!content || typeof content !== 'object' || Array.isArray(content)) return [];
  const value = content as Record<string, unknown>;
  if (!Array.isArray(value.images)) return [];
  return value.images.map(normalizeImagePayload).filter((image): image is ImagePayload => image !== null);
}

function normalizeFileContentPayload(content: unknown): FileContentPayload {
  if (!content || typeof content !== 'object' || Array.isArray(content)) {
    return { content: contentToText(content), language: 'text', truncated: false };
  }
  const value = content as Record<string, unknown>;
  return {
    filename: optionalString(value.filename) || basename(optionalString(value.path)),
    language: optionalString(value.language) || 'text',
    mime_type: optionalString(value.mime_type),
    content: typeof value.content === 'string' ? value.content : contentToText(value.content),
    size: numberValue(value.size),
    truncated: value.truncated === true,
    path: optionalString(value.path),
  };
}

function hasRenderableMessage(message: Message, reasoningContent: string): boolean {
  if (reasoningContent.trim()) return true;
  if (hasRenderableParts(message.parts)) return true;
  if (message.role === 'user' && messageAttachments(message).length) return true;
  return false;
}

function hasVisibleRun(run: Run | undefined): boolean {
  return Boolean(run && isActiveRunStatus(run.status));
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function basename(value: string | undefined): string | undefined {
  if (!value) return undefined;
  return value.split(/[\\/]/).filter(Boolean).pop() || value;
}

function languageForFilename(name: string): string {
  const extension = basename(name)?.toLowerCase().match(/(\.[^.]+)$/)?.[1] || '';
  return (
    {
      '.md': 'markdown',
      '.py': 'python',
      '.js': 'javascript',
      '.ts': 'typescript',
      '.tsx': 'tsx',
      '.jsx': 'jsx',
      '.json': 'json',
      '.yaml': 'yaml',
      '.yml': 'yaml',
      '.toml': 'toml',
      '.xml': 'xml',
      '.html': 'html',
      '.css': 'css',
      '.env': 'dotenv',
      '.log': 'log',
      '.csv': 'csv',
      '.sql': 'sql',
      '.sh': 'shell',
      '.ps1': 'powershell',
      '.bat': 'batch',
      '.ini': 'ini',
      '.cfg': 'ini',
    }[extension] || 'text'
  );
}

export function defaultWrapLines(filename: string, language: string): boolean {
  const extension = basename(filename)?.toLowerCase().match(/(\.[^.]+)$/)?.[1] || '';
  const codeExtensions = new Set(['.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.yaml', '.yml', '.toml', '.xml', '.html', '.css', '.sql', '.sh', '.ps1', '.bat', '.ini', '.cfg']);
  const textExtensions = new Set(['.md', '.txt', '.log', '.csv']);
  if (codeExtensions.has(extension)) return false;
  if (textExtensions.has(extension)) return true;
  return !['python', 'javascript', 'typescript', 'tsx', 'jsx', 'json', 'yaml', 'toml', 'xml', 'html', 'css', 'sql', 'shell', 'powershell', 'batch', 'ini'].includes(language.toLowerCase());
}

function extractReasoningContent(metadata: Record<string, unknown> | undefined): string {
  if (!metadata) return '';
  const direct = metadata.reasoning_content;
  if (typeof direct === 'string' && direct.trim()) return direct;
  const reasoning = metadata.reasoning;
  if (reasoning && typeof reasoning === 'object' && !Array.isArray(reasoning)) {
    const content = (reasoning as Record<string, unknown>).content;
    if (typeof content === 'string' && content.trim()) return content;
  }
  return '';
}

export function normalizeJsonContent(content: unknown): unknown {
  if (typeof content !== 'string') {
    return content;
  }
  const unwrapped = unwrapJsonString(content);
  try {
    return JSON.parse(unwrapped);
  } catch {
    return unwrapped;
  }
}

function normalizeKbSearchResponse(value: unknown): KbSearchResponse | null {
  if (!isPlainRecord(value)) return null;
  const rawResults = value.results;
  const isWebSearchShape = value.kind === 'web_search_results' || value.schema === 'web_search.results.v1' || (Array.isArray(rawResults) && rawResults.some(isWebSearchResultRecord));
  if (isWebSearchShape) return null;
  const hasKbSearchShape = Array.isArray(rawResults) && (
    isPlainRecord(value.debug) ||
    rawResults.some((item) => isPlainRecord(item) && (
      'knowledge_base_id' in item ||
      'knowledge_base_name' in item ||
      'source_id' in item ||
      'heading_path' in item ||
      'vector_score' in item ||
      'keyword_score' in item ||
      'rrf_score' in item ||
      'rerank_score' in item
    ))
  );
  if (!hasKbSearchShape) return null;
  const results = rawResults
    .filter(isPlainRecord)
    .map((item): KbSearchResult => ({
      rank: numberValue(item.rank),
      knowledge_base_id: textValue(item.knowledge_base_id),
      knowledge_base_name: textValue(item.knowledge_base_name),
      source_id: textValue(item.source_id),
      title: textValue(item.title),
      heading_path: textValue(item.heading_path),
      content: textValue(item.content) || '',
      vector_score: nullableNumber(item.vector_score),
      keyword_score: nullableNumber(item.keyword_score),
      rrf_score: nullableNumber(item.rrf_score),
      rerank_score: nullableNumber(item.rerank_score),
    }));
  const debug = isPlainRecord(value.debug) ? value.debug : undefined;
  return {
    query: textValue(value.query),
    results,
    debug: debug
      ? {
          embedding_groups: Array.isArray(debug.embedding_groups) ? debug.embedding_groups.filter(isPlainRecord).map((group) => ({
            embedding_model_profile_id: textValue(group.embedding_model_profile_id),
            knowledge_base_ids: Array.isArray(group.knowledge_base_ids) ? group.knowledge_base_ids.map(String) : [],
            candidate_count: numberValue(group.candidate_count),
          })) : [],
          keyword_candidate_count: numberValue(debug.keyword_candidate_count),
          merged_candidate_count: numberValue(debug.merged_candidate_count),
          reranker_used: booleanValue(debug.reranker_used),
          reranker_failed: booleanValue(debug.reranker_failed),
          warnings: Array.isArray(debug.warnings) ? debug.warnings.map(String) : [],
        }
      : undefined,
    error: isPlainRecord(value.error)
      ? {
          code: textValue(value.error.code),
          message: textValue(value.error.message),
        }
      : undefined,
  };
}

function normalizeWebSearchResponse(value: unknown): WebSearchResponse | null {
  if (!isPlainRecord(value)) return null;
  if (value.kind !== 'web_search_results' && value.schema !== 'web_search.results.v1') return null;
  const rawResults = Array.isArray(value.results) ? value.results : [];
  return {
    kind: textValue(value.kind),
    schema: textValue(value.schema),
    query: textValue(value.query),
    provider: textValue(value.provider),
    searched_at: textValue(value.searched_at),
    results: rawResults
      .filter(isPlainRecord)
      .map((item): WebSearchResult => ({
        rank: numberValue(item.rank),
        title: textValue(item.title),
        url: textValue(item.url),
        domain: textValue(item.domain),
        snippet: textValue(item.snippet) || '',
        published_at: textValue(item.published_at) || null,
        source: textValue(item.source),
      })),
    warnings: Array.isArray(value.warnings) ? value.warnings.map(String) : [],
  };
}

function isWebSearchResultRecord(value: unknown): boolean {
  return isPlainRecord(value) && (typeof value.url === 'string' || typeof value.domain === 'string');
}

function safeHttpUrl(value: string | undefined): string {
  if (!value) return '';
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : '';
  } catch {
    return '';
  }
}

function contextSummaryForStep(step: RunStep, runKnowledge?: KnowledgeRetrievalSummary | null): NormalizedContextMetadata | null {
  const summary = normalizeContextMetadata(step.metadata);
  if (!summary.knowledge && runKnowledge && fallbackKnowledgeStepLabel(step.label, runKnowledge)) {
    summary.knowledge = knowledgeContextFromRetrieval(runKnowledge);
  }
  if (!summary.memory && !summary.knowledge && !summary.worldbook && !summary.web) return null;
  const hasUsedContext = Boolean(
    summary.memory?.injected ||
    summary.worldbook?.injected ||
    summary.knowledge?.injected ||
    summary.web?.injected ||
    summary.web?.attempted ||
    summary.web?.resolverUsed ||
    Boolean(summary.web?.querySource) ||
    Boolean(summary.web?.skippedReason && summary.web.enabled === true) ||
    summary.memory?.warnings.length ||
    summary.worldbook?.warnings.length ||
    summary.knowledge?.warnings.length ||
    summary.web?.warnings.length,
  );
  return hasUsedContext ? summary : null;
}

function fallbackKnowledgeStepLabel(label: string, summary: KnowledgeRetrievalSummary): boolean {
  const normalized = label.trim().toLowerCase();
  const source = summary.source;
  if (source === 'prompt_agent') return normalized === 'building context';
  if (source === 'script_agent') return normalized === 'running script' || normalized === 'calling llm' || normalized.includes('llm');
  return normalized === 'building context' || normalized === 'running script';
}

function knowledgeRetrievalSummaryFromNormalized(summary: KnowledgeContextSummary): KnowledgeRetrievalSummary | null {
  return summary.retrieval || knowledgeContextFromRetrieval({
    kbLabels: summary.kbNames,
    injected: summary.injected,
    resultCount: summary.snippetCount,
    warnings: summary.warnings,
  }).retrieval || null;
}

function knowledgeContextFromRetrieval(retrieval: KnowledgeRetrievalSummary): KnowledgeContextSummary {
  return {
    injected: retrieval.injected,
    snippetCount: retrieval.resultCount,
    snippetRefs: [],
    kbNames: retrieval.kbLabels,
    rerankerSummary: rerankerLabel(retrieval),
    warnings: retrieval.warnings,
    canViewSnippets: false,
    retrieval,
  };
}

function knowledgeRetrievalSummary(value: unknown): KnowledgeRetrievalSummary | null {
  if (!isPlainRecord(value)) return null;
  const context = value;
  const enabled = booleanValue(context.enabled);
  const injected = booleanValue(context.injected);
  const hasCounts = ['result_count', 'vector_candidate_count', 'keyword_candidate_count', 'merged_candidate_count'].some((key) => numberValue(context[key]) !== undefined);
  const warnings = Array.isArray(context.warnings) ? context.warnings.map(String).filter(Boolean) : [];
  if (enabled === false && !warnings.length && !hasCounts) return null;
  const kbLabels = [
    ...(Array.isArray(context.knowledge_base_names) ? context.knowledge_base_names.map(String) : []),
    ...(Array.isArray(context.knowledge_bases) ? context.knowledge_bases.map(kbLabel).filter((item): item is string => Boolean(item)) : []),
  ];
  if (!kbLabels.length && Array.isArray(context.knowledge_base_ids)) {
    kbLabels.push(...context.knowledge_base_ids.map(String));
  }
  return {
    source: textValue(context.source),
    kbLabels: Array.from(new Set(kbLabels.filter(Boolean))),
    injected,
    resultCount: numberValue(context.result_count),
    embeddingLabel: firstText([
      context.embedding_model_profile_name,
      context.embedding_model_profile_alias,
      Array.isArray(context.embedding_model_profiles) ? context.embedding_model_profiles.map(String).join(', ') : undefined,
    ]),
    embeddingDimension: embeddingDimensionValue(context.embedding_dimension),
    vectorCandidateCount: numberValue(context.vector_candidate_count),
    keywordCandidateCount: numberValue(context.keyword_candidate_count),
    mergedCandidateCount: numberValue(context.merged_candidate_count),
    rerankerUsed: booleanValue(context.reranker_used),
    rerankerFailed: booleanValue(context.reranker_failed),
    rerankerInputCount: numberValue(context.reranker_input_count),
    rerankerOutputCount: numberValue(context.reranker_output_count),
    warnings,
  };
}

function kbLabel(value: unknown): string | undefined {
  if (typeof value === 'string') return value;
  if (!isPlainRecord(value)) return undefined;
  return textValue(value.name) || textValue(value.id);
}

function firstPlainRecord(values: unknown[]): Record<string, unknown> | undefined {
  return values.find(isPlainRecord);
}

function mergeKnowledgeRetrievalSummaries(items: KnowledgeRetrievalSummary[]): KnowledgeRetrievalSummary | null {
  if (!items.length) return null;
  return {
    source: items.map((item) => item.source).filter(Boolean).join(', ') || undefined,
    kbLabels: uniqueStrings(items.flatMap((item) => item.kbLabels)),
    injected: items.some((item) => item.injected === true),
    resultCount: sumNumbers(items.map((item) => item.resultCount)),
    embeddingLabel: uniqueStrings(items.map((item) => item.embeddingLabel).filter((item): item is string => Boolean(item))).join(', ') || undefined,
    embeddingDimension: uniqueStrings(items.map((item) => item.embeddingDimension).filter((item): item is string | number => item !== undefined).map(String)).join('/') || undefined,
    vectorCandidateCount: sumNumbers(items.map((item) => item.vectorCandidateCount)),
    keywordCandidateCount: sumNumbers(items.map((item) => item.keywordCandidateCount)),
    mergedCandidateCount: sumNumbers(items.map((item) => item.mergedCandidateCount)),
    rerankerUsed: items.some((item) => item.rerankerUsed === true) ? true : items.some((item) => item.rerankerUsed === false) ? false : undefined,
    rerankerFailed: items.some((item) => item.rerankerFailed === true),
    rerankerInputCount: sumNumbers(items.map((item) => item.rerankerInputCount)),
    rerankerOutputCount: sumNumbers(items.map((item) => item.rerankerOutputCount)),
    warnings: uniqueStrings(items.flatMap((item) => item.warnings)),
  };
}

function memorySummaryLabel(summary: CoreMemoryContextSummary, t: ReturnType<typeof useTranslation>['t']): string {
  if (summary.injected) return t('runs:contextSummary.memoryInjected', { count: summary.contentChars ?? 0 });
  if (summary.skippedReason) return t('runs:contextSummary.skippedWithReason', { reason: summary.skippedReason });
  return summary.enabled === false ? t('runs:contextSummary.skipped') : t('runs:contextSummary.notUsed');
}

function worldbookSummaryLabel(summary: WorldbookContextSummary, t: ReturnType<typeof useTranslation>['t']): string {
  if (summary.injectedEntryCount !== undefined || summary.matchedEntryCount !== undefined) {
    return t('runs:contextSummary.worldbookCounts', {
      injected: summary.injectedEntryCount ?? 0,
      matched: summary.matchedEntryCount ?? 0,
      recursion: summary.recursionRoundsUsed ?? summary.recursionDepth ?? 0,
    });
  }
  return summary.injected ? t('runs:contextSummary.injected') : t('runs:contextSummary.skipped');
}

function knowledgeSummaryLabel(summary: KnowledgeContextSummary | undefined, t: ReturnType<typeof useTranslation>['t']): string | undefined {
  if (!summary) return undefined;
  const parts = [];
  const count = summary.snippetCount ?? summary.retrieval?.resultCount;
  if (count !== undefined) parts.push(t('runs:contextSummary.snippetCount', { count }));
  if (summary.kbNames.length) parts.push(summary.kbNames.join(', '));
  if (summary.retrieval) parts.push(t('runs:contextSummary.rerankerValue', { value: rerankerLabel(summary.retrieval, t) }));
  return parts.join(' / ') || (summary.injected ? t('runs:contextSummary.injected') : t('runs:contextSummary.skipped'));
}

function webSummaryLabel(summary: WebContextSummary, t: ReturnType<typeof useTranslation>['t']): string {
  if (summary.injected) {
    const provider = summary.provider || t('runs:contextSummary.unknown');
    const resultLabel = [t('runs:contextSummary.webResultCount', { count: summary.resultCount ?? 0, provider }), ...webDiagnosticsSummaryParts(summary, t)].join(' · ');
    return summary.query ? `${resultLabel} · ${t('runs:contextSummary.searchQuery', { query: summary.query })}` : resultLabel;
  }
  if (summary.skippedReason) {
    const reason = webSkipReasonLabel(summary.skippedReason, t);
    const plan = webPlanSummaryParts(summary, t).join(' · ');
    return plan ? `${t('runs:contextSummary.skippedWithReason', { reason })} · ${plan}` : t('runs:contextSummary.skippedWithReason', { reason });
  }
  if (summary.attempted) return t('runs:contextSummary.noResults');
  return summary.enabled === false ? t('runs:contextSummary.skipped') : t('runs:contextSummary.notUsed');
}

function webPlanSummaryParts(summary: WebContextSummary, t: ReturnType<typeof useTranslation>['t']): string[] {
  const parts: string[] = [];
  if (summary.querySource) parts.push(t('runs:contextSummary.webQuerySource', { source: webQuerySourceLabel(summary.querySource, t) }));
  if (summary.resolverReason) parts.push(webSkipReasonLabel(summary.resolverReason, t));
  if (summary.resolverConfidence) parts.push(t('runs:contextSummary.webResolverConfidence', { confidence: summary.resolverConfidence }));
  return parts;
}

function webDiagnosticsSummaryParts(summary: WebContextSummary, t: ReturnType<typeof useTranslation>['t']): string[] {
  const diagnostics = summary.searchDiagnostics;
  const parts: string[] = [];
  if (diagnostics?.filteredCount) parts.push(t('runs:contextSummary.filteredResults', { count: diagnostics.filteredCount }));
  if (diagnostics?.dedupedCount) parts.push(t('runs:contextSummary.deduplicatedResults', { count: diagnostics.dedupedCount }));
  if (summary.candidateJudge?.used) {
    parts.push(t('runs:contextSummary.webCandidatesJudged', {
      judged: summary.candidateJudge.candidateCount ?? 0,
      retained: summary.candidateJudge.retainedCount ?? 0,
      rejected: summary.candidateJudge.rejectedCount ?? 0,
      unjudged: summary.candidateJudge.unjudgedCount ?? 0,
    }));
    if (summary.candidateJudge.rejectedCount) parts.push(t('runs:contextSummary.webCandidatesRejected', { count: summary.candidateJudge.rejectedCount }));
  }
  if (summary.pageFetchEnabled) {
    if (summary.pagesFetched !== undefined) parts.push(t('runs:contextSummary.pagesFetched', { count: summary.pagesFetched }));
    if (summary.pagesFailed) parts.push(t('runs:contextSummary.pagesFailed', { count: summary.pagesFailed }));
  }
  if (summary.pageExcerptGate?.enabled) {
    parts.push(t('runs:contextSummary.pageExcerptGate', {
      attempted: summary.pageExcerptGate.attempted ?? 0,
      accepted: summary.pageExcerptGate.accepted ?? 0,
      rejected: summary.pageExcerptGate.rejected ?? 0,
      failed: summary.pageExcerptGate.failed ?? 0,
    }));
    if (summary.pageExcerptGate.stoppedReason) parts.push(t('runs:contextSummary.pageExcerptGateStopped', { reason: summary.pageExcerptGate.stoppedReason }));
  }
  return parts;
}

function webContextPlanStepMessage(plan: Record<string, unknown>, t: ReturnType<typeof useTranslation>['t']): string {
  const parts: string[] = [];
  const querySource = textValue(plan.query_source);
  const skippedReason = textValue(plan.skipped_reason);
  const resolver = isPlainRecord(plan.resolver) ? plan.resolver : {};
  const resolverReason = textValue(resolver.reason);
  const resolverConfidence = textValue(resolver.confidence);
  const warnings = stringArray(plan.warnings);
  if (querySource) parts.push(t('runs:contextSummary.webQuerySource', { source: webQuerySourceLabel(querySource, t) }));
  if (skippedReason) parts.push(t('runs:contextSummary.skippedWithReason', { reason: webSkipReasonLabel(skippedReason, t) }));
  if (resolverReason && resolverReason !== skippedReason) parts.push(webSkipReasonLabel(resolverReason, t));
  if (resolverConfidence) parts.push(t('runs:contextSummary.webResolverConfidence', { confidence: resolverConfidence }));
  if (warnings.length) parts.push(t('runs:contextSummary.warningsCount', { count: warnings.length }));
  return parts.join(' · ');
}

function webQuerySourceLabel(source: string, t: ReturnType<typeof useTranslation>['t']): string {
  const key = `runs:contextSummary.webQuerySources.${source}`;
  const label = t(key);
  return label === key ? source : label;
}

function webSkipReasonLabel(reason: string, t: ReturnType<typeof useTranslation>['t']): string {
  const key = `runs:contextSummary.webSkipReasons.${reason}`;
  const label = t(key);
  return label === key ? t('runs:contextSummary.webSkipReasons.web_context_plan_unavailable') : label;
}

function rerankerLabel(summary: KnowledgeRetrievalSummary, t?: ReturnType<typeof useTranslation>['t']): string {
  if (summary.rerankerFailed) return t ? t('runs:contextSummary.failed') : 'failed';
  if (summary.rerankerUsed) {
    if (summary.rerankerInputCount !== undefined || summary.rerankerOutputCount !== undefined) {
      return `${summary.rerankerOutputCount ?? 0} / ${summary.rerankerInputCount ?? 0}`;
    }
    return t ? t('runs:contextSummary.used') : 'used';
  }
  if (summary.rerankerUsed === false) return t ? t('runs:contextSummary.notUsed') : 'not used';
  return t ? t('runs:contextSummary.unknown') : 'unknown';
}

function embeddingSummaryLabel(summary: KnowledgeRetrievalSummary): string | undefined {
  const label = summary.embeddingLabel;
  const dimension = summary.embeddingDimension;
  if (label && dimension) return `${label} / ${dimension}d`;
  if (label) return label;
  if (dimension) return `${dimension}d`;
  return undefined;
}

function injectedLabel(summary: KnowledgeRetrievalSummary): string | undefined {
  if (summary.resultCount !== undefined) return `${summary.resultCount} snippets`;
  if (summary.injected === undefined) return undefined;
  return summary.injected ? 'yes' : 'no';
}

function embeddingDimensionValue(value: unknown): number | string | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (Array.isArray(value)) {
    const values = value.filter((item): item is number => typeof item === 'number' && Number.isFinite(item));
    if (values.length) return Array.from(new Set(values)).join('/');
  }
  return undefined;
}

function normalizeError(message: Message): { code?: string; message?: string } {
  if (message.client_error) {
    return message.client_error;
  }
  const metadataError = message.metadata?.error;
  if (metadataError && typeof metadataError === 'object' && !Array.isArray(metadataError)) {
    const error = metadataError as Record<string, unknown>;
    return {
      code: typeof error.code === 'string' ? error.code : undefined,
      message: typeof error.message === 'string' ? error.message : undefined,
    };
  }
  const errorPart = Array.isArray(message.parts) ? message.parts.find((part) => part.type === 'error') : undefined;
  if (errorPart?.type === 'error') return { code: errorPart.code || undefined, message: errorPart.message };
  return { code: message.run_id ? 'RUN_FAILED' : undefined, message: copyableMessageContent(message) };
}

function hasErrorPart(message: Message): boolean {
  return Array.isArray(message.parts) && message.parts.some((part) => part.type === 'error');
}

function resolvedModelLabel(message: Message): string | undefined {
  const badge = resolveMessageModelBadge(message);
  if (badge.label) return badge.label;
  const fromMessage = extractResolutionLabel(message.metadata?.llm_resolution);
  if (fromMessage) return fromMessage;
  return undefined;
}

function hasProducerIdentity(message: Message): boolean {
  return message.speaker_type === 'agent' || message.speaker_type === 'capability' || Boolean(message.agent_id || message.command_name);
}

function resolveMessageModelBadge(message: Message): { label?: string; title?: string } {
  const llm = isPlainRecord(message.metadata?.llm) ? message.metadata?.llm as Record<string, unknown> : undefined;
  const resolution = isPlainRecord(message.metadata?.llm_resolution) ? message.metadata?.llm_resolution as Record<string, unknown> : undefined;
  const label = firstText([
    llm?.model_profile_name,
    resolution?.profile_name,
    llm?.requested_model_id,
    resolution?.model_id,
    llm?.actual_model_id,
  ]);
  return { label, title: modelTitle(message) || label };
}

function extractActualModelLabel(value: unknown): string | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const llm = value as Record<string, unknown>;
  for (const key of ['model_profile_name', 'requested_model_id', 'actual_model_id']) {
    const item = llm[key];
    if (typeof item === 'string' && item.trim()) return item.trim();
  }
  return undefined;
}

function hasModelMismatch(message: Message): boolean {
  const llm = message.metadata?.llm;
  return Boolean(llm && typeof llm === 'object' && !Array.isArray(llm) && (llm as Record<string, unknown>).model_mismatch === true);
}

function modelTitle(message: Message): string | undefined {
  const value = isPlainRecord(message.metadata?.llm) ? message.metadata?.llm as Record<string, unknown> : {};
  const resolution = isPlainRecord(message.metadata?.llm_resolution) ? message.metadata?.llm_resolution as Record<string, unknown> : {};
  const modelProfileName = textValue(value.model_profile_name) || textValue(resolution.profile_name);
  const modelProfileId = textValue(value.model_profile_id) || textValue(resolution.profile_id);
  const providerProfileName = textValue(value.provider_profile_name) || textValue(resolution.provider_profile_name);
  const providerProfileId = textValue(value.provider_profile_id) || textValue(resolution.provider_profile_id);
  const requested = textValue(value.requested_model_id) || textValue(resolution.model_id);
  const actual = textValue(value.actual_model_id);
  const provider = textValue(value.provider) || textValue(resolution.provider);
  const status = textValue(value.status) || textValue(resolution.status);
  if (![modelProfileName, modelProfileId, providerProfileName, providerProfileId, requested, actual, provider, status].some(Boolean)) return undefined;
  return [
    `Model profile: ${modelProfileName || 'Unknown'}`,
    `Model profile ID: ${modelProfileId || 'Unknown'}`,
    `Provider profile: ${providerProfileName || 'Unknown'}`,
    `Provider profile ID: ${providerProfileId || 'Unknown'}`,
    `Requested model: ${requested || 'Unknown'}`,
    `Actual model: ${actual || 'Unknown'}`,
    `Provider: ${provider || 'Unknown'}`,
    `Status: ${status || 'Unknown'}`,
  ].join('\n');
}

function extractResolutionLabel(value: unknown): string | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const resolution = value as Record<string, unknown>;
  for (const key of ['profile_name', 'profile_key', 'profile_alias', 'model_id']) {
    const item = resolution[key];
    if (typeof item === 'string' && item.trim()) return item.trim();
  }
  return undefined;
}

function formatMetrics(value: unknown, interrupted: boolean, t: ReturnType<typeof useTranslation>['t']): string {
  if (!value || typeof value !== 'object') return '';
  const metrics = value as Record<string, unknown>;
  const usageSource = typeof metrics.usage_source === 'string' ? metrics.usage_source : '';
  const promptTokens = numberValue(metrics.prompt_tokens);
  const providerTokens = numberValue(metrics.completion_tokens);
  const estimatedTokens = numberValue(metrics.estimated_completion_tokens);
  const tokens = providerTokens ?? estimatedTokens;
  const durationMs = numberValue(metrics.duration_ms);
  const firstTokenMs = numberValue(metrics.time_to_first_token_ms);
  const tokensPerSecond = numberValue(metrics.tokens_per_second);
  const parts: string[] = [];
  if (interrupted) parts.push(t('runs:panel.stop'));
  if (promptTokens !== undefined) {
    parts.push(t('runs:metrics.inputTokens', { count: promptTokens }));
  }
  if (tokens !== undefined) {
    const estimated = usageSource === 'estimated' || (providerTokens === undefined && estimatedTokens !== undefined);
    parts.push(t(estimated ? 'runs:metrics.estimatedOutputTokens' : 'runs:metrics.outputTokens', { count: tokens }));
  }
  if (tokensPerSecond !== undefined) {
    parts.push(t('runs:metrics.tokensPerSecond', { rate: tokensPerSecond.toFixed(1) }));
  }
  if (firstTokenMs !== undefined) {
    parts.push(`${formatSeconds(firstTokenMs)} first token`);
  } else if (durationMs !== undefined) {
    parts.push(formatSeconds(durationMs));
  }
  return parts.join(' · ');
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return undefined;
}

function nullableNumber(value: unknown): number | undefined {
  return numberValue(value);
}

function maxNumber(values: (number | undefined)[]): number | undefined {
  const filtered = values.filter((value): value is number => value !== undefined);
  return filtered.length ? Math.max(...filtered) : undefined;
}

function sumNumbers(values: (number | undefined)[]): number | undefined {
  const filtered = values.filter((value): value is number => value !== undefined);
  return filtered.length ? filtered.reduce((total, value) => total + value, 0) : undefined;
}

function booleanValue(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function textValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).map((item) => item.trim()).filter(Boolean) : [];
}

function uniqueStrings(values: (string | undefined)[]): string[] {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value && value.trim()))));
}

function plainRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isPlainRecord) : [];
}

function firstText(values: unknown[]): string | undefined {
  for (const value of values) {
    const text = textValue(value);
    if (text) return text;
  }
  return undefined;
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(ms < 1000 ? 1 : 1)}s`;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(value < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function truncateLabel(value: string): string {
  return value.length > 34 ? `${value.slice(0, 31)}...` : value;
}

function unwrapJsonString(value: string): string {
  try {
    const parsed = JSON.parse(value);
    return typeof parsed === 'string' ? parsed : value;
  } catch {
    return value;
  }
}

function shouldCollapseUserMessage(value: string): boolean {
  if (value.length > 600) return true;
  if (value.split(/\r\n|\r|\n/).length > 8) return true;
  return value.split(/\s+/).some((token) => token.length > 160);
}

