// Entry-point/lifecycle regression without CDN or a Python installation.
// The VM exercises actual worker routing and globals cleanup. The fake Python
// runtime checks the generated transaction program, then models its state.
// Real Python IO/numerics are covered by test_native_integration.py/browser QA.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {stripTypeScriptTypes} from 'node:module';
import {setImmediate as nextTurn} from 'node:timers/promises';

const source = stripTypeScriptTypes(fs.readFileSync(new URL('../src/worker.ts',import.meta.url),'utf8'))
  + '\nglobalThis.installRuntimeForTest = value => { runtimePromise = Promise.resolve(value); };';

function harness() {
  const messages=[], globals=new Map(), state={dataset:null,calibration:null}, programs=[];
  const context={URL,Uint8Array,location:{href:'https://test.invalid/tools/assets/worker.js',origin:'https://test.invalid'},postMessage:message=>messages.push(message)};
  const runtime={globals,async loadPackage(){},async runPythonAsync(code){
    programs.push(code);
    if(code.includes('demo_dataset()')) {
      assert.match(code,/_dataset = _next_dataset\s+_calibration_dataset = None/);
      state.dataset={name:'demo'};state.calibration=null;
      return JSON.stringify({name:'demo'});
    }
    if(code.includes('inspect_calibration_bytes if _input_is_calibration else inspect_bytes')) {
      assert.match(code,/if _input_is_calibration:\s+_calibration_dataset = _next_dataset\s+else:\s+_dataset = _next_dataset\s+_calibration_dataset = None/);
      assert.equal((code.match(/\b_calibration_dataset\s*=/g)??[]).length,2);
      assert.equal((code.match(/\b_dataset\s*=/g)??[]).length,1);
      assert(code.indexOf('_json.dumps(_next_summary')<code.indexOf('if _input_is_calibration:'));
      const name=globals.get('_input_name'),calibration=globals.get('_input_is_calibration');
      assert.equal(typeof calibration,'boolean');
      assert(!code.includes(name),'file names must remain data, not executable interpolation');
      if(name.startsWith('bad'))throw new Error('ValueError: synthetic read failure');
      const loaded={name,sheet:JSON.parse(globals.get('_input_sheet_json')),bytes:[...globals.get('_input_data')]};
      if(calibration)state.calibration=loaded;
      else{state.dataset=loaded;state.calibration=null;}
      return JSON.stringify({name,sheet:loaded.sheet,...(calibration?{sourceSha256:'a'.repeat(64),temperatureColumns:[{column:'temperature',observedTemperatures:[20,30]}]}:{})});
    }
    if(code.includes('analyze(_dataset')) {
      assert.match(code,/analyze\(_dataset, _json\.loads\(_config_json\), calibration=_calibration_dataset\)/);
      if(!state.dataset)throw new Error('ValueError: no dataset');
      return JSON.stringify({dataset:state.dataset.name,calibration:state.calibration?.name??null,config:JSON.parse(globals.get('_config_json'))});
    }
    throw new Error('Unexpected generated Python program');
  }};
  vm.runInNewContext(source,context);
  context.installRuntimeForTest(runtime);
  let sequence=0;
  async function send(kind,payload={}) {
    const id=++sequence;
    context.onmessage({data:{id,kind,pythonUrl:'https://test.invalid/tools/python/workbench.py',...payload}});
    for(let i=0;i<100;i++) {
      await nextTurn();
      const response=messages.find(message=>message.id===id&&message.kind!=='progress');
      if(response)return response;
    }
    throw new Error('Worker request did not settle');
  }
  const load=(filename,calibration=false,sheet=null)=>send(calibration?'loadCalibration':'load',{filename,sheet,data:Uint8Array.from([1,2,3]).buffer});
  return {send,load,state,globals,messages,programs};
}

const a=harness();
assert.equal((await a.load('measurement.csv')).kind,'success');
assert.equal(a.state.dataset.name,'measurement.csv');
assert.equal(a.state.calibration,null);
const malicious='calibration-"quote"-\n.csv';
const calibration=await a.load(malicious,true);
assert.equal(calibration.kind,'success'); // exercises onmessage whitelist
assert.deepEqual(Array.from(calibration.result.temperatureColumns[0].observedTemperatures),[20,30]);
assert.equal(a.state.dataset.name,'measurement.csv');
assert.equal(a.state.calibration.name,malicious);
assert.equal(a.globals.size,0);

const stable=structuredClone(a.state);
assert.equal((await a.load('bad-calibration.csv',true)).kind,'error');
assert.deepEqual(a.state,stable,'failed calibration read must not replace either dataset');
assert.equal((await a.load('bad-measurement.csv')).kind,'error');
assert.deepEqual(a.state,stable,'failed measurement read must not clear calibration');
assert.equal(a.globals.size,0,'failed requests must clear transferred input globals');
const analyzed=await a.send('analyze',{config:{analysisEngine:'aquap2py',nativeAquagram:{enabled:true}}});
assert.equal(analyzed.kind,'success');
assert.equal(analyzed.result.calibration,malicious);
assert.equal(a.globals.size,0);
assert.equal((await a.send('demo')).kind,'success');
assert.equal(a.state.dataset.name,'demo');
assert.equal(a.state.calibration,null,'demo replacement clears previous calibration');

// A fresh Worker (as after dispose) can receive calibration before measurement.
// Hydrating measurement clears it, so both must be hydrated in this order.
const b=harness();
await b.load('calibration.csv',true);
assert.equal(b.state.dataset,null);
await b.load('measurement.csv');
assert.equal(b.state.calibration,null);
await b.load('calibration.csv',true);
const recovered=await b.send('analyze',{config:{}});
assert.equal(recovered.result.dataset,'measurement.csv');
assert.equal(recovered.result.calibration,'calibration.csv');
assert.equal((await b.send('unsupported')).kind,'error');
assert.equal(b.globals.size,0);
console.log('PASS: worker entry accepts calibration, separates datasets, preserves failed transactions, clears globals, resets on source replacement and supports ordered rehydration');
