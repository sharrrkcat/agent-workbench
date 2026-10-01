import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';

const parser = unified().use(remarkParse).use(remarkGfm);

type TextNode = { type: string; value?: string; alt?: string | null; children?: TextNode[] };

function readableText(node: TextNode): string {
  if (node.type === 'definition' || node.type === 'html') return '';
  if (node.type === 'image' || node.type === 'imageReference') return node.alt || '';
  if (node.type === 'break') return ' ';
  if (node.value !== undefined) return node.value;
  const separator = ['root', 'blockquote', 'list', 'listItem', 'table', 'tableRow'].includes(node.type) ? ' ' : '';
  return (node.children || []).map(readableText).join(separator);
}

export function reasoningText(markdown: string): string {
  return readableText(parser.parse(markdown)).replace(/\s+/g, ' ').trim();
}
