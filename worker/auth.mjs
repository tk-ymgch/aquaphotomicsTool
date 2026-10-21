// Shared-password gate. Runtime secrets are configured in Sites, never bundled.
const encoder = new TextEncoder();
const COOKIE = '__Host-aqua_session';
const SESSION_SECONDS = 8 * 60 * 60;
const failures = new Map(); // Best-effort per-isolate limit, not a durable global quota.
const hexBytes = (value) => Uint8Array.from(value.match(/../g), (s) => parseInt(s, 16));
const base64url = (bytes) => btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
const unbase64url = (value) => Uint8Array.from(atob(value.replaceAll('-', '+').replaceAll('_', '/')), (c) => c.charCodeAt(0));

function configured(env) {
  return /^pbkdf2:100000:[a-f0-9]{32}:[a-f0-9]{64}$/.test(env.SITE_PASSWORD_HASH ?? '') && /^[a-f0-9]{64}$/.test(env.SESSION_SIGNING_KEY ?? '');
}

async function signingKey(env) {
  return crypto.subtle.importKey('raw', encoder.encode(`${env.SESSION_SIGNING_KEY}:${env.SITE_PASSWORD_HASH}`), {name: 'HMAC', hash: 'SHA-256'}, false, ['sign', 'verify']);
}

async function validSession(request, env) {
  const value = (request.headers.get('cookie') ?? '').split(';').map((s) => s.trim()).find((s) => s.startsWith(`${COOKIE}=`))?.slice(COOKIE.length + 1);
  if (!value || value.length > 1024) return false;
  try {
    const [payload, signature, extra] = value.split('.');
    if (!payload || !signature || extra !== undefined) return false;
    if (!await crypto.subtle.verify('HMAC', await signingKey(env), unbase64url(signature), encoder.encode(payload))) return false;
    const data = JSON.parse(new TextDecoder().decode(unbase64url(payload)));
    const now = Math.floor(Date.now() / 1000);
    return data.v === 1 && Number.isInteger(data.exp) && data.exp > now && data.exp <= now + SESSION_SECONDS && typeof data.nonce === 'string';
  } catch { return false; }
}

async function sessionCookie(env) {
  const data = {v: 1, exp: Math.floor(Date.now() / 1000) + SESSION_SECONDS, nonce: base64url(crypto.getRandomValues(new Uint8Array(16)))};
  const payload = base64url(encoder.encode(JSON.stringify(data)));
  const signature = base64url(new Uint8Array(await crypto.subtle.sign('HMAC', await signingKey(env), encoder.encode(payload))));
  return `${COOKIE}=${payload}.${signature}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${SESSION_SECONDS}`;
}

function headers(type = 'text/html; charset=utf-8') {
  return {
    'Content-Type': type, 'Cache-Control': 'private, no-store',
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin',
    'X-Robots-Tag': 'noindex, nofollow, noarchive', 'X-Frame-Options': 'DENY',
    'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-eval' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' https://cdn.jsdelivr.net http://127.0.0.1:8787 http://localhost:8787; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
  };
}

function loginPage(error = '') {
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>アクセス認証 | Aquaphotomics Workbench</title><style>
  *{box-sizing:border-box}body{margin:0;min-height:100svh;background:#eef0f1;color:#202428;font-family:Inter,"Noto Sans JP","Yu Gothic",sans-serif;display:grid;place-items:center;padding:28px}body:before{content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(ellipse at 78% 15%,#fff 0,transparent 60%),radial-gradient(ellipse at 10% 90%,#dce1e4,transparent 55%)}main{position:relative;width:min(100%,490px);padding:46px 42px;background:#ffffffb8;border:1px solid #fff;border-radius:26px;box-shadow:0 24px 90px #202c3910;backdrop-filter:blur(24px)}.mark{width:45px;height:45px;border:1px solid #a3abb0;border-radius:50%;box-shadow:inset 0 0 0 8px #ffffffa0;margin-bottom:28px}.eyebrow{font-size:10px;font-weight:700;letter-spacing:.19em;color:#697278;margin:0 0 13px}h1{font-size:24px;line-height:1.65;font-weight:600;letter-spacing:-.04em;margin:0 0 14px}.intro{font-size:13px;line-height:1.9;color:#697278;margin:0 0 30px}label{display:block;font-size:12px;font-weight:600;margin-bottom:9px}input{width:100%;height:49px;border:1px solid #cbd0d3;border-radius:10px;background:#ffffffb8;padding:0 14px;font-size:17px;color:#202428;outline:none}input:focus{border-color:#414a51;box-shadow:0 0 0 3px #414a5112}button{margin-top:15px;width:100%;height:48px;border:0;border-radius:10px;background:#252b30;color:white;font:600 13px inherit;cursor:pointer}button:hover{background:#41494f}.error{font-size:12px;line-height:1.8;color:#943c3c;margin:13px 0 0}.foot{font-size:10px;line-height:1.9;color:#80888d;margin:29px 0 0;letter-spacing:.02em}@media(max-width:500px){main{padding:34px 26px}h1{font-size:21px}}</style></head><body><main><div class="mark" aria-hidden="true"></div><p class="eyebrow">AQUAPHOTOMICS WORKBENCH</p><h1>アクアフォトミクス解析<br>ワークベンチ</h1><p class="intro">このアプリの利用にはパスワードが必要です。<br>共有されたパスワードを入力してください。</p><form method="post" action="/auth/login"><label for="password">パスワード</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="512" autofocus><button type="submit">ワークベンチを開く</button>${error ? `<p class="error" role="alert">${error}</p>` : ''}</form><p class="foot">CSV / EXCEL · PREPROCESSING · PCA · AQUAGRAM<br>認証は8時間有効です。共有端末では利用後にログアウトしてください。</p></main></body></html>`;
}

function response(body, status = 200, extra = {}, type) {
  return new Response(body, {status, headers: {...headers(type), ...extra}});
}

async function readLimitedBody(request) {
  if (Number(request.headers.get('content-length') ?? 0) > 2048) return null;
  if (!request.body) return '';
  const reader = request.body.getReader();
  const chunks = []; let length = 0;
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      length += value.length;
      if (length > 2048) { await reader.cancel(); return null; }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder().decode(bytes);
}

async function passwordMatches(password, env) {
  if (!password || password.length > 512) return false;
  const [, iterations, salt, expected] = env.SITE_PASSWORD_HASH.split(':');
  const key = await crypto.subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, ['deriveBits']);
  const actual = new Uint8Array(await crypto.subtle.deriveBits({name: 'PBKDF2', hash: 'SHA-256', salt: hexBytes(salt), iterations: Number(iterations)}, key, 256));
  const wanted = hexBytes(expected); let mismatch = actual.length ^ wanted.length;
  for (let i = 0; i < actual.length; i++) mismatch |= actual[i] ^ wanted[i];
  return mismatch === 0;
}

export function createPasswordGate(assets) {
  return {async fetch(request, env) {
    try {
      if (!configured(env)) return response('アクセス認証を準備中です。', 503);
      const url = new URL(request.url);
      const method = request.method;
      if (url.pathname === '/auth/login' || url.pathname === '/auth/logout') {
        if (method !== 'POST') return response('Method not allowed', 405, {Allow: 'POST'});
        if (request.headers.get('origin') !== url.origin) return response('Forbidden', 403);
        if (url.pathname === '/auth/logout') return response(null, 303, {Location: '/', 'Set-Cookie': `${COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`});
        if ((request.headers.get('content-type') ?? '').split(';', 1)[0].trim().toLowerCase() !== 'application/x-www-form-urlencoded') return response('Unsupported media type', 415);
        const body = await readLimitedBody(request);
        if (body === null) return response('Request too large', 413);
        const now = Date.now();
        for (const [key, item] of failures) if (now - item.start >= 10 * 60 * 1000) failures.delete(key);
        const ip = request.headers.get('cf-connecting-ip') ?? 'unknown';
        const item = failures.get(ip);
        if (item?.count >= 15) return response(loginPage('試行回数が上限に達しました。10分後にお試しください。'), 429, {'Retry-After': '600'});
        const password = new URLSearchParams(body).get('password') ?? '';
        if (!await passwordMatches(password, env)) {
          if (!item && failures.size >= 1000) failures.delete(failures.keys().next().value);
          failures.set(ip, {start: item?.start ?? now, count: (item?.count ?? 0) + 1});
          return response(loginPage('パスワードを確認してください。'), 401);
        }
        failures.delete(ip);
        return response(null, 303, {Location: '/', 'Set-Cookie': await sessionCookie(env)});
      }
      if (!['GET', 'HEAD'].includes(method)) return response('Method not allowed', 405, {Allow: 'GET, HEAD'});
      if (!await validSession(request, env)) {
        if (url.pathname !== '/' && url.pathname !== '/index.html') return response(method === 'HEAD' ? null : 'Authentication required', 401);
        return response(method === 'HEAD' ? null : loginPage());
      }
      const path = url.pathname === '/' ? '/index.html' : url.pathname;
      const asset = Object.hasOwn(assets, path) ? assets[path] : undefined;
      if (!asset) return response(method === 'HEAD' ? null : 'Not found', 404);
      const bytes = method === 'HEAD' ? null : Uint8Array.from(atob(asset.base64), (c) => c.charCodeAt(0));
      return response(bytes, 200, {}, asset.type);
    } catch {
      // Do not log request bodies, cookies, passwords or runtime secrets.
      return response('認証処理を完了できませんでした。時間をおいて再度お試しください。', 503);
    }
  }};
}
