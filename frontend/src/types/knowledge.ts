
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

export type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  aliases_text: string;
  embedding_model_profile_id: string;
  enabled: boolean;
  index_status: string;
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
  status: string;
  error?: string | null;
  chunks: number;
  indexed_at?: string | null;
  created_at: string;
  updated_at: string;
  [key: string]: unknown;
};

export type SessionKnowledgeBindings = {
  session_id: string;
  persona_knowledge_base_ids: string[];
  knowledge_base_ids: string[];
  effective_knowledge_base_ids: string[];
};

export type KnowledgeSearchResponse = {
  query: string;
  results: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
  debug?: Record<string, unknown>;
  context_preview?: string;
};
