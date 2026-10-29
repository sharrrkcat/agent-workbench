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
export type WebToolsSettings = WebSearchOptions & { provider: 'anysearch'; has_api_key: boolean };
export type WebToolsSettingsPatch = Partial<WebSearchOptions> & { api_key?: string };
export type WebSource = { source_id: string; url: string; title: string };
export type WebPage = WebSource & { snippet?: string; content?: string };
export type WebSearchResult = { provider: string; query: string; results: WebPage[]; request_id?: string; search_time_ms?: number };
export type WebFetchResult = WebPage & { provider: string; content: string; request_id?: string };
