import { countTokens } from 'gpt-tokenizer/encoding/o200k_base';

self.onmessage = (event: MessageEvent<{ key: string; sources: { id: string; text: string }[] }>) => {
  const counts: Record<string, number | null> = {};
  for (const source of event.data.sources) {
    try {
      counts[source.id] = countTokens(source.text, { disallowedSpecial: new Set() });
    } catch {
      counts[source.id] = null;
    }
  }
  self.postMessage({ key: event.data.key, counts });
};
