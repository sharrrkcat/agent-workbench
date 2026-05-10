import { Brain, Eye, Hammer, Radio } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { LlmProfile } from '../types';

export type ModelCapabilities = {
  vision?: boolean;
  tools?: boolean;
  reasoning?: boolean;
  streaming?: boolean;
};

export function ModelCapabilityIcons({ capabilities, className = '' }: { capabilities: ModelCapabilities; className?: string }) {
  const { t } = useTranslation('llm');
  const visible = Boolean(capabilities.vision || capabilities.tools || capabilities.reasoning || capabilities.streaming);
  if (!visible) return null;

  return (
    <div className={`capability-icons ${className}`.trim()} aria-label={t('labels.currentModelCapabilities')}>
      {capabilities.vision ? (
        <span className="capability-icon vision" title={t('labels.visionSupported')} aria-label={t('labels.visionSupported')}>
          <Eye size={14} aria-hidden="true" />
        </span>
      ) : null}
      {capabilities.tools ? (
        <span className="capability-icon tools" title={t('labels.toolsSupported')} aria-label={t('labels.toolsSupported')}>
          <Hammer size={14} aria-hidden="true" />
        </span>
      ) : null}
      {capabilities.reasoning ? (
        <span
          className="capability-icon reasoning"
          title={t('help.reasoningOutput')}
          aria-label={t('labels.reasoningOutput')}
        >
          <Brain size={14} aria-hidden="true" />
        </span>
      ) : null}
      {capabilities.streaming ? (
        <span className="capability-icon streaming" title={t('labels.streamingSupported')} aria-label={t('labels.streamingSupported')}>
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
