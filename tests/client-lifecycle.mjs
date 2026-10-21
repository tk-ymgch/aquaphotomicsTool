// Run with Node >=22.18: node tests/client-lifecycle.mjs
// The actual worker/Python path is verified in the browser; these tests exercise
// cancellation, errors and races that are difficult to trigger reliably in UI tests.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { stripTypeScriptTypes } from 'node:module';

const clientPath = new URL('../src/client.ts', import.meta.url);
let source = stripTypeScriptTypes(fs.readFileSync(clientPath, 'utf8'));
source = source
  .replace('export class AnalysisClient', 'class AnalysisClient')
  .replaceAll('import.meta.env.BASE_URL', "'./'")
  .replaceAll('import.meta.url', "'https://test.invalid/workbench/src/client.ts'")
  + '\nglobalThis.AnalysisClient = AnalysisClient;';

const timers = [];
class FakeWorker {
  static instances = [];
  sent = [];
  terminated = false;

  constructor(url, options) {
    this.url = url;
    this.options = options;
    FakeWorker.instances.push(this);
  }
  postMessage(value, transfer) { this.sent.push({ value, transfer }); }
  terminate() { this.terminated = true; }
  reply(value) { this.onmessage({ data: value }); }
}

const context = {
  Worker: FakeWorker,
  URL,
  window: { location: { href: 'https://test.invalid/workbench/' } },
  structuredClone,
  setTimeout(fn) {
    const timer = { fn, cleared: false };
    timers.push(timer);
    return timer;
  },
  clearTimeout(timer) { timer.cleared = true; },
};
vm.runInNewContext(source, context);
const Client = context.AnalysisClient;
const flush = () => Promise.resolve().then(() => Promise.resolve());

const client = new Client(() => { throw new Error('UI callback failure'); });
const worker = FakeWorker.instances.at(-1);
assert.equal(worker.options.type, 'module');
const first = client.demo();
await assert.rejects(client.demo(), /別の処理/);
await flush();
const firstRequest = worker.sent[0].value;
assert.equal(firstRequest.pythonUrl, 'https://test.invalid/workbench/python/workbench.py');
worker.reply({ id: firstRequest.id + 100, kind: 'error', message: 'unrelated response' });
worker.reply({ id: firstRequest.id, kind: 'progress', progress: { phase: 'demo', message: 'demo' } });
worker.reply({ id: firstRequest.id, kind: 'success', result: { name: 'demo' } });
assert.equal((await first).name, 'demo');
assert.equal(timers[0].cleared, true);

const config = { range: [1300, 1600] };
const analysis = client.analyze(config);
config.range[0] = 999;
await flush();
const analysisRequest = worker.sent.at(-1).value;
assert.equal(analysisRequest.config.range[0], 1300);
worker.reply({ id: analysisRequest.id, kind: 'error', message: '解析テスト' });
await assert.rejects(analysis, /解析テスト/);

await assert.rejects(client.load({ name: 'input.txt', size: 5 }), /CSV/);
await assert.rejects(client.load({ name: 'empty.csv', size: 0 }), /空/);
await assert.rejects(client.load({ name: 'large.csv', size: 51 * 1024 * 1024 }), /50 MB/);
await assert.rejects(client.load({ name: 'missing.csv', size: 5, arrayBuffer: async () => { throw new Error('unavailable'); } }), /利用可能/);

const bytes = new Uint8Array([1, 2, 3]).buffer;
const loading = client.load({ name: 'input.csv', size: 3, arrayBuffer: async () => bytes });
await flush();
assert.equal(worker.sent.at(-1).transfer[0], bytes);
client.dispose();
client.dispose();
await assert.rejects(loading, /中止/);
assert.equal(worker.terminated, true);
await assert.rejects(client.demo(), /終了/);

// Disposing while the file is still being read must not enqueue a late request.
const slowClient = new Client();
let resolveBytes;
const slow = slowClient.load({
  name: 'slow.csv', size: 3,
  arrayBuffer: () => new Promise(resolve => { resolveBytes = resolve; }),
});
slowClient.dispose();
await assert.rejects(slow, /中止/);
resolveBytes(bytes);
await flush();
assert.equal(FakeWorker.instances.at(-1).sent.length, 0);

const timedClient = new Client();
const timed = timedClient.demo();
timers.at(-1).fn();
await assert.rejects(timed, /5分/);
assert.equal(FakeWorker.instances.at(-1).terminated, true);

const crashedClient = new Client();
const crashed = crashedClient.demo();
FakeWorker.instances.at(-1).onerror({ preventDefault() {} });
await assert.rejects(crashed, /解析環境/);

const brokenMessageClient = new Client();
const brokenMessage = brokenMessageClient.demo();
FakeWorker.instances.at(-1).onmessageerror();
await assert.rejects(brokenMessage, /データ通信/);

const postFailureClient = new Client();
FakeWorker.instances.at(-1).postMessage = () => { throw new Error('postMessage failed'); };
await assert.rejects(postFailureClient.demo(), /送れません/);
postFailureClient.dispose();

console.log('PASS: client lifecycle, concurrency, snapshots, validation, transfer, cancellation, timeout, worker errors');
