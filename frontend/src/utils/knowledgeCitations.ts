export type ParsedKnowledgeCitation = {
  token: string;
  labels: string[];
};

export function parseKnowledgeCitationToken(token: string): ParsedKnowledgeCitation | null {
  if (!/^\[K\d+(?:\s*(?:,|-|–)\s*K\d+)*\]$/.test(token)) return null;
  const body = token.slice(1, -1);
  const labels: string[] = [];
  const seen = new Set<string>();

  for (const part of body.split(',')) {
    const item = part.trim();
    const range = item.match(/^K(\d+)\s*[-–]\s*K(\d+)$/);
    const single = item.match(/^K(\d+)$/);
    if (range) {
      const start = Number(range[1]);
      const end = Number(range[2]);
      if (!Number.isInteger(start) || !Number.isInteger(end) || start > end || end - start + 1 > 20) return null;
      for (let value = start; value <= end; value += 1) {
        const label = `K${value}`;
        if (!seen.has(label)) {
          labels.push(label);
          seen.add(label);
        }
      }
      continue;
    }
    if (!single) return null;
    const label = `K${Number(single[1])}`;
    if (!seen.has(label)) {
      labels.push(label);
      seen.add(label);
    }
  }

  return labels.length ? { token, labels } : null;
}
