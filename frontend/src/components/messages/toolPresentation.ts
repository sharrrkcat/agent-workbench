export function toolArgumentsSummary(args: Record<string, unknown>): string {
  const entries = Object.entries(args);
  const valueText = (value: unknown) => (typeof value === 'string' ? value : JSON.stringify(value)).replace(/\s+/g, ' ').trim();
  return entries.length === 1
    ? valueText(entries[0][1])
    : entries.map(([key, value]) => `${key}=${valueText(value)}`).join(' ');
}
