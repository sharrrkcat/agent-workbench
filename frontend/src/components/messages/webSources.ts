import { unified, type Plugin } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import { decodeString } from 'micromark-util-decode-string';
import type { Nodes, Root, Text } from 'mdast';
import type { ElementContent } from 'hast';
import type { Message, MessagePart, ToolResultPart } from '@/types/messages';
import type { WebPage, WebSource } from '@/types/tools';

export type WebSourceMap = ReadonlyMap<string, WebSource>;
export type WebToolOutput = { pages: WebPage[]; content?: string };
export const isWebTool = (name: string) => name === 'web_search' || name === 'web_fetch';
export const sourceHostname = (source: Pick<WebPage, 'url'>) => new URL(source.url).hostname;
export const sourceTitle = (source: Pick<WebPage, 'url' | 'title'>) => source.title.trim() || sourceHostname(source);

function readPage(value: unknown): WebPage | null {
  if (!value || typeof value !== 'object') return null;
  const page = value as Record<string, unknown>;
  if ((page.source_id !== undefined && (typeof page.source_id !== 'string' || !/^W[1-9]\d*$/.test(page.source_id))) ||
      typeof page.url !== 'string' || typeof page.title !== 'string' ||
      (page.content !== undefined && typeof page.content !== 'string') ||
      (page.snippet !== undefined && typeof page.snippet !== 'string')) return null;
  try {
    const url = new URL(page.url);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
  } catch { return null; }
  return page as WebPage;
}

/** Tool data is an opaque JSON field at the HTTP/WS boundary. */
export function readWebToolOutput(part?: ToolResultPart): WebToolOutput | null {
  if (part?.status !== 'success' || !isWebTool(part.tool_name) || !part.data || typeof part.data !== 'object') return null;
  const data = part.data as Record<string, unknown>;
  if (part.tool_name === 'web_search') {
    if (!Array.isArray(data.results)) return null;
    const pages = data.results.map(readPage);
    return pages.every((page): page is WebPage => page !== null) ? { pages } : null;
  }
  const page = readPage(data);
  return page && typeof page.content === 'string' ? { pages: [page], content: page.content } : null;
}

export function webSourcesForReply(messages: Message[]): Map<string, WebSource> {
  const sources = new Map<string, WebSource>();
  for (const message of messages) for (const part of message.parts) {
    if (part.type !== 'tool_result') continue;
    for (const page of readWebToolOutput(part)?.pages ?? []) {
      if (!page.source_id) continue;
      const previous = sources.get(page.source_id);
      sources.set(page.source_id, { source_id: page.source_id, url: page.url, title: page.title || previous?.title || '' });
    }
  }
  return sources;
}

type Citation = { start: number; end: number; source: WebSource };

export function citationMatches(text: string, sources: WebSourceMap, markdown = false): Citation[] {
  const citations: Citation[] = [];
  for (const match of text.matchAll(/\[(W[1-9]\d*)\]/g)) {
    const source = sources.get(match[1]);
    if (!source) continue;
    let backslashes = 0;
    for (let index = match.index! - 1; index >= 0 && text[index] === '\\'; index--) backslashes++;
    if (markdown && backslashes % 2) continue;
    citations.push({ start: match.index!, end: match.index! + match[0].length, source });
  }
  return citations;
}

function visitText(node: Nodes, visit: (node: Text) => void): void {
  if (['link', 'linkReference', 'image', 'imageReference', 'code', 'inlineCode', 'html', 'definition'].includes(node.type)) return;
  if (node.type === 'text') visit(node);
  else if ('children' in node) for (const child of node.children) visitText(child, visit);
}

const parser = unified().use(remarkParse).use(remarkGfm);

function markdownCitations(text: string, sources: WebSourceMap): Citation[] {
  const found: Citation[] = [];
  visitText(parser.parse(text), (node) => {
    const start = node.position!.start.offset!;
    const raw = text.slice(start, node.position!.end.offset);
    found.push(...citationMatches(raw, sources, true).map((citation) => ({
      ...citation, start: start + citation.start, end: start + citation.end,
    })));
  });
  return found;
}

export function citedWebSources(parts: MessagePart[], sources: WebSourceMap): WebSource[] {
  const used = new Map<string, WebSource>();
  for (const part of parts) {
    if (part.type !== 'text') continue;
    const matches = part.format === 'plain' ? citationMatches(part.text, sources) : markdownCitations(part.text, sources);
    for (const { source } of matches) if (!used.has(source.url)) used.set(source.url, source);
  }
  return [...used.values()];
}

export function copyWebAnswer(parts: MessagePart[], sources: WebSourceMap): string {
  return parts.filter((part) => part.type === 'text').map((part) => {
    let text = part.text;
    const matches = part.format === 'plain' ? citationMatches(text, sources) : markdownCitations(text, sources);
    for (const { start, end, source } of matches.reverse()) {
      const title = sourceTitle(source).replace(/[\\[\]]/g, '\\$&');
      const url = source.url.replace(/[<>\s]/g, (value) => encodeURIComponent(value));
      text = text.slice(0, start) + `[${title}](<${url}>)` + text.slice(end);
    }
    return text;
  }).join('\n\n');
}

/** Attach citation links to text nodes after Markdown has identified code and links. */
export const remarkWebCitations: Plugin<[WebSourceMap | undefined], Root> = (sources) => (tree, file) => {
  if (!sources?.size) return;
  const markdown = String(file);
  visitText(tree, (node) => {
    const raw = markdown.slice(node.position!.start.offset, node.position!.end.offset);
    const matches = citationMatches(raw, sources, true);
    if (!matches.length) return;
    const children: ElementContent[] = [];
    let position = 0;
    for (const { start, end, source } of matches) {
      const marker = raw.slice(start, end);
      // Markdown removes container indentation and decodes escapes/entities. Match
      // the same occurrence in the parsed text instead of treating raw offsets as text offsets.
      const occurrence = decodeString(raw.slice(0, start)).split(marker).length;
      let decodedStart = -marker.length;
      for (let index = 0; index < occurrence; index++) decodedStart = node.value.indexOf(marker, decodedStart + marker.length);
      const decodedEnd = decodedStart + marker.length;
      children.push({ type: 'text', value: node.value.slice(position, decodedStart) });
      children.push({ type: 'element', tagName: 'a', properties: { href: source.url, 'data-web-source': source.source_id },
        children: [{ type: 'text', value: `[${source.source_id}]` }] });
      position = decodedEnd;
    }
    children.push({ type: 'text', value: node.value.slice(position) });
    node.data = { ...node.data, hName: 'span', hChildren: children };
  });
};
