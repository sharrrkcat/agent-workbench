import type { Run } from './runs';
import type { Message } from './messages';
import type { Session } from './chat';

export type HarnessTool = {
  name: string;
  scope: 'general' | 'qqbot';
  description: string;
  parameters: Record<string, unknown>;
  risk: 'safe' | 'file' | 'network';
  requires_approval: boolean;
  direct_callable: boolean;
};

export type ToolRunResponse = { run: Run; messages: Message[]; session: Session };

export type WebSearchOptions = { max_results: number; zone: 'cn' | 'intl' | null; language: string | null };
export type WebLimits = { search_calls_per_run: number; fetch_calls_per_run: number; cache_ttl_hours: number; cache_retention_days: number };
export type WebToolsSettings = WebSearchOptions & WebLimits & { provider: 'anysearch'; has_api_key: boolean };
export type WebToolsSettingsPatch = Partial<WebSearchOptions & WebLimits> & { api_key?: string };
export type WebSource = { source_id: string; url: string; title: string };
export type WebDate = { value?: string; precision?: 'day' | 'month'; source?: 'url' | 'content'; uncertain: boolean };
export type WebPage = { url: string; title: string; source_id?: string; snippet?: string; content?: string;
  date?: WebDate; content_chars?: number; content_limited?: boolean; matched_queries?: number[] };
export type WebQuery = { query: string; recency: 'any' | 'week' | 'month' | 'year' };
export type WebSearchStatus = WebQuery & { status: 'success' | 'error' | 'duplicate'; error_code?: string };
export type WebRemaining = { search: number; fetch: number };
export type WebSearchStats = { candidates: number; duplicates: number; expired: number; unrelated: number; omitted: number; source_chars: number };
export type WebSearchResult = { searches: WebSearchStatus[]; results: WebPage[]; stats: WebSearchStats;
  retrieved_at: string; remaining: WebRemaining; truncated: boolean };
export type WebFetchResult = WebPage & { content: string; page: number; total_pages: number; order: 'document' | 'relevance';
  cache_hit: boolean; cached_at: string; content_hash: string; retrieved_at: string; remaining: WebRemaining;
  links: { text: string; url: string; offset: number }[]; notice?: 'no_more_content' | 'no_focus_match'; truncated: boolean };
