export type ProfileKeySource = {
  id?: string | null;
  alias?: string | null;
};

export function sanitizeProfileKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/_+/g, '_')
    .replace(/-+/g, '-')
    .replace(/^[^a-z0-9]+/, '')
    .replace(/[^a-z0-9]+$/, '');
}

export function finalSafeRefSegment(value: string | null | undefined, prefix: string): string {
  const text = String(value || '').trim();
  if (!text.startsWith(prefix)) return '';
  return text.slice(prefix.length).split(/[\\/]/).filter(Boolean).pop() || '';
}

export function profileKeyBase(candidates: Array<string | null | undefined>, fallback = 'profile'): string {
  for (const candidate of candidates) {
    const key = sanitizeProfileKey(String(candidate || ''));
    if (key) return key;
  }
  return fallback;
}

export function uniqueProfileKey(
  candidates: Array<string | null | undefined>,
  profiles: ProfileKeySource[],
  currentProfileId?: string | null,
  fallback = 'profile',
): string {
  const base = profileKeyBase(candidates, fallback);
  const existing = new Set(
    profiles
      .filter((profile) => profile.id !== currentProfileId)
      .flatMap((profile) => [profile.alias, profile.id])
      .filter(Boolean)
      .map((value) => String(value).toLowerCase()),
  );
  if (!existing.has(base)) return base;
  let index = 2;
  while (existing.has(`${base}-${index}`)) {
    index += 1;
  }
  return `${base}-${index}`;
}
