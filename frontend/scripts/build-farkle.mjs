import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const frontend = fileURLToPath(new URL('..', import.meta.url));
const { values } = parseArgs({ options: { 'out-dir': { type: 'string' } } });
const output = path.resolve(values['out-dir'] || path.join(frontend, 'dist-farkle'));
const buildRoot = path.resolve(frontend, '../build');
await fs.mkdir(buildRoot, { recursive: true });
const stage = await fs.mkdtemp(path.join(buildRoot, 'farkle-'));
const manifest = '.farkle-generated.json';
const ownedFile = (file) => ['index.html', '.nojekyll'].includes(file)
  || /^assets\/[A-Za-z0-9_.-]+$/.test(file);

try {
  await build({
    configFile: false,
    root: path.join(frontend, 'src/standalone'),
    base: './',
    publicDir: false,
    plugins: [react(), tailwindcss()],
    resolve: { alias: [
      { find: '@/components/playground/farkle/host', replacement: path.join(frontend, 'src/standalone/host.ts') },
      { find: '@', replacement: path.join(frontend, 'src') },
    ] },
    build: { outDir: stage, emptyOutDir: false, chunkSizeWarningLimit: 10000 },
  });
  await fs.writeFile(path.join(stage, '.nojekyll'), '');
  const assets = await fs.readdir(path.join(stage, 'assets'));
  const files = ['index.html', '.nojekyll', ...assets.map((name) => `assets/${name}`)];
  for (const file of files.filter((name) => /\.(html|js|css)$/.test(name))) {
    const content = await fs.readFile(path.join(stage, file), 'utf8');
    if (/cogita|\/playground\/|\/api\//i.test(content)) throw new Error(`Unexpected application content in ${file}`);
  }

  await fs.mkdir(output, { recursive: true });
  const previousPath = path.join(output, manifest);
  const previous = await fs.readFile(previousPath, 'utf8').then(JSON.parse).catch((error) => {
    if (error.code === 'ENOENT') return [];
    throw error;
  });
  if (!Array.isArray(previous) || ![...previous, ...files].every((file) => typeof file === 'string' && ownedFile(file))) {
    throw new Error('Invalid generated-file manifest. No destination files were changed.');
  }
  // Validate the publication boundary before replacing or removing any files.
  for (const file of [manifest, 'assets', ...new Set([...previous, ...files])]) {
    const stat = await fs.lstat(path.join(output, file)).catch((error) => {
      if (error.code === 'ENOENT') return null;
      throw error;
    });
    if (stat?.isSymbolicLink()) throw new Error(`Refusing to publish through a symbolic link: ${file}`);
    if (stat && files.includes(file) && !previous.includes(file)) {
      throw new Error(`Refusing to overwrite a non-generated file: ${file}`);
    }
  }
  await fs.mkdir(path.join(output, 'assets'), { recursive: true });
  for (const file of files) await fs.copyFile(path.join(stage, file), path.join(output, file));
  for (const file of previous.filter((file) => !files.includes(file))) await fs.rm(path.join(output, file), { force: true });
  await fs.writeFile(previousPath, JSON.stringify(files, null, 2) + '\n');
  console.log(`Farkle static site: ${output}`);
} finally {
  const resolvedStage = await fs.realpath(stage);
  const resolvedBuild = await fs.realpath(buildRoot);
  if (path.dirname(resolvedStage) !== resolvedBuild || !path.basename(resolvedStage).startsWith('farkle-')) {
    throw new Error(`Unexpected staging directory: ${resolvedStage}`);
  }
  await fs.rm(resolvedStage, { recursive: true, force: true });
}
