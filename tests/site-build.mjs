// Run after pnpm build, with Node >=22.18: node tests/site-build.mjs
// Checks the deployed artifact, including every client asset behind the gate.
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { resolve, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { webcrypto } from 'node:crypto';

if (!globalThis.crypto?.subtle) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
}
const root = fileURLToPath(new URL('..', import.meta.url));
const dist = resolve(root, 'dist');
const client = resolve(root, '.client-build');
const encoder = new TextEncoder();
const origin = 'https://deployed-artifact-test.invalid';
const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
async function filesIn(folder) {
  const files = [];
  for (const entry of await readdir(folder, { withFileTypes: true })) {
    assert.equal(entry.isSymbolicLink(), false, 'build artifact must not include symlinks');
    const path = resolve(folder, entry.name);
    if (entry.isDirectory()) files.push(...await filesIn(path));
    else if (entry.isFile()) files.push(path);
  }
  return files;
}
const routeFor = path => '/' + relative(client, path).split(sep).join('/');
const distributionFiles = (await filesIn(dist)).map(path => relative(dist, path).split(sep).join('/')).sort();
assert.deepEqual(distributionFiles, ['.openai/hosting.json', 'server/index.js'],
  'dist must contain only the Worker and its hosting configuration, without a static bypass');
const hosting = JSON.parse(await readFile(resolve(dist, '.openai/hosting.json'), 'utf8'));
assert.equal(Object.hasOwn(hosting, 'static'), false, 'hosting must not publish a static asset directory');

const built = await import(pathToFileURL(resolve(dist, 'server/index.js')).href);
assert.equal(typeof built.default?.fetch, 'function', 'built Worker must export default.fetch');
const worker = built.default;
const clientFiles = await filesIn(client);
assert.ok(clientFiles.some(path => routeFor(path) === '/index.html'));
assert.ok(clientFiles.some(path => routeFor(path) === '/python/workbench.py'));
assert.ok(clientFiles.some(path => routeFor(path).startsWith('/assets/')));
assert.ok(clientFiles.some(path => routeFor(path).startsWith('/wheels/')));

const password = 'generated-artifact-tests-only.' + hex(crypto.getRandomValues(new Uint8Array(16)));
const salt = crypto.getRandomValues(new Uint8Array(16));
const passwordKey = await crypto.subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, ['deriveBits']);
const digest = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations: 100000 }, passwordKey, 256);
const env = {
  SITE_PASSWORD_HASH: `pbkdf2:100000:${hex(salt)}:${hex(new Uint8Array(digest))}`,
  SESSION_SIGNING_KEY: hex(crypto.getRandomValues(new Uint8Array(32))),
};
function noStore(response) {
  assert.match(response.headers.get('Cache-Control') ?? '', /no-store/i);
}
const get = (path, environment, cookie) => worker.fetch(new Request(origin + path, {
  headers: cookie ? { Cookie: cookie } : {},
}), environment);

let protectedAssets = 0;
for (const path of clientFiles) {
  const route = routeFor(path);
  const response = await get(route, env);
  noStore(response);
  if (route === '/index.html') {
    assert.equal(response.status, 200);
    const body = await response.text();
    assert.match(body, /<form\b/i);
    assert.notEqual(body, await readFile(path, 'utf8'));
  } else {
    assert.equal(response.status, 401, `unauthenticated asset ${route}`);
    protectedAssets++;
  }
  const unconfigured = await get(route, {});
  assert.equal(unconfigured.status, 503, `unconfigured asset ${route}`);
  noStore(unconfigured);
}
const rootResponse = await get('/', env);
assert.equal(rootResponse.status, 200);
assert.match(await rootResponse.text(), /<form\b/i);
assert.equal((await get('/', {})).status, 503);

const loggedIn = await worker.fetch(new Request(origin + '/auth/login', {
  method: 'POST',
  headers: { Origin: origin, 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ password }).toString(),
}), env);
assert.equal(loggedIn.status, 303);
const cookie = loggedIn.headers.get('Set-Cookie')?.split(';', 1)[0];
assert.ok(cookie?.startsWith('__Host-aqua_session='));
for (const path of clientFiles) {
  const route = routeFor(path);
  const response = await get(route, env, cookie);
  assert.equal(response.status, 200, `authenticated asset ${route}`);
  noStore(response);
  assert.ok(Buffer.from(await response.arrayBuffer()).equals(await readFile(path)),
    `bundled bytes must match the client build: ${route}`);
}
const index = await get('/', env, cookie);
assert.equal(index.status, 200);
assert.ok(Buffer.from(await index.arrayBuffer()).equals(await readFile(resolve(client, 'index.html'))));
const missing = await get('/asset-that-does-not-exist', env, cookie);
assert.equal(missing.status, 404);
noStore(missing);

console.log(`PASS: built Worker, 2-file server-only dist, no static bypass, ${protectedAssets} unauthenticated assets rejected, ${clientFiles.length} authenticated assets byte-matched, missing-env 503`);
