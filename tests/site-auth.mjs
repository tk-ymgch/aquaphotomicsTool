// Run with Node >=22.18: node tests/site-auth.mjs
// All passwords, keys and assets below are generated test-only fixtures.
// The production gate must use Web Crypto; node:crypto is used only here to
// provide the same standard API in the standalone Node test environment.
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { createPasswordGate } from '../worker/auth.mjs';

if (!globalThis.crypto?.subtle) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
}
const crypto = globalThis.crypto;
const encoder = new TextEncoder();
const ORIGIN = 'https://aquaphotomics-test.invalid';
const COOKIE_NAME = '__Host-aqua_session';
const text = {
  index: '<!doctype html><html><body><h1>PROTECTED_TEST_RESEARCH_APP</h1></body></html>',
  script: 'globalThis.PROTECTED_TEST_ASSET = true;',
  python: 'PROTECTED_TEST_PYTHON = True\n',
};
const assets = {
  '/index.html': { type: 'text/html; charset=utf-8', base64: btoa(text.index) },
  '/assets/app.js': { type: 'text/javascript; charset=utf-8', base64: btoa(text.script) },
  '/python/workbench.py': { type: 'text/x-python; charset=utf-8', base64: btoa(text.python) },
};
const gate = createPasswordGate(assets);
assert.equal(typeof gate.fetch, 'function');

const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
const randomBytes = size => crypto.getRandomValues(new Uint8Array(size));
const password = `for-generated-auth-tests-only.${hex(randomBytes(16))}`;
const salt = randomBytes(16);
const key = await crypto.subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, ['deriveBits']);
const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations: 100000 }, key, 256);
const env = {
  SITE_PASSWORD_HASH: `pbkdf2:100000:${hex(salt)}:${hex(new Uint8Array(bits))}`,
  SESSION_SIGNING_KEY: hex(randomBytes(32)),
};

function request(path = '/', { method = 'GET', cookie, origin, type, body } = {}) {
  const headers = new Headers();
  if (cookie !== undefined) headers.set('Cookie', cookie);
  if (origin !== undefined) headers.set('Origin', origin);
  if (type !== undefined) headers.set('Content-Type', type);
  return new Request(`${ORIGIN}${path}`, { method, headers, body });
}
const fetchGate = (path, options, environment = env) => gate.fetch(request(path, options), environment);
const login = (value = password, overrides = {}, environment = env) => fetchGate('/auth/login', {
  method: 'POST', origin: ORIGIN, type: 'application/x-www-form-urlencoded',
  body: new URLSearchParams({ password: value }).toString(), ...overrides,
}, environment);

function noStore(response) {
  assert.match(response.headers.get('Cache-Control') ?? '', /(?:^|[,\s])no-store(?:$|[,\s])/i,
    'authentication and protected responses must prevent cached reuse');
}
function checkCookie(response, { cleared = false } = {}) {
  const header = response.headers.get('Set-Cookie');
  assert.ok(header, 'a Set-Cookie header is required');
  assert.match(header, new RegExp(`^${COOKIE_NAME}=`));
  assert.match(header, /;\s*Secure(?:;|$)/i);
  assert.match(header, /;\s*HttpOnly(?:;|$)/i);
  assert.match(header, /;\s*SameSite=Strict(?:;|$)/i);
  assert.match(header, /;\s*Path=\/(?:;|$)/i);
  assert.doesNotMatch(header, /;\s*Domain=/i, '__Host- cookies must not set Domain');
  assert.match(header, cleared ? /;\s*Max-Age=0(?:;|$)/i : /;\s*Max-Age=28800(?:;|$)/i);
  return header.split(';', 1)[0];
}
async function noProtectedBody(response) {
  const body = await response.text();
  assert.ok(!body.includes('PROTECTED_TEST_'), 'unauthenticated responses must not contain protected files');
  assert.ok(!body.includes(password), 'responses must not echo the test password');
  assert.ok(!body.includes(env.SITE_PASSWORD_HASH), 'responses must not expose password hashes');
  assert.ok(!body.includes(env.SESSION_SIGNING_KEY), 'responses must not expose signing keys');
  return body;
}

async function withClock(milliseconds, operation) {
  const NativeDate = globalThis.Date;
  class TestDate extends NativeDate {
    constructor(...args) { super(...(args.length ? args : [milliseconds])); }
    static now() { return milliseconds; }
  }
  globalThis.Date = TestDate;
  try { return await operation(); } finally { globalThis.Date = NativeDate; }
}

let passed = 0;
async function check(name, operation) {
  try {
    await operation();
    passed++;
  } catch (error) {
    console.error(`FAIL: ${name}`);
    throw error;
  }
}

await check('unauthenticated document shows a password form, never the application', async () => {
  const response = await fetchGate('/');
  assert.equal(response.status, 200);
  assert.match(response.headers.get('Content-Type') ?? '', /text\/html/i);
  noStore(response);
  const html = await noProtectedBody(response);
  assert.match(html, /<form\b/i);
  assert.match(html, /name\s*=\s*["']password["']/i);
  assert.match(html, /type\s*=\s*["']password["']/i);
  assert.equal(response.headers.has('Set-Cookie'), false);
});

await check('direct assets and Python source reject unauthenticated requests', async () => {
  for (const path of ['/assets/app.js', '/python/workbench.py']) {
    const response = await fetchGate(path);
    assert.equal(response.status, 401, path);
    noStore(response);
    await noProtectedBody(response);
  }
});

await check('HEAD cannot leak protected content', async () => {
  const document = await fetchGate('/', { method: 'HEAD' });
  assert.equal(document.status, 200);
  noStore(document);
  assert.equal(await document.text(), '');
  const asset = await fetchGate('/assets/app.js', { method: 'HEAD' });
  assert.equal(asset.status, 401);
  noStore(asset);
  assert.equal(await asset.text(), '');
});

await check('correct password establishes the constrained 8-hour session cookie', async () => {
  const response = await login();
  assert.equal(response.status, 303);
  assert.equal(new URL(response.headers.get('Location'), ORIGIN).origin, ORIGIN);
  checkCookie(response);
  noStore(response);
  await noProtectedBody(response);
});

await check('incorrect password returns 401 without issuing a valid session', async () => {
  const response = await login('this-is-a-deliberately-wrong-test-password');
  assert.equal(response.status, 401);
  const cookie = response.headers.get('Set-Cookie');
  assert.ok(cookie === null || /Max-Age=0(?:;|$)/i.test(cookie));
  noStore(response);
  await noProtectedBody(response);
});

await check('login Origin is required and matched exactly', async () => {
  for (const origin of [undefined, 'null', 'https://elsewhere.invalid', `${ORIGIN}.evil.invalid`, `${ORIGIN}/`, ORIGIN.replace('https:', 'http:')]) {
    const response = await login(password, { origin });
    assert.equal(response.status, 403, String(origin));
    noStore(response);
    await noProtectedBody(response);
  }
});

await check('login accepts only URL-encoded form bodies', async () => {
  for (const type of ['application/json', 'text/plain', 'multipart/form-data', 'application/x-www-form-urlencodedX']) {
    const response = await login(password, { type });
    assert.equal(response.status, 415, type);
    noStore(response);
    await noProtectedBody(response);
  }
  const utf8 = await login(password, { type: 'application/x-www-form-urlencoded; charset=UTF-8' });
  assert.equal(utf8.status, 303);
});

await check('oversized form bodies are rejected before authentication', async () => {
  const response = await login(password, { body: `password=${'x'.repeat(1024 * 1024)}` });
  assert.equal(response.status, 413);
  noStore(response);
  await noProtectedBody(response);
});

await check('missing secrets fail closed for page, source and login', async () => {
  for (const environment of [{}, { SITE_PASSWORD_HASH: env.SITE_PASSWORD_HASH }, { SESSION_SIGNING_KEY: env.SESSION_SIGNING_KEY }]) {
    for (const path of ['/', '/python/workbench.py']) {
      const response = await fetchGate(path, {}, environment);
      assert.equal(response.status, 503);
      noStore(response);
      await noProtectedBody(response);
    }
    const response = await login(password, {}, environment);
    assert.equal(response.status, 503);
    await noProtectedBody(response);
  }
});

await check('malformed password hashes and signing keys fail closed', async () => {
  for (const environment of [
    { ...env, SITE_PASSWORD_HASH: 'pbkdf2:100000:not-hex:not-a-hash' },
    { ...env, SITE_PASSWORD_HASH: env.SITE_PASSWORD_HASH.replace('100000', '1') },
    { ...env, SESSION_SIGNING_KEY: 'not-a-signing-key' },
  ]) {
    const response = await login(password, {}, environment);
    assert.equal(response.status, 503);
    noStore(response);
    await noProtectedBody(response);
  }
});

await check('authentication routes reject methods other than POST', async () => {
  for (const path of ['/auth/login', '/auth/logout']) {
    const response = await fetchGate(path, { origin: ORIGIN });
    assert.equal(response.status, 405);
    assert.match(response.headers.get('Allow') ?? '', /POST/);
    assert.equal(response.headers.has('Set-Cookie'), false);
    noStore(response);
  }
});

const activeCookie = checkCookie(await login());

await check('authenticated requests serve the exact bundled assets', async () => {
  for (const [path, expected, type] of [
    ['/', text.index, 'text/html'], ['/index.html', text.index, 'text/html'],
    ['/assets/app.js?v=fixture', text.script, 'text/javascript'],
    ['/python/workbench.py', text.python, 'text/x-python'],
  ]) {
    const response = await fetchGate(path, { cookie: activeCookie });
    assert.equal(response.status, 200, path);
    assert.ok((response.headers.get('Content-Type') ?? '').startsWith(type));
    noStore(response);
    assert.equal(await response.text(), expected);
  }
});

await check('authenticated HEAD keeps headers and omits the asset body', async () => {
  const response = await fetchGate('/assets/app.js', { method: 'HEAD', cookie: activeCookie });
  assert.equal(response.status, 200);
  assert.match(response.headers.get('Content-Type') ?? '', /text\/javascript/i);
  noStore(response);
  assert.equal(await response.text(), '');
});

await check('unknown authenticated assets return a non-cacheable 404', async () => {
  const response = await fetchGate('/missing-fixture.txt', { cookie: activeCookie });
  assert.equal(response.status, 404);
  noStore(response);
  await noProtectedBody(response);
});

await check('tampered, truncated and unsigned cookies cannot access source', async () => {
  const value = activeCookie.slice(COOKIE_NAME.length + 1);
  const changed = (value[0] === 'A' ? 'B' : 'A') + value.slice(1);
  const separator = value.lastIndexOf('.');
  assert.ok(separator > 0, 'the issued token must contain a signed payload');
  const signatureOffset = separator + 1;
  const changedSignature = value.slice(0, signatureOffset)
    + (value[signatureOffset] === 'A' ? 'B' : 'A') + value.slice(signatureOffset + 1);
  for (const token of [changed, changedSignature, value.slice(0, Math.floor(value.length / 2)), 'unsigned-test-session']) {
    const response = await fetchGate('/python/workbench.py', { cookie: `${COOKIE_NAME}=${token}` });
    assert.equal(response.status, 401);
    noStore(response);
    await noProtectedBody(response);
  }
});

await check('sessions are invalid after the signing key is rotated', async () => {
  const response = await fetchGate('/assets/app.js', { cookie: activeCookie }, {
    ...env, SESSION_SIGNING_KEY: hex(randomBytes(32)),
  });
  assert.equal(response.status, 401);
  await noProtectedBody(response);
});

await check('the signature-protected session expires after 8 hours', async () => {
  const start = Date.parse('2026-10-21T00:00:00Z');
  const cookie = await withClock(start, async () => checkCookie(await login()));
  const before = await withClock(start + 8 * 60 * 60 * 1000 - 1000,
    () => fetchGate('/assets/app.js', { cookie }));
  assert.equal(before.status, 200);
  const after = await withClock(start + 8 * 60 * 60 * 1000 + 1000,
    () => fetchGate('/assets/app.js', { cookie }));
  assert.equal(after.status, 401);
  noStore(after);
  await noProtectedBody(after);
});

await check('logout clears the secure host-only cookie', async () => {
  const response = await fetchGate('/auth/logout', { method: 'POST', origin: ORIGIN, cookie: activeCookie });
  assert.ok([200, 204, 303].includes(response.status));
  const cleared = checkCookie(response, { cleared: true });
  assert.equal(cleared, `${COOKIE_NAME}=`);
  noStore(response);
  await noProtectedBody(response);
  const next = await fetchGate('/python/workbench.py', { cookie: cleared });
  assert.equal(next.status, 401);
});

await check('logout rejects cross-origin requests without clearing a session', async () => {
  for (const origin of [undefined, 'null', 'https://elsewhere.invalid']) {
    const response = await fetchGate('/auth/logout', { method: 'POST', origin, cookie: activeCookie });
    assert.equal(response.status, 403);
    assert.equal(response.headers.has('Set-Cookie'), false);
    noStore(response);
  }
});

console.log(`PASS: ${passed} password gate checks (form, assets, Origin, body limits, cookies, HMAC, expiry, logout, HEAD, 404, caching)`);
