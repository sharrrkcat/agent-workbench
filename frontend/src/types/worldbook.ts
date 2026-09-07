import type { BindingMode } from './chat';

export type WorldbookSettings = {
  worldbook_enabled: boolean;
  worldbook_max_entries_per_call: number;
  worldbook_max_context_chars: number;
  worldbook_regex_case_insensitive: boolean;
  worldbook_recursion_depth: number;
  worldbook_case_sensitive: boolean;
  worldbook_whole_words: boolean;
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
  activation_mode: string;
  enabled: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type SessionWorldbooksResponse = {
  session_id: string;
  mode: BindingMode;
  worldbook_ids: string[];
  effective_worldbook_ids: string[];
};
