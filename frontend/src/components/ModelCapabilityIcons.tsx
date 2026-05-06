import { Brain, Eye, Hammer, Radio } from 'lucide-react';
import type { LlmProfile } from '../types';

export type ModelCapabilities = {
  vision?: boolean;
  tools?: boolean;
  reasoning?: boolean;
  streaming?: boolean;
};

export function ModelCapabilityIcons({ capabilities, className = '' }: { capabilities: ModelCapabilities; className?: string }) {
  const visible = Boolean(capabilities.vision || capabilities.tools || capabilities.reasoning || capabilities.streaming);
  if (!visible) return null;

  return (
    <div className={`capability-icons ${className}`.trim()} aria-label="Current model capabilities">
      {capabilities.vision ? (
        <span className="capability-icon vision" title="Vision supported" aria-label="Vision supported">
          <Eye size={14} aria-hidden="true" />
        </span>
      ) : null}
      {capabilities.tools ? (
        <span className="capability-icon tools" title="Tools supported" aria-label="Tools supported">
          <Hammer size={14} aria-hidden="true" />
        </span>
      ) : null}
      {capabilities.reasoning ? (
        <span className="capability-icon reasoning" title="Reasoning supported" aria-label="Reasoning supported">
          <Brain size={14} aria-hidden="true" />
        </span>
      ) : null}
      {capabilities.streaming ? (
        <span className="capability-icon streaming" title="Streaming supported" aria-label="Streaming supported">
          <Radio size={14} aria-hidden="true" />
        </span>
      ) : null}
    </div>
  );
}

export function capabilitiesFromProfile(profile: Pick<LlmProfile, 'supports_vision' | 'supports_tools' | 'supports_reasoning' | 'supports_streaming'>): ModelCapabilities {
  return {
    vision: Boolean(profile.supports_vision),
    tools: Boolean(profile.supports_tools),
    reasoning: Boolean(profile.supports_reasoning),
    streaming: Boolean(profile.supports_streaming),
  };
}
