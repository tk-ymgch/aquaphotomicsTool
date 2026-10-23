import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
const source = stripTypeScriptTypes(await readFile(new URL('../src/downloads.ts', import.meta.url), 'utf8'));
const { parseCsv, getResultTables, comparisonCsv } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const csv = '\uFEFFsample_id,group,value\r\n001,"群, A",1.2345678901234567\r\n"試料""二\n行",対照,\r\n';
const rows = parseCsv(csv);
assert.deepEqual(rows, [['sample_id','group','value'],['001','群, A','1.2345678901234567'],['試料"二\n行','対照','']]);
assert.deepEqual(parseCsv('a,b\n1,2'), [['a','b'],['1','2']]);
const result = { exports: { 'data/preprocessed.csv': csv, 'data/pca_scores.csv': 'id,PC1\n001,0.125\n', 'settings.json': '{}' }, metadata:{samples:2,variables:3,settings:{pipelineMode:'legacy-python',missing:'mean',aquagramReference:'none',scatter:'snv',smooth:true,derivative:1}},pca:{explainedVariance:[.8,.2]},aquagram:{wavelengths:[1340,1400,1450],groups:[],reference:'none',definition:'processed group mean'} };
const tables = getResultTables(result);
assert.equal(tables.length, 2); assert.equal(tables[0].exportPath, 'data/preprocessed.csv');
assert.deepEqual(tables[0].rows, rows.slice(1));
assert.equal(tables[1].rows[0][1], '0.125');
const comparison = parseCsv(comparisonCsv([{id:'1',name:'旧版, 比較',createdAt:'2026-10-21T00:00:00Z',result}]));
for (const [column,value] of [['pipeline_mode','legacy-python'],['missing','mean'],['aquagram_reference','none']]) assert.equal(comparison[1][comparison[0].indexOf(column)],value);
assert.equal(comparison[1].length, comparison[0].length);
const paper={...result,metadata:{...result.metadata,settings:{...result.metadata.settings,analysisProfile:'paper-v1'}},
  aquagram:{...result.aquagram,mode:'paper-delta-C',unit:'ΔC',sdDdof:1},
  paper:{preprocessing:{inputKind:'as-recorded'},mode:{participantCount:7,referenceSource:{sha256:'a'.repeat(64)}}},
  exports:{...result.exports,'paper/delta_coordinates.csv':'sample_id,C1\n001,-0.3\n'}};
const paperTable=getResultTables(paper).find(table=>table.exportPath==='paper/delta_coordinates.csv');
assert.equal(paperTable.rows[0][1],'-0.3');
const paperCsv=parseCsv(comparisonCsv([{id:'paper',name:'artificial paper',createdAt:'2032-01-01',result:paper}]));
for (const [column,value] of [['analysis_profile','paper-v1'],['paper_input_kind','as-recorded'],['paper_loading_participants','7'],['aquagram_sd_ddof','1'],['paper_reference_sha256','a'.repeat(64)]]) assert.equal(paperCsv[1][paperCsv[0].indexOf(column)],value);
console.log('PASS: result table/CSV fidelity and comparison method provenance');
