export type LLMUsage = {
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  prompt_tokens_details: { cached_tokens: number | null } | null;
  completion_tokens_details: { reasoning_tokens: number | null } | null;
};

export type LLMTiming = {
  first_response_ms: number | null;
  total_ms: number | null;
  queue_ms: number | null;
  load_ms: number | null;
  generation_ms: number | null;
  generation_tokens: number | null;
  tokens_per_second: number | null;
  tps_source: 'native' | 'estimated' | null;
};

export type LLMCallSnapshot = {
  model_profile_id: string;
  model: string;
  message_id: string;
  started_at: string;
  first_response_at: string | null;
  completed: boolean;
  usage: LLMUsage | null;
  timing: LLMTiming;
};
