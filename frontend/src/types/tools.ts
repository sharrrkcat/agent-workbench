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
