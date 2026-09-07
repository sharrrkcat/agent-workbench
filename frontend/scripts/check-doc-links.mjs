import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import GithubSlugger from 'github-slugger';

const root = fileURLToPath(new URL('../../', import.meta.url));
const parser = unified().use(remarkParse);
const documents = new Map();
const ignored = new Set([
  '.git',
  '.venv',
  '.pytest_cache',
  'node_modules',
  'dist',
  'build',
  'data',
  'test-results',
  'playwright-report',
]);

function walk(node, visit) {
  visit(node);
  for (const child of node.children || []) walk(child, visit);
}

function files(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (ignored.has(entry.name) || entry.isSymbolicLink()) return [];
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? files(target) : target.endsWith('.md') ? [target] : [];
  });
}

function document(filename) {
  if (documents.has(filename)) return documents.get(filename);
  const tree = parser.parse(fs.readFileSync(filename, 'utf8'));
  const definitions = new Map();
  const anchors = new Set();
  const slugger = new GithubSlugger();
  walk(tree, (node) => {
    if (node.type === 'definition') definitions.set(node.identifier, node.url);
    if (node.type !== 'heading') return;
    let text = '';
    walk(node, (child) => {
      if (['text', 'inlineCode'].includes(child.type)) text += child.value;
      if (child.type === 'image') text += child.alt || '';
    });
    anchors.add(slugger.slug(text));
  });
  const result = { tree, definitions, anchors };
  documents.set(filename, result);
  return result;
}

const failures = [];
let links = 0;
const markdown = files(root);
for (const filename of markdown) {
  const { tree, definitions } = document(filename);
  walk(tree, (node) => {
    const target = ['link', 'image'].includes(node.type)
      ? node.url
      : ['linkReference', 'imageReference'].includes(node.type)
        ? definitions.get(node.identifier)
        : null;
    if (!target || /^[a-z][a-z\d+.-]*:/i.test(target) || target.startsWith('//')) return;
    links += 1;
    const base = target.startsWith('/') ? pathToFileURL(root) : pathToFileURL(filename);
    const url = new URL(target.startsWith('/') ? '.' + target : target, base);
    const local = fileURLToPath(url);
    const source = path.relative(root, filename) + ':' + (node.position?.start.line || 1);
    if (!fs.existsSync(local)) {
      failures.push(`${source}: missing ${target}`);
      return;
    }
    if (url.hash && local.endsWith('.md') && !document(local).anchors.has(decodeURIComponent(url.hash.slice(1)))) {
      failures.push(`${source}: missing anchor ${target}`);
    }
  });
}
if (failures.length) {
  failures.forEach((failure) => console.error(failure));
  process.exitCode = 1;
} else {
  console.log(`documentation links: ${links} local links across ${markdown.length} Markdown files passed`);
}
