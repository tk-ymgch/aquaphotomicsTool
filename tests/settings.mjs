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
  assert.equal(doc.schemaVersion, 1); assert.equal(doc.appVersion, '1.2');
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
console.log(`PASS: ${passed} settings checks (roundtrip, legacy provenance, strict validation, columns, SG grid, PLS, safety)`);
