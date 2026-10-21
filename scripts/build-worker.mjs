// Package the Vite build inside the Worker so every application resource passes
// the server authentication gate. No public/static asset bypass is emitted.
import {readFile, writeFile, readdir, mkdir, rm} from 'node:fs/promises';
import {resolve, relative, sep, extname} from 'node:path';
import {fileURLToPath} from 'node:url';
const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const client = resolve(root, '.client-build');
const dist = resolve(root, 'dist');
if (relative(root, dist) !== 'dist') throw new Error('Build destination is outside the project');
const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.py':'text/plain; charset=utf-8','.whl':'application/zip','.svg':'image/svg+xml','.png':'image/png','.csv':'text/csv; charset=utf-8','.json':'application/json; charset=utf-8','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.xls':'application/vnd.ms-excel'};
const assets = Object.create(null);
async function collect(dir) {
  for (const entry of (await readdir(dir, {withFileTypes:true})).sort((a,b)=>a.name.localeCompare(b.name))) {
    const path = resolve(dir, entry.name);
    if (entry.isSymbolicLink()) throw new Error('Asset symlinks are not supported');
    if (entry.isDirectory()) await collect(path);
    else if (entry.isFile()) {
      const route = '/' + relative(client, path).split(sep).join('/');
      if (route.endsWith('.map') || route.includes('/.')) throw new Error('Unexpected private asset in client build');
      assets[route] = {type: types[extname(path)] ?? 'application/octet-stream', base64: (await readFile(path)).toString('base64')};
    }
  }
}
await collect(client);
if (!assets['/index.html']) throw new Error('Missing client entry');
const config = JSON.parse(await readFile(resolve(root, '.openai/hosting.json'), 'utf8'));
if (config.static) throw new Error('Static hosting bypasses authentication');
const auth = await readFile(resolve(root, 'worker/auth.mjs'), 'utf8');
await rm(dist, {recursive:true, force:true});
await mkdir(resolve(dist, 'server'), {recursive:true});
await mkdir(resolve(dist, '.openai'), {recursive:true});
await writeFile(resolve(dist, 'server/index.js'), `${auth}\nconst assets = ${JSON.stringify(assets)};\nexport default createPasswordGate(assets);\n`);
await writeFile(resolve(dist, '.openai/hosting.json'), JSON.stringify(config, null, 2) + '\n');
console.log(`Authenticated Worker built with ${Object.keys(assets).length} protected assets`);
