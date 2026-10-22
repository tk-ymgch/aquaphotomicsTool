// Run after pnpm build:pages. Uses generated test credentials, never live secrets.
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { webcrypto } from 'node:crypto';

if (!globalThis.crypto?.subtle) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
}
const root = fileURLToPath(new URL('..', import.meta.url));
const pages = resolve(root, 'pages-dist');
const client = resolve(root, '.client-build');
const origin = 'https://pages-artifact-test.invalid';
const encoder = new TextEncoder();
const hex = value => Buffer.from(value).toString('hex');
async function filesIn(folder) {
  const files = [];
  for (const entry of await readdir(folder, { withFileTypes: true })) {
    assert.equal(entry.isSymbolicLink(), false, 'distribution must not contain symlinks');
    const path = resolve(folder, entry.name);
    if (entry.isDirectory()) files.push(...await filesIn(path));
    else if (entry.isFile()) files.push(path);
  }
  return files;
}
assert.deepEqual((await filesIn(pages)).map(path => relative(pages, path).split(sep).join('/')).sort(),
  ['_routes.json', '_worker.js'], 'no separately served client assets may bypass authentication');
assert.deepEqual(JSON.parse(await readFile(resolve(pages, '_routes.json'), 'utf8')),
  { version: 1, include: ['/*'], exclude: [] }, 'every route must invoke the Worker');
assert.deepEqual(await readFile(resolve(pages, '_worker.js')),
  await readFile(resolve(root, 'dist/server/index.js')), 'Pages and Sites must use the identical Worker');
const worker = (await import(pathToFileURL(resolve(pages, '_worker.js')).href)).default;
assert.equal(typeof worker?.fetch, 'function');

const password = 'generated-pages-test-only.' + hex(crypto.getRandomValues(new Uint8Array(16)));
const salt = crypto.getRandomValues(new Uint8Array(16));
const key = await crypto.subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, ['deriveBits']);
const digest = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations: 100000 }, key, 256);
const env = {
  SITE_PASSWORD_HASH: `pbkdf2:100000:${hex(salt)}:${hex(digest)}`,
  SESSION_SIGNING_KEY: hex(crypto.getRandomValues(new Uint8Array(32))),
  // A future accidental static fallback must fail this test.
  ASSETS: { fetch() { throw new Error('Static assets must not bypass the password gate'); } },
};
const get = (route, environment = env, cookie, method = 'GET') => worker.fetch(new Request(origin + route, {
  method, headers: cookie ? { Cookie: cookie } : {},
}), environment);
const post = (route, passwordValue) => worker.fetch(new Request(origin + route, {
  method: 'POST',
  headers: { Origin: origin, 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ password: passwordValue }).toString(),
}), env);
const noStore = response => assert.match(response.headers.get('Cache-Control') ?? '', /no-store/i);
const clientFiles = await filesIn(client);
const routeFor = path => '/' + relative(client, path).split(sep).join('/');
assert.ok(clientFiles.some(path => routeFor(path) === '/index.html'));
assert.ok(clientFiles.some(path => routeFor(path) === '/python/workbench.py'));
assert.ok(clientFiles.some(path => routeFor(path) === '/python/experiment.py'));
assert.ok(clientFiles.some(path => routeFor(path) === '/python/aquap2py.zip'));
assert.ok(clientFiles.some(path => routeFor(path).startsWith('/wheels/')));

for (const path of clientFiles) {
  const route = routeFor(path);
  const response = await get(route);
  noStore(response);
  assert.equal(response.status, route === '/index.html' ? 200 : 401, `unauthenticated ${route}`);
  if (route === '/index.html') {
    assert.match(await response.text(), /<form\b/i);
    assert.equal((await get(route, env, undefined, 'HEAD')).status, 200);
  }
  for (const incomplete of [{}, { SITE_PASSWORD_HASH: env.SITE_PASSWORD_HASH }, { SESSION_SIGNING_KEY: env.SESSION_SIGNING_KEY }]) {
    const missing = await get(route, incomplete);
    assert.equal(missing.status, 503, `missing secrets must fail closed: ${route}`);
    noStore(missing);
  }
}
for (const route of ['/_worker.js', '/_routes.json', '/.openai/hosting.json', '/missing']) {
  assert.equal((await get(route)).status, 401, `unauthenticated reserved route ${route}`);
}
assert.match(await (await get('/')).text(), /<form\b/i);
assert.equal((await post('/auth/login', 'incorrect-test-password')).status, 401);
const login = await post('/auth/login', password);
assert.equal(login.status, 303);
noStore(login);
assert.equal(login.headers.get('Location'), '/');
const setCookie = login.headers.get('Set-Cookie');
assert.match(setCookie ?? '', /; Path=\/; HttpOnly; Secure; SameSite=Strict; Max-Age=28800$/);
const cookie = setCookie.split(';', 1)[0];
for (const path of clientFiles) {
  const route = routeFor(path);
  const response = await get(route, env, cookie);
  assert.equal(response.status, 200, `authenticated ${route}`);
  noStore(response);
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), await readFile(path), `unchanged client bytes ${route}`);
  const head = await get(route, env, cookie, 'HEAD');
  assert.equal(head.status, 200);
  assert.equal((await head.arrayBuffer()).byteLength, 0);
}
assert.deepEqual(Buffer.from(await (await get('/', env, cookie)).arrayBuffer()), await readFile(resolve(client, 'index.html')));
for (const route of ['/_worker.js', '/_routes.json', '/missing']) {
  assert.equal((await get(route, env, cookie)).status, 404, `reserved files must not be downloadable: ${route}`);
}
const logout = await post('/auth/logout', '');
assert.equal(logout.status, 303);
assert.match(logout.headers.get('Set-Cookie') ?? '', /^__Host-aqua_session=;.*Max-Age=0$/);
assert.equal((await get('/python/workbench.py', env, '__Host-aqua_session=')).status, 401,
  'browser cookie cleared by logout must lose access');
assert.equal((await get('/python/workbench.py', env, cookie + 'modified')).status, 401, 'tampered session must be rejected');
console.log(`PASS: Pages 2-file advanced-mode artifact, unchanged Sites Worker, ${clientFiles.length} protected assets byte-matched, wrong/correct password, logout, HEAD and fail-closed secrets`);
