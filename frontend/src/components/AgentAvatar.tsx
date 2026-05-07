import { useEffect, useState } from 'react';
import { Bot } from 'lucide-react';
import { API_BASE_URL } from '../api/client';
import { resolveAvatarUrlFromBase } from '../api/url';
import type { Agent, ManifestSummary } from '../types';

type AvatarSource = Pick<Agent, 'id' | 'name' | 'avatar' | 'avatar_type' | 'avatar_url'> | ManifestSummary;

export function AgentAvatar({
  agent,
  label,
  className = 'agent-avatar',
  iconSize = 16,
}: {
  agent?: AvatarSource;
  label?: string;
  className?: string;
  iconSize?: number;
}) {
  const fallbackLabel = label || agent?.name || agent?.id || 'AI';
  const [imageFailed, setImageFailed] = useState(false);
  const imageUrl = resolveImageUrl(agent?.avatar_type === 'image' ? agent.avatar_url : null);

  useEffect(() => {
    setImageFailed(false);
  }, [imageUrl]);

  if (imageUrl && !imageFailed) {
    return (
      <div className={className} aria-hidden="true">
        <img src={imageUrl} alt="" onError={() => setImageFailed(true)} />
      </div>
    );
  }

  const text = avatarText(agent, fallbackLabel);
  return (
    <div className={className} aria-hidden="true">
      {text || <Bot size={iconSize} />}
    </div>
  );
}

function avatarText(agent: AvatarSource | undefined, fallbackLabel: string): string {
  if (agent?.avatar_type === 'emoji' || agent?.avatar_type === 'text') {
    return agent.avatar?.trim() || initials(fallbackLabel);
  }
  if (agent?.avatar_type === 'initials' || agent?.avatar_type === 'image') {
    return initials(fallbackLabel);
  }
  return agent?.avatar?.trim() || initials(fallbackLabel);
}

function resolveImageUrl(value?: string | null): string {
  return resolveAvatarUrlFromBase(API_BASE_URL, value);
}

function initials(value: string): string {
  const words = value
    .replace(/[/_-]/g, ' ')
    .split(/\s+/)
    .filter(Boolean);
  return words
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join('');
}
