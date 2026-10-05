import type { QQResourceQuery } from '../../api/qq';
import { projectResourcesUrl } from './navigation';

export function readResourceQuery(search: string): QQResourceQuery {
  const params = new URLSearchParams(search);
  const page = Number(params.get('page') || 1);
  const favorite = params.get('favorite');
  return { page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    sort: params.get('sort') === 'size' ? 'size' : 'created_at',
    order: params.get('order') === 'asc' ? 'asc' : 'desc',
    favorite: favorite === 'favorites' || favorite === 'unfavorited' ? favorite : 'all' };
}

export function resourceQueryUrl(projectId: string, query: QQResourceQuery) {
  return projectResourcesUrl(projectId) + '?' + new URLSearchParams({ ...query, page: String(query.page) });
}

export function resourcePages(page: number, total: number): Array<number | 'ellipsis'> {
  const pages = [...new Set([1, page - 1, page, page + 1, total])].filter((n) => n > 0 && n <= total).sort((a, b) => a - b);
  return pages.flatMap((value, index) => index && value - pages[index - 1] > 1 ? ['ellipsis', value] as const : [value]);
}
