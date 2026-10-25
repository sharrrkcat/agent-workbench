export type DiePoint = { id: string; index: number; x: number; y: number };
export type Direction = 'w' | 'a' | 's' | 'd';

export function nextHoveredDie(points: DiePoint[], currentId: string | null, direction: Direction): string | null {
  const current = points.find((point) => point.id === currentId);
  if (!current) return points[0]?.id ?? null;
  const candidates = points.filter((point) => {
    if (direction === 'w') return point.y < current.y;
    if (direction === 's') return point.y > current.y;
    if (direction === 'a') return point.x < current.x;
    return point.x > current.x;
  });
  const distance = (point: DiePoint) => (point.x - current.x) ** 2 + (point.y - current.y) ** 2;
  candidates.sort((a, b) => distance(a) - distance(b) || a.index - b.index);
  return candidates[0]?.id ?? current.id;
}
