// Run with Node >=22.18: node tests/worker-xlsx.mjs
// Tests wheel URL construction and retry/lifecycle behavior without a network.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { stripTypeScriptTypes } from 'node:module';

const source = stripTypeScriptTypes(fs.readFileSync(new URL('../src/worker.ts', import.meta.url), 'utf8'))
  + '\nglobalThis.ensureXlsxForTest = ensureXlsx;';
const messages = [];
const context = {
  URL,
  location: { href: 'https://test.invalid/tools/assets/worker.js', origin: 'https://test.invalid' },
  postMessage: message => messages.push(message),
};
vm.runInNewContext(source, context);

const globals = new Map();
const packages = [];
let installs = 0;
const runtime = {
  globals,
  async loadPackage(names) { packages.push(...names); },
  async runPythonAsync(code) {
    installs++;
    assert.match(code, /_json\.loads\(_excel_wheels_json\)/);
    assert.match(code, /deps=False/);
    const urls = JSON.parse(globals.get('_excel_wheels_json'));
    assert.deepEqual(urls, [
      'https://test.invalid/tools/wheels/et_xmlfile-2.0.0-py3-none-any.whl',
      'https://test.invalid/tools/wheels/openpyxl-3.1.5-py2.py3-none-any.whl',
    ]);
    if (installs === 1) throw new Error('temporary download failure');
  },
};

await assert.rejects(context.ensureXlsxForTest(runtime, 'https://test.invalid/tools/python/workbench.py', 1), /Excel/);
assert.equal(globals.has('_excel_wheels_json'), false);
await context.ensureXlsxForTest(runtime, 'https://test.invalid/tools/python/workbench.py', 2);
await context.ensureXlsxForTest(runtime, 'https://test.invalid/tools/python/workbench.py', 3);
assert.deepEqual(packages, ['micropip']);
assert.equal(installs, 2);
assert.equal(globals.has('_excel_wheels_json'), false);
assert(messages.some(message => message.kind === 'progress' && message.progress.phase === 'excel'));
console.log('PASS: XLSX pinned same-origin wheels, deps=False, retry after failure, cleanup, success caching');
