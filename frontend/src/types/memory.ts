export type MemoryPool = 'character' | 'general';
export type MemoryIsolation = 'shared' | 'block_outgoing' | 'block_incoming' | 'isolated';
export type MemoryStatus = 'active' | 'needs_review' | 'deleted';
export type MemoryPreview = {
  id: string; revision: number; pool: MemoryPool; character_id: string; persona_id: string; session_id: string | null;
  summary: string; status: MemoryStatus; managed_by: 'user' | 'model'; pinned: boolean; observed_at: string; updated_at: string;
};
export type MemoryEntry = MemoryPreview & {
  body: string; created_at: string;
  origin: { character_id: string; persona_id: string; session_id: string | null; run_id: string | null;
    evidence: { message_id: string; digest: string }[] };
  publication: { memory_id: string; revision: number } | null;
};
export type MemoryCreate = Pick<MemoryEntry, 'pool' | 'character_id' | 'persona_id' | 'session_id' | 'summary' | 'body' | 'pinned'> & { source_message_id?: string };
export type MemoryEdit = { expected_revision: number; summary: string; body: string; status: 'active' | 'needs_review'; pinned: boolean };
export type MemoryPage = { items: MemoryPreview[]; total: number; next_offset: number | null };
export type MemoryDeletionPreview = { revision: string; local: MemoryPreview[]; general: MemoryPreview[] };
export type MemoryDeletionChoice = { expected_revision?: string; local?: 'delete' | 'keep' | 'transfer' | 'publish';
  general?: 'delete' | 'keep'; target_character_id?: string | null };
export type MemoryQuery = { pool?: MemoryPool; character_id?: string; persona_id?: string; session_id?: string; origin_session_id?: string;
  status?: 'active' | 'needs_review'; q?: string; offset?: number; limit?: number };
