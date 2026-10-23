// Convert the authenticated Worker build to Cloudflare Pages advanced mode.
// Keep the Worker byte-for-byte identical; do not publish separate client files.
import { lstat, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = resolve(root, 'pages-dist');
if (relative(root, output) !== 'pages-dist') throw new Error('Pages destination is outside the project');
try {
  if ((await lstat(output)).isSymbolicLink()) throw new Error('Pages destination must not be a symlink');
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}

const worker = await readFile(resolve(root, 'dist/server/index.js'));
if (!worker.includes(Buffer.from('export default createPasswordGate(assets);'))) {
  throw new Error('Build the authenticated Worker before the Pages distribution');
}
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await writeFile(resolve(output, '_worker.js'), worker);
await writeFile(resolve(output, '_routes.json'), JSON.stringify({
  version: 1,
  include: ['/*'],
  exclude: [],
}, null, 2) + '\n');
console.log('Cloudflare Pages advanced-mode build: unchanged authenticated Worker, all routes protected');
