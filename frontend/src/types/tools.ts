import type { Run } from './runs';
import type { Message } from './messages';
import type { Session } from './chat';

export type HarnessTool = {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  risk: 'safe' | 'file' | 'network';
  requires_approval: boolean;
  direct_callable: boolean;
};

export type HarnessSettings = { searxng_base_url: string | null };

export type ToolRunResponse = { run: Run; messages: Message[]; session: Session };
