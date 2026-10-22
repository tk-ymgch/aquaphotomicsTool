// Exercise transaction boundaries and cleanup without a CDN or measured inputs.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {stripTypeScriptTypes} from 'node:module';
import {setImmediate as nextTurn} from 'node:timers/promises';

const source = stripTypeScriptTypes(fs.readFileSync(new URL('../src/worker.ts',import.meta.url),'utf8'))
  + '\nglobalThis.installRuntimeForTest = value => { runtimePromise = Promise.resolve(value); };';
const globals=new Map(), messages=[], state={dataset:'previous',unity:'previous-unity'};
const context={URL,Uint8Array,location:{href:'https://test.invalid/assets/worker.js',origin:'https://test.invalid'},postMessage:m=>messages.push(m)};
const runtime={globals,async loadPackage(){},async runPythonAsync(code){
  if(code.includes('merge_phase_files(')) {
    const specs=JSON.parse(globals.get('_experiment_files_json'));
    for(const spec of specs){assert(!code.includes(spec.name),'filenames must never become executable Python');assert(globals.get(spec.key) instanceof Uint8Array);}
    assert(code.indexOf('_json.dumps(dict(summary=')<code.indexOf('_dataset = _next_dataset'),'serialization must succeed before commit');
    assert(code.indexOf('inspect_unity_bytes(')<code.indexOf('_dataset = _next_dataset'),'all files must parse before commit');
    if(specs.some(s=>s.name.startsWith('bad'))) throw new Error('ValueError: invalid synthetic input');
    state.dataset='merged';state.unity=specs.some(s=>s.phase==='Unity')?'new-unity':null;
    return JSON.stringify({summary:{name:'merged'},unity:state.unity?{name:state.unity}:null});
  }
  if(code.includes('inspect_unity_bytes(')) {
    assert(code.indexOf('_json.dumps(')<code.indexOf('_unity_dataset = _next_unity'));
    if(globals.get('_input_name').startsWith('bad'))throw new Error('ValueError: invalid Unity');
    state.unity=globals.get('_input_name');return JSON.stringify({name:state.unity});
  }
  if(code.includes('synchronize_experiment(')) {
    const config=JSON.parse(globals.get('_experiment_config_json'));
    if(!config.unityStartTime) throw new Error('ValueError: explicit clock anchor required');
    return JSON.stringify({rows:[],provenance:{config},exports:{}});
  }
  throw new Error('Unexpected Python operation');
}};
vm.runInNewContext(source,context);context.installRuntimeForTest(runtime);
let sequence=0;
async function send(kind,payload){const id=++sequence;context.onmessage({data:{kind,id,pythonUrl:'https://test.invalid/python/workbench.py',...payload}});
  for(let n=0;n<200;n++){await nextTurn();const m=messages.find(x=>x.id===id&&x.kind!=='progress');if(m)return m;}throw new Error('Request did not settle');}
const file=(filename,phase)=>({filename,phase,data:Uint8Array.from([1,2,3]).buffer});
const malicious='Task-"quote"-\n.csv';
assert.equal((await send('loadExperiment',{files:[file('baseline.csv','Baseline'),file(malicious,'Task'),file('unity.csv','Unity')]})).kind,'success');
assert.deepEqual(state,{dataset:'merged',unity:'new-unity'});assert.equal(globals.size,0);
const stable={...state};
assert.equal((await send('loadExperiment',{files:[file('baseline.csv','Baseline'),file('bad-unity.csv','Unity')]})).kind,'error');
assert.deepEqual(state,stable,'failed batch must preserve previous measurement and Unity');assert.equal(globals.size,0);
assert.equal((await send('loadUnity',{filename:'bad-unity.csv',data:new ArrayBuffer(3)})).kind,'error');
assert.deepEqual(state,stable);assert.equal(globals.size,0);
assert.equal((await send('synchronize',{config:{unityStartTime:null},analysis:null})).kind,'error');assert.equal(globals.size,0);
assert.equal((await send('synchronize',{config:{unityStartTime:'2026-01-01T10:00:00'},analysis:null})).kind,'success');assert.equal(globals.size,0);
assert.equal((await send('loadExperiment',{files:[file('task.csv','Task')]})).kind,'success');assert.equal(state.unity,null,'new batch must clear previous Unity');
console.log('PASS: experiment atomic imports, explicit anchor forwarding, failed-input state preservation, filename isolation and transferred-data cleanup');
