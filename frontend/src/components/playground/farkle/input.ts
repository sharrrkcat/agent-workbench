export type DiePoint = { id: string; index: number; x: number; y: number };
export type Direction = 'w' | 'a' | 's' | 'd';

export function nextHoveredDie(points: DiePoint[], currentId: string | null, direction: Direction): string | null {
  const current = points.find((point) => point.id === currentId);
  if (!current) return points[0]?.id ?? null;
  const candidates = points.filter((point) => {
    const dx = point.x - current.x, dy = point.y - current.y;
    const horizontal = direction === 'a' || direction === 'd';
    const forward = direction === 'a' ? -dx : direction === 'd' ? dx : direction === 'w' ? -dy : dy;
    return forward > 0 && Math.abs(horizontal ? dy : dx) <= forward;
  });
  const distance = (point: DiePoint) => (point.x - current.x) ** 2 + (point.y - current.y) ** 2;
  candidates.sort((a, b) => distance(a) - distance(b) || a.index - b.index);
  return candidates[0]?.id ?? current.id;
}
