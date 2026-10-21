import {readFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import assert from 'node:assert/strict';
const source = stripTypeScriptTypes(await readFile(new URL('../src/downloads.ts',import.meta.url),'utf8'));
const {comparisonCsv,snapshotBytes} = await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const result = {
  metadata:{samples:3,variables:4,settings:{scatter:'snv',smooth:true,derivative:1}},
  pca:{explainedVariance:[.7,.2]},exports:{'settings.json':'{}'},
  pls:{targetColumn:'濃度',method:'nested-group-kfold',folds:3,seed:11,selectedComponents:2,metrics:{rmseCV:.5,maeCV:.4,r2CV:.8,baselineRmseCV:2}}
};
const runs=[{id:'a',name:'SNV,"微分"\n条件',createdAt:'2026-10-21',result},{id:'b',name:'PLSなし',createdAt:'2026-10-21',result:{...result,pls:undefined}}];
const csv=comparisonCsv(runs);
assert.match(csv,/"SNV,""微分""\n条件"/);
// Parse quoted CSV independently, including quotes and embedded line breaks.
const rows=[];let row=[],cell='',quoted=false;
for(let i=0;i<csv.length;i++) {
  const c=csv[i];
  if(c==='"') {if(quoted&&csv[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
  else if(c===','&&!quoted){row.push(cell);cell='';}
  else if(c==='\n'&&!quoted){row.push(cell);rows.push(row);row=[];cell='';}
  else cell+=c;
}
assert.equal(rows.length,3);
assert.equal(rows[1][0],runs[0].name);
assert(Math.abs(Number(rows[1][rows[0].indexOf('pc1_pc2_variance')])-.9)<1e-14);
assert.equal(rows[1][rows[0].indexOf('pls_rmsecv')],'0.5');
assert.equal(rows[1][rows[0].indexOf('pls_cv_method')],'nested-group-kfold');
assert.equal(rows[2][rows[0].indexOf('pls_rmsecv')],'');
assert(rows.every(row=>row.length===rows[0].length));
const single=comparisonCsv([{...runs[1],result:{...runs[1].result,pca:{explainedVariance:[.8]}}}]);
assert.equal(single.trim().split('\n')[1].split(',')[rows[0].indexOf('pc1_pc2_variance')],'""');
assert(snapshotBytes(result)>3*4*16);
assert.equal(comparisonCsv([]).split('\n').length,2);
console.log('PASS: comparison CSV escaping, applied metrics, PLS absence, headers and retained snapshot size');
