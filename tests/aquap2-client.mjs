// Boundary and provenance checks; actual installed-R numerical tests are separate.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
const source = stripTypeScriptTypes(await readFile(new URL('../src/aquap2Client.ts', import.meta.url), 'utf8'));
const { Aquap2Client, validateEndpoint, validateROutput, mergeAquap2Result } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const ids=['a','b','c'], groups=['Control','Control','Treatment'], waves=[1340,1450,1550];
const baseline={metadata:{samples:3,variables:3,warnings:[],settings:{pcaScale:false,aquagramReference:'global'}},spectra:{ids,groups,wavelengths:waves,processed:[[1,2,3],[2,3,4],[3,4,6]]},pca:{ids,groups,scores:[[1],[2],[3]],loadings:[[.1],[.2],[.3]],explainedVariance:[.8]},aquagram:{wavelengths:waves,labels:waves.map(String),groups:[{name:'Control',n:2,values:[-1,-2,-3]},{name:'Treatment',n:1,values:[2,4,6]}],reference:'全体平均',definition:'Python'},exports:{'settings.json':JSON.stringify({_provenance:{aquap2_not_executed:true,implementation:'Python'}}),'data/aquagram.csv':'python baseline\n','README.txt':'実装はNumPy・SciPy・scikit-learnによるPython処理です。aquap2は実行していません。'}};
const factor=Math.sqrt(2/3);
const output={pca:structuredClone(baseline.pca),aquagram:{...structuredClone(baseline.aquagram),definition:'classic; sample SD',ddof:1,mode:'classic',groups:baseline.aquagram.groups.map(g=>({...g,values:g.values.map(x=>x*factor)}))},runtime:{engine:'aquap2',aquap2Version:'0.4.5',rVersion:'R test',api:'aquap2::gdmm',packageApiExecuted:true,installedPackage:true},warnings:['identity SG3; rounding difference recorded']};
let passed=0;
function check(name,test){try{test();passed++;}catch(e){console.error(name);throw e;}}
check('only fixed local endpoints',()=>{assert.equal(validateEndpoint('http://localhost:8787/'),'http://localhost:8787');for(const url of ['https://remote.example','http://127.0.0.1:9000','http://localhost:8787/path','http://localhost:8787@evil.example'])assert.throws(()=>validateEndpoint(url));});
check('source harness and malformed/reordered results are rejected',()=>{for(const mutate of [x=>x.runtime.packageApiExecuted=false,x=>x.runtime.api='source harness',x=>x.pca.ids.reverse(),x=>x.pca.scores[0][0]=NaN,x=>x.pca.explainedVariance=[1.2],x=>x.aquagram.groups[0].n=1,x=>x.aquagram.wavelengths.reverse()]){const bad=structuredClone(output);mutate(bad);assert.throws(()=>validateROutput(bad,baseline));}});
check('actual-stage provenance replaces stale Python claims and keeps independent baseline',()=>{const merged=mergeAquap2Result(baseline,output);assert.equal(merged.metadata.execution.packageApiExecuted,true);assert.equal(merged.metadata.execution.preprocessingEngine,'python');assert.ok(merged.metadata.warnings.includes(output.warnings[0]));const settings=JSON.parse(merged.exports['settings.json']);assert.equal(settings._provenance.aquap2_not_executed,false);assert.match(settings._provenance.implementation,/installed aquap2/);assert.ok(!merged.exports['README.txt'].includes('aquap2は実行していません'));assert.equal(merged.exports['data/python_reference_aquagram.csv'],'python baseline\n');assert.equal(JSON.parse(merged.exports['aquap2_comparison.json']).maximumAbsoluteDifferenceAfterSdConversion,0);assert.equal(baseline.metadata.execution,undefined);assert.equal(baseline.exports['data/aquagram.csv'],'python baseline\n');});
await (async()=>{
  const original=globalThis.fetch;const calls=[];let pending=false;
  globalThis.fetch=async(url,options)=>{calls.push({url,options});if(pending)return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))));const value=url.endsWith('/health')?{schemaVersion:1,available:true,engine:'aquap2',api:'aquap2::gdmm',aquap2Version:'0.4.5',rVersion:'R test',capabilities:{pca:true,classic:true}}:url.endsWith('/session')?{token:'private-'.repeat(8),expiresIn:1800}:output;return {ok:true,json:async()=>value};};
  try{
    const client=new Aquap2Client();await assert.rejects(client.analyze(baseline),/接続テスト/);
    await client.connect();const merged=await client.analyze(baseline);
    assert.equal(calls.at(-1).options.headers.Authorization,'Bearer '+'private-'.repeat(8));
    assert.equal(calls.at(-1).options.credentials,'omit');
    assert.ok(!JSON.stringify(merged).includes('private-private'));
    assert.ok(!JSON.stringify(merged).includes('127.0.0.1'));
    for(const change of [{pcaScale:true},{aquagramReference:'none'},{pls:{enabled:true}}])await assert.rejects(client.analyze({...baseline,metadata:{...baseline.metadata,settings:{...baseline.metadata.settings,...change}}}));
    pending=true;const active=client.analyze(baseline);client.disconnect();await assert.rejects(active,/中止/);await assert.rejects(client.analyze(baseline),/接続テスト/);passed+=4;
  }finally{globalThis.fetch=original;}
})();
console.log(`PASS: ${passed} aquap2 client boundary/provenance/connection checks`);
