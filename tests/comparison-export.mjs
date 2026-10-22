import {readFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import assert from 'node:assert/strict';
const source = stripTypeScriptTypes(await readFile(new URL('../src/downloads.ts',import.meta.url),'utf8'));
const {comparisonCsv,snapshotBytes} = await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const result = {
  metadata:{samples:3,variables:4,settings:{scatter:'snv',smooth:true,derivative:1}},
  pca:{explainedVariance:[.7,.2]},exports:{'settings.json':'{}'},
  aquagram:{wavelengths:[1340,1400,1450],groups:[],reference:'global',definition:'test classic'},
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
// Read a complete CSV record independently so native metrics/units cannot be
// swapped with nested-CV columns or mislabel AUC as SD-standardized values.
const native={...result,pls:undefined,
  aquagram:{...result.aquagram,mode:'aucs.tn.dce',unit:'degC-equivalent-deviation'},
  metadata:{...result.metadata,execution:{engine:'aquap2py',implementationName:'aquap2py',implementationVersion:'0.2.0',aquagramSdDdof:null,packageApiExecuted:false},
    settings:{...result.metadata.settings,nativeAquagram:{enabled:true,calibrationSource:{sha256:'c'.repeat(64)}}}},
  nativePlsr:{targetColumn:'native target',selectedComponents:4,settings:{validation:'LOO'},metrics:{rmseCV:.75,rmseAdjCV:.72}}};
const nativeLines=comparisonCsv([{id:'native',name:'native',createdAt:'2026-10-22',result:native}]).trim().split('\n');
const nativeHeaders=nativeLines[0].split(',').map(v=>v.slice(1,-1));
const nativeValues=nativeLines[1].split(',').map(v=>v.slice(1,-1));
const value=name=>nativeValues[nativeHeaders.indexOf(name)];
assert.equal(value('native_plsr_target'),'native target');
assert.equal(value('native_plsr_validation'),'LOO');
assert.equal(value('native_plsr_components'),'4');
assert.equal(value('native_plsr_rmsecv'),'0.75');
assert.equal(value('native_plsr_adjusted_rmsecv'),'0.72');
assert.equal(value('pls_rmsecv'),'');
assert.equal(value('aquagram_sd_ddof'),'');
assert.equal(value('aquagram_mode'),'aucs.tn.dce');
assert.equal(value('aquagram_unit'),'degC-equivalent-deviation');
assert.equal(value('calibration_sha256'),'c'.repeat(64));
assert.equal(value('r_package_executed'),'false');
const sfc={...native,aquagram:{...native.aquagram,mode:'sfc',unit:'standardized'},metadata:{...native.metadata,execution:{...native.metadata.execution,aquagramSdDdof:1}}};
const sfcLine=comparisonCsv([{id:'sfc',name:'sfc',createdAt:'2026-10-22',result:sfc}]).trim().split('\n')[1].split(',');
assert.equal(sfcLine[nativeHeaders.indexOf('aquagram_sd_ddof')],'"1"');
console.log('PASS: comparison CSV escaping, nested/native metric separation, AUC units and null SD, SFC sample SD, calibration SHA, headers and retained snapshot size');
