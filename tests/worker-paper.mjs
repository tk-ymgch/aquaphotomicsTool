// Transaction regression for paper-profile inputs. Numerical replication is
// tested separately against synthetic fixtures and private original outputs.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {stripTypeScriptTypes} from 'node:module';
import {setImmediate as nextTurn} from 'node:timers/promises';

const source = stripTypeScriptTypes(fs.readFileSync(new URL('../src/worker.ts',import.meta.url),'utf8'))
  + '\nglobalThis.installRuntimeForTest = value => { runtimePromise = Promise.resolve(value); };';
const globals = new Map(), messages = [], state = {dataset:'prior',calibration:'prior',unity:'prior'};
const context = {URL,Uint8Array,location:{href:'https://test.invalid/assets/worker.js',origin:'https://test.invalid'},postMessage:message=>messages.push(message)};
const runtime = {globals, async loadPackage(){}, async runPythonAsync(code) {
  if (code.includes('paper_demo_dataset()')) {
    assert.equal(globals.get('_use_paper_demo'),true);
    assert(code.indexOf('_json.dumps(')<code.indexOf('_dataset = _next_dataset'));
    state.dataset='paper-demo'; state.calibration=null; state.unity=null;
    return JSON.stringify({name:'artificial-paper-demo'});
  }
  if (code.includes('inspect_paper_reference_bytes(')) {
    const filename = globals.get('_paper_reference_name');
    assert(!code.includes(filename),'reference filenames must remain data');
    assert(globals.get('_paper_reference_data') instanceof Uint8Array);
    assert(!/\b_dataset\s*=/.test(code),'reference loading must not replace active spectra');
    if (filename.startsWith('bad')) throw new Error('ValueError: invalid reference');
    return JSON.stringify({values:[1,...Array(11).fill(0)],source:{name:filename,sha256:'a'.repeat(64)},participantCount:7});
  }
  if (code.includes('analyze(_dataset')) {
    const config=JSON.parse(globals.get('_config_json'));
    assert.equal(config.analysisProfile,'paper-v1');
    return JSON.stringify({metadata:{settings:config},exports:{}});
  }
  throw new Error('Unexpected operation');
}};
vm.runInNewContext(source,context); context.installRuntimeForTest(runtime);
let sequence=0;
async function send(kind,payload={}) {
  const id=++sequence;
  context.onmessage({data:{kind,id,pythonUrl:'https://test.invalid/python/workbench.py',...payload}});
  for(let n=0;n<200;n++) {await nextTurn();const done=messages.find(message=>message.id===id&&message.kind!=='progress');if(done)return done;}
  throw new Error('Request did not settle');
}
const original={...state}, filename='reference-"\n.csv';
const loaded=await send('loadPaperReference',{filename,data:new ArrayBuffer(3)});
assert.equal(loaded.kind,'success'); assert.equal(loaded.result.source.name,filename);
assert.deepEqual(state,original); assert.equal(globals.size,0);
assert.equal((await send('loadPaperReference',{filename:'bad.csv',data:new ArrayBuffer(2)})).kind,'error');
assert.deepEqual(state,original); assert.equal(globals.size,0);
const config={analysisProfile:'paper-v1',paper:{timeColumn:'time_seconds',loading:loaded.result}};
assert.equal((await send('analyze',{config})).kind,'success');assert.equal(globals.size,0);
assert.equal((await send('paperDemo')).kind,'success');assert.equal(globals.size,0);
assert.deepEqual(state,{dataset:'paper-demo',calibration:null,unity:null});
console.log('PASS: paper reference routing, filename isolation, failed-input cleanup, active-data preservation, profile forwarding and synthetic-demo lifecycle');
