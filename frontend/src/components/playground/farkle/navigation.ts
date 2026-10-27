import { farkleHost } from '@/components/playground/farkle/host';

export type FarkleNavigate = (url: string) => Promise<boolean>;
export const farkleHistoryUrl = (page = 1) => `${farkleHost.tableUrl}?view=history&page=${page}`;
export const isFarkleHistory = (search: string) => new URLSearchParams(search).get('view') === 'history';
