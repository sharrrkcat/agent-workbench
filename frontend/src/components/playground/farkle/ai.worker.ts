import { FarkleAI, type AiDecision, type AiPosition } from './ai';
import type { DieType } from './dice';

export type AiRequest = { kind: 'prepare'; types: DieType[] } | { kind: 'decide'; id: number; position: AiPosition };
export type AiResponse = { id: number; decision: AiDecision };

let ai: FarkleAI;
self.onmessage = (event: MessageEvent<AiRequest>) => {
  const request = event.data;
  if (request.kind === 'prepare') ai = new FarkleAI(request.types);
  else self.postMessage({ id: request.id, decision: ai.decide(request.position) } satisfies AiResponse);
};
