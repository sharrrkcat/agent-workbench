
export type KnowledgeSettings = {
  id: number;
  reranker_enabled: boolean;
  reranker_model_profile_id: string | null;
  reranker_candidate_limit: number;
  hybrid_search_enabled: boolean;
  default_vector_candidate_k: number;
  default_keyword_candidate_k: number;
  default_final_top_k: number;
  default_max_context_chars: number;
  default_min_score: number | null;
  min_score_threshold: number | null;
  retrieval_max_chunks_per_source: number | null;
  retrieval_max_chunks_per_knowledge_base: number | null;
  rrf_k: number;
  default_chunk_size: number;
  default_chunk_overlap: number;
  max_source_size_bytes: number;
  max_chunks_per_source: number;
  max_total_index_chars_per_source: number;
  knowledge_context_instruction: string;
  knowledge_context_snippet_template: string;
};

export type KnowledgeSettingsInput = Omit<KnowledgeSettings, 'id'>;
export type KnowledgeIndexStatus = 'empty' | 'ready' | 'indexing' | 'failed' | 'needs_reindex';
export type KnowledgeSourceStatus = 'pending' | 'indexing' | 'indexed' | 'needs_reindex' | 'failed' | 'deleted';
export type KnowledgeBaseInput = {
  name: string;
  embedding_model_profile_id: string;
  description?: string;
  aliases_text?: string;
  enabled?: boolean;
  vector_candidate_k_override?: number | null;
  keyword_candidate_k_override?: number | null;
  final_top_k_override?: number | null;
  max_context_chars_override?: number | null;
};

export type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  aliases_text: string;
  embedding_model_profile_id: string;
  enabled: boolean;
  index_status: KnowledgeIndexStatus;
  index_error?: string | null;
  vector_candidate_k_override?: number | null;
  keyword_candidate_k_override?: number | null;
  final_top_k_override?: number | null;
  max_context_chars_override?: number | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgeSource = {
  id: string;
  knowledge_base_id: string;
  source_type: 'pasted_text' | 'attachment_text' | 'file';
  uri: string;
  title: string;
  relative_path?: string;
  status: KnowledgeSourceStatus;
  error?: string | null;
  chunks: number;
  indexed_at?: string | null;
  created_at: string;
  updated_at: string;
  size_bytes: number;
  content_hash: string;
  metadata: Record<string, unknown>;
};

export type KnowledgeSourceIndexResult = {
  source_id: string;
  status: KnowledgeSourceStatus;
  chunks: number;
  embedding_model_profile_id?: string | null;
  embedding_dimension?: number | null;
  indexed_at?: string | null;
  error?: string | null;
  skipped?: boolean;
};

export type KnowledgeSourcePreview = { source_id: string; title: string; uri: string; content: string; truncated: boolean };
export type KnowledgeSourceChunk = {
  chunk_id: string; chunk_index: number; heading_path: string; char_start: number; char_end: number;
  content: string; content_preview: string; truncated: boolean; embedding_dimension?: number | null;
  metadata: Record<string, unknown>;
};

export type KnowledgeSearchInput = {
  query: string; knowledge_base_ids?: string[]; session_id?: string; top_k?: number; max_context_chars?: number;
  min_score_threshold?: number; max_chunks_per_source?: number; max_chunks_per_knowledge_base?: number; debug?: boolean;
};

export type SessionKnowledgeBindings = {
  session_id: string;
  persona_knowledge_base_ids: string[];
  knowledge_base_ids: string[];
  effective_knowledge_base_ids: string[];
};

export type KnowledgeSearchResponse = {
  query: string;
  results: Array<{
    chunk_id: string; knowledge_base_id: string; source_id: string; title: string; heading_path: string;
    content: string; truncated: boolean; vector_score: number | null; vector_rank: number | null;
    keyword_score: number | null; keyword_rank: number | null; rrf_score: number; rerank_score: number | null;
  }>;
  metadata?: { rerank_fallback: boolean; reranker_enabled: boolean; reranker_used: boolean };
  debug?: { warnings: string[]; merged_candidate_count: number; reranker_failed: boolean; [key: string]: unknown };
  context_preview?: string;
};
