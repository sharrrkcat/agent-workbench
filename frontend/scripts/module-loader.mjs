import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const moduleUrl = (source) => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const values = new Map();
globalThis.workbenchTestModules = values;
let sequence = 0;

export const sourceUrl = (relative) => new URL('../src/' + relative, import.meta.url).href;

export function mockModule(exports) {
  const id = ++sequence;
  values.set(id, exports);
  return moduleUrl(
    Object.keys(exports)
      .map((key) =>
        key === 'default'
          ? `export default globalThis.workbenchTestModules.get(${id}).default;`
          : `export const ${key} = globalThis.workbenchTestModules.get(${id})[${JSON.stringify(key)}];`,
      )
      .join('\n'),
  );
}

export function apiMocks(api) {
  return Object.fromEntries(
    ['chat', 'models', 'runs', 'tools', 'knowledge', 'worldbook', 'settings'].map((domain) => [
      sourceUrl(`api/${domain}.ts`),
      mockModule({ [domain + 'Api']: api }),
    ]),
  );
}

// Load the actual TypeScript module graph. Tests replace boundary modules, not
// implementation source strings, so moving code cannot bypass the assertions.
export function createModuleLoader(mocks = {}) {
  const cache = new Map();

  function resolve(specifier, parent) {
    if (mocks[specifier]) return mocks[specifier];
    if (!specifier.startsWith('.') && !specifier.startsWith('file:')) return import.meta.resolve(specifier);
    const url = new URL(specifier, parent);
    let filename = fileURLToPath(url);
    if (!path.extname(filename))
      filename = ['.ts', '.tsx', '.js', '.json'].map((ext) => filename + ext).find(fs.existsSync);
    if (!filename) throw new Error(`Cannot resolve ${specifier} from ${parent}`);
    const resolved = pathToFileURL(filename).href;
    return mocks[resolved] || resolved;
  }

  async function build(url) {
    if (!url.startsWith('file:') || url.includes('/node_modules/')) return url;
    if (cache.has(url)) return cache.get(url);
    const job = (async () => {
      const filename = fileURLToPath(url);
      const source = fs.readFileSync(filename, 'utf8');
      if (filename.endsWith('.json')) return moduleUrl(`export default ${source};`);
      const compiled = ts.transpileModule(source, {
        fileName: filename,
        compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
      }).outputText;
      const tree = ts.createSourceFile(filename, compiled, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
      const edits = [];
      for (const node of tree.statements) {
        if (!(ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) || !node.moduleSpecifier) continue;
        const child = await build(resolve(node.moduleSpecifier.text, url));
        edits.push([node.moduleSpecifier.getStart(tree), node.moduleSpecifier.end, JSON.stringify(child)]);
      }
      let output = compiled;
      for (const [start, end, value] of edits.reverse()) output = output.slice(0, start) + value + output.slice(end);
      return moduleUrl('import.meta.env = {};\n' + output + '\n//# sourceURL=' + url);
    })();
    cache.set(url, job);
    return job;
  }

  return async (relative) => {
    const url = await build(resolve(relative, import.meta.url));
    return { url, exports: await import(url) };
  };
}
