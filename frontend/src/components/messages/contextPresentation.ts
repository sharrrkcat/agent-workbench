import type { ContextDetail, ContextSource, ContextSourceKind } from '../../types/context';

export type DisplayContextSource = ContextSource & { empty?: boolean };
const systemOrder: ContextSourceKind[] = ['instruction', 'character', 'persona', 'memory_instruction', 'memory_index', 'qq_runtime'];
const rank = (source: DisplayContextSource) => source.id === 'history-instruction' ? 4.5
  : systemOrder.includes(source.kind) ? systemOrder.indexOf(source.kind) : systemOrder.length;

export function contextPresentation(detail: ContextDetail) {
  const sources: DisplayContextSource[] = detail.sources.map((source) => ({ ...source }));
  const empty = detail.exclusions.filter((item) => systemOrder.includes(item.kind) &&
    ['empty', 'no_bindings', 'no_results'].includes(item.reason));
  if (empty.length) {
    let system = sources.find((source) => source.kind === 'system');
    if (!system) {
      system = { id: 'empty:system', kind: 'system', role: 'system', text: '', char_count: 0, empty: true };
      sources.unshift(system);
    }
    for (const item of empty) {
      if (!sources.some((source) => source.kind === item.kind)) sources.push({
        id: `empty:${item.kind}`, kind: item.kind, parent_id: system.id, role: 'system',
        reference_id: item.reference_id, name: item.name, text: '', char_count: 0, empty: true,
      });
    }
  }
  const byParent = new Map<string | null, DisplayContextSource[]>();
  for (const source of sources) {
    const parent = source.parent_id || null;
    byParent.set(parent, [...(byParent.get(parent) || []), source]);
  }
  for (const source of sources.filter((item) => item.kind === 'system' || item.kind === 'memory_index')) {
    byParent.get(source.id)?.sort((a, b) => {
      if (a.empty || b.empty) return rank(a) - rank(b);
      return (a.message_index ?? 0) - (b.message_index ?? 0)
        || (a.start ?? 0) - (b.start ?? 0) || rank(a) - rank(b);
    });
  }
  return { sources, byParent, exclusions: detail.exclusions.filter((item) => !empty.includes(item)) };
}
