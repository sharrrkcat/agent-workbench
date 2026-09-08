
export type WorldbookSettingsInput = {
  worldbook_enabled: boolean;
  worldbook_max_entries_per_call: number;
  worldbook_max_context_chars: number;
  worldbook_regex_case_insensitive: boolean;
  worldbook_recursion_depth: number;
  worldbook_case_sensitive: boolean;
  worldbook_whole_words: boolean;
};

export type WorldbookSettings = WorldbookSettingsInput & { id: number; created_at: string; updated_at: string };
export type WorldbookInput = { name: string; description?: string; enabled?: boolean };
export type ActivationMode = 'keyword' | 'always';
export type WorldbookEntryInput = {
  name: string;
  keywords_text: string;
  content: string;
  activation_mode: ActivationMode;
  enabled: boolean;
};

export type Worldbook = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  entry_count?: number;
  active_binding_count?: number;
  created_at: string;
  updated_at: string;
};

export type WorldbookEntry = {
  id: string;
  worldbook_id: string;
  name: string;
  keywords_text: string;
  content: string;
  activation_mode: ActivationMode;
  enabled: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type WorldbookMatchResponse = {
  matched_count: number;
  included_count: number;
  truncated: boolean;
  recursion_depth: number;
  recursion_rounds_used: number;
  case_sensitive: boolean;
  whole_words: boolean;
  warnings: Array<{ code: string; message: string; entry_id?: string; worldbook_id?: string }>;
  results: Array<{
    worldbook_id: string; worldbook_name: string; entry_id: string; entry_name: string;
    activation_mode: ActivationMode; matched_keywords: string[]; matched_by_recursion: boolean;
    recursion_depth: number; sort_order: number; content_preview: string;
  }>;
};

export type SessionWorldbooksResponse = {
  session_id: string;
  persona_worldbook_ids: string[];
  worldbook_ids: string[];
  effective_worldbook_ids: string[];
};
