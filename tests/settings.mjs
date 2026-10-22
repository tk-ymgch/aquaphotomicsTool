// Node >=22.18: node tests/settings.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
const source = stripTypeScriptTypes(await readFile(new URL('../src/settings.ts', import.meta.url), 'utf8'));
const { createSettingsDocument, parseSettingsDocument } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

const waves = Array.from({ length: 61 }, (_, i) => 1300 + i * 5);
const summary = {
  name: '人工スペクトル.csv', columns: ['sample_id', 'group', 'target', 'batch', ...waves.map(w => `wl_${w}`)],
  preview: [], rowCount: 45, sheets: [], sheet: null, artificial: true,
  suggestedId: 'sample_id', suggestedGroup: 'group',
  wavelengthColumns: waves.map(wavelength => ({ column: `wl_${wavelength}`, wavelength })),
};
const config = {
  idColumn: 'sample_id', groupColumn: 'group', wavelengthColumns: waves.map(w => `wl_${w}`),
  range: [1300, 1600], missing: 'error', scatter: 'snv', smooth: true, window: 11,
  polyorder: 2, derivative: 0, pcaScale: false, components: 5,
  aquagramWavelengths: [1340, 1360, 1400, 1450, 1500, 1550], aquagramReference: 'group:対照群', aquagramTolerance: 2.5,
};
const pls = { enabled: true, targetColumn: 'target', maxComponents: 8, folds: 5, split: 'group', cvGroupColumn: 'batch', seed: 42, scale: true };
const decode = (value, dataset = summary) => parseSettingsDocument(JSON.stringify(value), dataset);
let passed = 0;
function check(name, test) { try { test(); passed++; } catch (error) { console.error(`FAIL: ${name}`); throw error; } }

check('new document roundtrip and detached snapshots', () => {
  const input = structuredClone(config), doc = createSettingsDocument(input, { name: summary.name });
  assert.equal(doc.format, 'aquaphotomics-workbench-settings');
  assert.equal(doc.schemaVersion, 1); assert.equal(doc.appVersion, '1.6');
  assert.equal(doc.source.sheet, null); assert.ok(Number.isFinite(Date.parse(doc.createdAt)));
  input.range[0] = 999; input.wavelengthColumns.length = 0;
  assert.deepEqual(decode(doc), config);
});
check('document contains only configuration and source labels', () => {
  const document = createSettingsDocument({ ...config, raw: [[123456]], preview: [['not exported']] }, { name: summary.name, sheet: null, data: 'not exported' });
  assert.equal('raw' in document.config, false); assert.equal('preview' in document.config, false);
  assert.deepEqual(Object.keys(document.source).sort(), ['name', 'sheet']);
  assert.equal(JSON.stringify(document).includes('not exported'), false);
});
check('optional PLS roundtrip and unknown-key stripping', () => {
  const document = createSettingsDocument({ ...config, pls: { ...pls, arbitrary: [1, 2] } }, null);
  assert.deepEqual(decode(document), { ...config, pls });
  assert.equal('arbitrary' in document.config.pls, false);
});
check('legacy flat settings and group-name migration', () => {
  assert.deepEqual(decode(config), config);
  assert.equal(decode({ ...config, aquagramReference: 'Control' }).aquagramReference, 'group:Control');
  assert.equal(decode({ ...config, aquagramReference: '全体平均' }).aquagramReference, 'global');
});
check('old provenance requestedConfig wins over applied interpolated settings', () => {
  const legacy = { ...config, range: [1, 2], aquagramWavelengths: [1, 1.5, 2], _provenance: { requestedConfig: config, appliedWavelengths: [1, 1.5, 2] } };
  assert.deepEqual(decode(legacy), config);
  assert.throws(() => decode({ ...legacy, _provenance: { requestedConfig: { ...config, scatter: 'unsupported' } } }), /散乱補正/);
});
check('uneven SG grid accepts requested targets and actual legacy targets', () => {
  const wavelengthColumns = [1300, 1303, 1310, 1315, 1320].map(wavelength => ({ column: `wl_${wavelength}`, wavelength }));
  const dataset = { ...summary, columns: ['sample_id', 'group', ...wavelengthColumns.map(w => w.column)], wavelengthColumns };
  const cfg = { ...config, wavelengthColumns: wavelengthColumns.map(w => w.column), range: [1300, 1320], window: 5, aquagramWavelengths: [1300, 1305, 1320], aquagramTolerance: 0 };
  assert.deepEqual(decode(cfg, dataset), cfg);
  assert.throws(() => decode({ ...cfg, smooth: false }, dataset), /許容誤差/);
});
check('unsupported formats and versions are rejected', () => {
  const doc = createSettingsDocument(config, null);
  for (const changed of [{ format: 'other' }, { schemaVersion: 2 }, { schemaVersion: '1' }, { appVersion: '2.0' }]) assert.throws(() => decode({ ...doc, ...changed }), /対応していません/);
});
check('malformed JSON and size limits fail clearly', () => {
  assert.throws(() => parseSettingsDocument('{', summary), /JSON/);
  assert.throws(() => parseSettingsDocument('a'.repeat(1024 * 1024 + 1), summary), /1 MiB/);
  assert.throws(() => parseSettingsDocument(JSON.stringify({ padding: '水'.repeat(400_000) }), summary), /1 MiB/);
  assert.deepEqual(parseSettingsDocument('\uFEFF' + JSON.stringify(config), summary), config);
});
check('prototype poison is rejected anywhere, including stripped keys', () => {
  for (const name of ['__proto__', 'constructor', 'prototype']) {
    const poisoned = JSON.stringify(config).replace(/}$/, `,"unknown":{"${name}":{"polluted":true}}}`);
    assert.throws(() => parseSettingsDocument(poisoned, summary), /安全でない/);
  }
  assert.equal({}.polluted, undefined);
});
check('columns and parsed wavelength metadata must match the loaded data', () => {
  assert.throws(() => decode({ ...config, idColumn: 'absent' }), /試料ID列/);
  assert.throws(() => decode({ ...config, wavelengthColumns: ['wl_1', 'wl_2', 'wl_3'] }), /波長列/);
  assert.throws(() => decode(config, { ...summary, wavelengthColumns: summary.wavelengthColumns.map((w, i) => i ? w : { ...w, wavelength: 1301 }) }), /一致しません/);
  assert.throws(() => decode({ ...config, wavelengthColumns: [config.wavelengthColumns[0], ...config.wavelengthColumns] }), /重複/);
});
check('type, finite numbers, bounds and SG validation', () => {
  for (const change of [{ smooth: 'true' }, { pcaScale: 1 }, { components: 0 }, { missing: 'drop' }, { scatter: 'SNV' }, { window: 10 }, { polyorder: 11 }, { derivative: 3 }, { range: [1500, 1300] }, { aquagramTolerance: -1 }]) assert.throws(() => decode({ ...config, ...change }));
  assert.throws(() => parseSettingsDocument(JSON.stringify(config).replace('"components":5', '"components":1e999'), summary), /数値/);
  assert.throws(() => decode({ ...config, range: [1300, 1301] }), /3列/);
});
check('Aquagram validation rejects duplicates, impossible mappings and out-of-range targets', () => {
  assert.throws(() => decode({ ...config, aquagramWavelengths: [1340, 1340, 1450] }), /重複/);
  assert.throws(() => decode({ ...config, aquagramWavelengths: [1340, 1341, 1450] }), /同じ波長/);
  assert.throws(() => decode({ ...config, aquagramWavelengths: [1200, 1400, 1500] }), /範囲外/);
  assert.throws(() => decode({ ...config, aquagramWavelengths: [1342, 1400, 1500], aquagramTolerance: 0 }), /許容誤差/);
});
check('PLS type, range, target and group validation', () => {
  const invalid = [{ maxComponents: 11 }, { folds: 1 }, { seed: -1 }, { seed: 2147483648 }, { scale: 'yes' }, { split: 'random' }, { targetColumn: null }, { targetColumn: 'absent' }, { targetColumn: 'wl_1400' }, { targetColumn: 'sample_id' }, { targetColumn: 'batch' }, { cvGroupColumn: null }];
  for (const change of invalid) assert.throws(() => decode({ ...config, pls: { ...pls, ...change } }));
  const disabled = { ...pls, enabled: false, targetColumn: null, cvGroupColumn: null };
  assert.deepEqual(decode({ ...config, pls: disabled }).pls, disabled);
  // The analysis engine caps requested folds to the available samples/groups.
  assert.equal(decode({ ...config, pls: { ...pls, folds: 10 } }, { ...summary, rowCount: 8 }).pls.folds, 10);
});
check('v1.2 imports retain the modern default and v1.3 preserves explicit compatibility', () => {
  const old = { ...createSettingsDocument(config, null), appVersion: '1.2' };
  assert.deepEqual(decode(old), config);
  const legacy = { ...config, pipelineMode: 'legacy-python', missing: 'mean', aquagramReference: 'none' };
  assert.deepEqual(decode(createSettingsDocument(legacy, null)), legacy);
  assert.equal(decode({ ...legacy, aquagramReference: 'None' }).aquagramReference, 'none');
  assert.equal(decode({ ...config, aquagramReference: 'group:none' }).aquagramReference, 'group:none');
  assert.throws(() => decode({ ...legacy, pipelineMode: 'r' }), /前処理方式/);
  assert.throws(() => decode({ ...old, appVersion: 1.3 }), /対応していません/);
});
check('legacy SG validates Aquagram against the original uneven grid', () => {
  const wavelengthColumns = [1300, 1303, 1310, 1315, 1320].map(wavelength => ({ column: `wl_${wavelength}`, wavelength }));
  const dataset = { ...summary, columns: ['sample_id', 'group', ...wavelengthColumns.map(w => w.column)], wavelengthColumns };
  const legacy = { ...config, pipelineMode: 'legacy-python', missing: 'mean', wavelengthColumns: wavelengthColumns.map(w => w.column), range: [1300, 1320], window: 5, aquagramWavelengths: [1300, 1303, 1320], aquagramTolerance: 0 };
  assert.deepEqual(decode(legacy, dataset), legacy);
  assert.throws(() => decode({ ...legacy, pipelineMode: 'modern' }, dataset), /許容誤差/);
});
check('v1.4 preserves only the engine choice and never a local connection credential', () => {
  const document = createSettingsDocument({ ...config, analysisEngine: 'aquap2', endpoint: 'http://127.0.0.1:8787', token: 'secret-session-token' }, null);
  assert.deepEqual(decode(document), { ...config, analysisEngine: 'aquap2' });
  assert.equal(JSON.stringify(document).includes('secret-session-token'), false);
  assert.equal(JSON.stringify(document).includes('8787'), false);
  assert.deepEqual(decode({ ...createSettingsDocument(config, null), appVersion: '1.3' }), config);
  assert.throws(() => decode({ ...config, analysisEngine: 'source-harness' }), /解析エンジン/);
});
check('aquap2py roundtrip keeps real uneven wavelengths and no connection secrets', () => {
  const wavelengthColumns=[1300,1303,1310,1315,1320].map(wavelength=>({column:`wl_${wavelength}`,wavelength}));
  const dataset={...summary,columns:['sample_id','group',...wavelengthColumns.map(w=>w.column)],wavelengthColumns};
  const cfg={...config,analysisEngine:'aquap2py',window:5,wavelengthColumns:wavelengthColumns.map(w=>w.column),range:[1300,1320],aquagramWavelengths:[1300,1303,1320],aquagramTolerance:0};
  const doc=createSettingsDocument({...cfg,token:'never-store',endpoint:'private-transport'},null);
  assert.deepEqual(decode(doc,dataset),cfg);
  assert.ok(!JSON.stringify(doc).includes('never-store'));
  assert.ok(!JSON.stringify(doc).includes('private-transport'));
  for (const appVersion of ['1.2','1.3','1.4']) assert.deepEqual(decode({...createSettingsDocument(config,null),appVersion}),config);
});
const nativeAquagram = {
  enabled: true, mode: 'aucs.dce', coordinateSystem: 'ot1.12', temperatureColumn: 'calibration_temperature',
  calibrationSmoothN: 17, tCalib: [20, 30], tExp: 25, smoothN: 21, msc: false, referenceGroup: null,
  calibrationSource: { name: 'artificial-calibration.xlsx', sheet: '温度校正', sha256: 'a'.repeat(64) },
};
const nativePlsr = { enabled: true, targetColumn: 'target', components: null, validation: 'LOO', cvGroupColumn: null };
check('v1.6 calibration source keeps identity only and is detached from the input', () => {
  const input = { ...config, analysisEngine: 'aquap2py', nativeAquagram: structuredClone(nativeAquagram) };
  const doc = createSettingsDocument(input, { name: summary.name });
  assert.deepEqual(decode(doc), input);
  assert.deepEqual(Object.keys(doc.config.nativeAquagram.calibrationSource).sort(), ['name', 'sha256', 'sheet']);
  input.nativeAquagram.tCalib[0] = 21;
  input.nativeAquagram.calibrationSource.name = 'changed.xlsx';
  assert.deepEqual(doc.config.nativeAquagram, nativeAquagram);
  // The temperature column belongs to the separate calibration file, not the measurement summary.
  assert.equal(summary.columns.includes(doc.config.nativeAquagram.temperatureColumn), false);
});
check('unknown calibration matrices and transport credentials are stripped on export and import', () => {
  const extra = { matrix: [['discard-calibration-measurements']], rawTemperatureMeans: [['discard-model-values']],
    credentials: { bearer: 'discard-calibration-credential' }, endpoint: 'discard-private-endpoint' };
  const aq = { ...nativeAquagram, ...extra, calibrationSource: { ...nativeAquagram.calibrationSource, ...extra } };
  const input = { ...config, analysisEngine: 'aquap2py', nativeAquagram: aq,
    nativePlsr: { ...nativePlsr, model: { coefficients: ['discard-fitted-model'] }, sessionBearer: 'discard-plsr-session' },
    calibration: extra, sessionBearer: 'discard-root-session' };
  const expected = { ...config, analysisEngine: 'aquap2py', nativeAquagram, nativePlsr };
  assert.deepEqual(decode(input), expected);
  const document = createSettingsDocument(input, { name: summary.name, ...extra });
  assert.deepEqual(decode(document), expected);
  assert.equal(JSON.stringify(document).includes('discard-'), false);
});
check('all calibrated Aquagram modes and both coordinate systems roundtrip without changing settings', () => {
  const modes = ['sfc', 'sfc-diff', 'aucs', 'aucs-diff', 'aucs.tn', 'aucs.tn-diff',
    'aucs.tn.dce', 'aucs.tn.dce-diff', 'aucs.dce', 'aucs.dce-diff'];
  for (const mode of modes) for (const coordinateSystem of ['ot1.12', 'ot1.15']) {
    const aq = { ...nativeAquagram, mode, coordinateSystem, msc: true, referenceGroup: mode.endsWith('-diff') ? 'group:literal-control-name' : null };
    const cfg = { ...config, analysisEngine: 'aquap2py', nativeAquagram: aq };
    assert.deepEqual(decode(createSettingsDocument(cfg, null)), cfg);
  }
});
check('calibration identity, temperatures, SG and required fields reject invalid settings', () => {
  const invalid = [{ temperatureColumn: null }, { mode: 'classic' }, { coordinateSystem: 'custom' },
    { tCalib: [30, 20] }, { tCalib: [20] }, { tCalib: ['20', 30] }, { tExp: '25' },
    { calibrationSmoothN: 16 }, { calibrationSmoothN: 1 }, { smoothN: 20 }, { smoothN: 503 }, { msc: 'false' },
    { mode: 'aucs-diff', referenceGroup: null }, { mode: 'sfc-diff', referenceGroup: '' },
    { calibrationSource: { ...nativeAquagram.calibrationSource, sha256: 'not-a-sha256' } },
    { calibrationSource: { ...nativeAquagram.calibrationSource, sheet: 123 } }];
  for (const change of invalid) assert.throws(() => decode({ ...config, nativeAquagram: { ...nativeAquagram, ...change } }));
  const disabled = { ...nativeAquagram, enabled: false, temperatureColumn: null, mode: 'aucs-diff', referenceGroup: null };
  assert.deepEqual(decode({ ...config, nativeAquagram: disabled }).nativeAquagram, disabled);
});
check('native PLSR fixed, automatic, LOO and group choices roundtrip without implicit clamping', () => {
  for (const components of [null, 1, 30]) for (const validation of ['LOO', 'group']) {
    const plsr = { ...nativePlsr, components, validation, cvGroupColumn: validation === 'group' ? 'batch' : null };
    const cfg = { ...config, analysisEngine: 'aquap2py', nativePlsr: plsr };
    assert.deepEqual(decode(createSettingsDocument(cfg, null)), cfg);
  }
  const disabled = { ...nativePlsr, enabled: false, targetColumn: null };
  assert.deepEqual(decode({ ...config, nativePlsr: disabled }).nativePlsr, disabled);
});
check('native PLSR target, component and CV group guards reject invalid settings', () => {
  const invalid = [{ targetColumn: null }, { targetColumn: 'absent' }, { targetColumn: 'sample_id' },
    { targetColumn: 'wl_1400' }, { components: 0 }, { components: 31 }, { components: 1.5 },
    { components: '2' }, { validation: 'kfold' }, { validation: 'group', cvGroupColumn: null },
    { validation: 'group', cvGroupColumn: 'target' }, { validation: 'group', cvGroupColumn: 'absent' },
    { validation: 'group', cvGroupColumn: 'wl_1400' }];
  for (const change of invalid) assert.throws(() => decode({ ...config, nativePlsr: { ...nativePlsr, ...change } }));
});
check('v1.5 documents preserve an explicit previous engine and do not gain native settings', () => {
  const cfg = { ...config, analysisEngine: 'python' };
  const doc = { ...createSettingsDocument(cfg, null), appVersion: '1.5' };
  assert.deepEqual(decode(doc), cfg);
  assert.equal('nativeAquagram' in decode(doc), false);
  assert.equal('nativePlsr' in decode(doc), false);
});
console.log(`PASS: ${passed} settings checks (roundtrip, legacy provenance, strict validation, columns, SG grid, PLS, native calibration/PLSR, safety)`);
