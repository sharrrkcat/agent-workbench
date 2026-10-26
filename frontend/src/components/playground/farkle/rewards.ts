import { SPECIAL_TYPES, type DieType } from './dice';
import type { Reward } from './economy';

type RewardEntry = { type: DieType; count: number };
type RewardGroup = { source: 'regular' | 'firstWin' | 'converted'; entries: RewardEntry[] };

export function rewardGroups(reward: Reward): RewardGroup[] {
  const regular: RewardEntry[] = SPECIAL_TYPES.map(({ id }) => ({ type: id, count: reward.special[id] }));
  regular.push({ type: 'merchant', count: reward.merchant - reward.firstWin - reward.converted });
  const groups: RewardGroup[] = [
    { source: 'regular', entries: regular },
    { source: 'firstWin', entries: [{ type: 'merchant', count: reward.firstWin }] },
    { source: 'converted', entries: [{ type: 'merchant', count: reward.converted }] },
  ];
  return groups.map((group) => ({ ...group, entries: group.entries.filter(({ count }) => count > 0) }))
    .filter(({ entries }) => entries.length > 0);
}
