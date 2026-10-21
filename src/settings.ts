import type { AnalysisConfig, DatasetSummary, PLSConfig } from './types';

export interface SettingsDocument {
  format: 'aquaphotomics-workbench-settings';
  schemaVersion: 1;
  appVersion: '1.2';
  createdAt: string;
  source: { name: string; sheet: string | null } | null;
  config: AnalysisConfig;
}

const MAX_BYTES = 1024 * 1024;
const MAX_VARIABLES = 10_000;
const own = (value: object, key: string) => Object.hasOwn(value, key);
function fail(message: string): never { throw new Error(`設定を読み込めません。${message}`); }

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(`${label}はオブジェクトにしてください。`);
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) fail(`${label}の形式が不正です。`);
  return value as Record<string, unknown>;
}

function safeTree(value: unknown): void {
  const queue: { value: unknown; depth: number }[] = [{ value, depth: 0 }];
  let nodes = 0;
  while (queue.length) {
    const current = queue.pop()!;
    if (++nodes > 60_000 || current.depth > 40) fail('設定の構造が大きすぎます。');
    if (!current.value || typeof current.value !== 'object') continue;
    for (const key of Object.keys(current.value)) {
      if (['__proto__', 'constructor', 'prototype'].includes(key)) fail('安全でないプロパティ名が含まれています。');
      queue.push({ value: (current.value as Record<string, unknown>)[key], depth: current.depth + 1 });
    }
  }
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || !value.trim() || value.length > 4096) fail(`${label}は空欄でない文字列にしてください。`);
  return value;
}
function number(value: unknown, label: string, minimum = -Infinity, maximum = Infinity): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) fail(`${label}の数値が範囲外です。`);
  return value;
}
function integer(value: unknown, label: string, minimum: number, maximum = Number.MAX_SAFE_INTEGER): number {
  const result = number(value, label, minimum, maximum);
  if (!Number.isSafeInteger(result)) fail(`${label}は整数にしてください。`);
  return result;
}
function boolean(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') fail(`${label}はtrueまたはfalseにしてください。`);
  return value;
}
function choice<T extends string>(value: unknown, values: readonly T[], label: string): T {
  if (typeof value !== 'string' || !values.includes(value as T)) fail(`${label}の選択値が不正です。`);
  return value as T;
}
function column(value: unknown, label: string, columns: Set<string> | null): string | null {
  if (value === null) return null;
  const result = text(value, label);
  if (columns && !columns.has(result)) fail(`${label}「${result}」が読み込んだデータにありません。`);
  return result;
}

// Keep the same complete-label grammar as Python's parse_wavelength.
function wavelength(label: string): number | null {
  const numeric = '([+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+))';
  for (const pattern of [`^${numeric}\\s*(?:nm)?$`, `^(?:wl|wavelength|wave|nm|x)[_\\-\\s]*${numeric}\\s*(?:nm)?$`]) {
    const match = label.trim().match(new RegExp(pattern, 'i'));
    if (match) {
      const value = Number(match[1]);
      return Number.isFinite(value) && value > 0 ? value : null;
    }
  }
  return null;
}

function sourceMetadata(value: unknown): SettingsDocument['source'] {
  if (value === null) return null;
  const source = record(value, '元ファイル情報');
  return { name: text(source.name, '元ファイル名'), sheet: source.sheet === undefined || source.sheet === null ? null : text(source.sheet, 'シート名') };
}

function validateConfig(value: unknown, summary: DatasetSummary | null): AnalysisConfig {
  const input = record(value, '解析設定');
  const columns = summary ? new Set(summary.columns) : null;
  const idColumn = column(input.idColumn, '試料ID列', columns);
  const groupColumn = column(input.groupColumn, 'グループ列', columns);
  if (!Array.isArray(input.wavelengthColumns) || input.wavelengthColumns.length < 3 || input.wavelengthColumns.length > MAX_VARIABLES) fail('波長列は3〜10,000列指定してください。');
  const selected = input.wavelengthColumns.map(value => {
    const name = column(value, '波長列', columns);
    if (name === null) fail('波長列にnullは指定できません。');
    return name;
  });
  if (new Set(selected).size !== selected.length) fail('波長列が重複しています。');
  const detected = summary ? new Map(summary.wavelengthColumns.map(item => [item.column, item.wavelength])) : null;
  const entries = selected.map(name => {
    const parsed = wavelength(name);
    if (parsed === null) fail(`波長列「${name}」の列名から波長を取得できません。`);
    if (detected && detected.get(name) !== parsed) fail(`波長列「${name}」の検出波長が列名と一致しません。`);
    return { name, value: parsed };
  }).sort((a, b) => a.value - b.value);
  if (new Set(entries.map(entry => entry.value)).size !== entries.length) fail('同じ波長を示す列が複数あります。');
  if (!Array.isArray(input.range) || input.range.length !== 2) fail('波長範囲は下限・上限の2値にしてください。');
  const low = number(input.range[0], '波長範囲の下限', Number.MIN_VALUE);
  const high = number(input.range[1], '波長範囲の上限', Number.MIN_VALUE);
  if (low >= high) fail('波長範囲の下限は上限より小さくしてください。');
  const cropped = entries.filter(entry => entry.value >= low && entry.value <= high);
  if (cropped.length < 3) fail('指定した波長範囲に3列以上の波長が必要です。');
  const smooth = boolean(input.smooth, 'SG平滑化');
  const window = integer(input.window, 'SG窓幅', 3);
  const polyorder = integer(input.polyorder, 'SG多項式次数', 0);
  const derivative = integer(input.derivative, '微分次数', 0, 2) as 0 | 1 | 2;
  let grid = cropped.map(entry => entry.value);
  if (smooth || derivative > 0) {
    if (window % 2 === 0 || window > grid.length) fail('SG窓幅は選択範囲の波長数以下の奇数にしてください。');
    if (polyorder >= window || polyorder < derivative) fail('SG多項式次数は窓幅未満、微分次数以上にしてください。');
    const step = grid[1] - grid[0];
    if (grid.slice(1).some((value, i) => Math.abs(value - grid[i] - step) > 1e-9 + 1e-6 * Math.abs(step))) {
      const start = grid[0], end = grid.at(-1)!;
      grid = grid.map((_, i) => start + (end - start) * i / (grid.length - 1));
    }
  }
  if (!Array.isArray(input.aquagramWavelengths) || input.aquagramWavelengths.length < 3 || input.aquagramWavelengths.length > MAX_VARIABLES) fail('Aquagramの波長を3〜10,000点指定してください。');
  const targets = input.aquagramWavelengths.map(value => number(value, 'Aquagramの波長', Number.MIN_VALUE));
  if (new Set(targets).size !== targets.length) fail('Aquagramの波長が重複しています。');
  const tolerance = number(input.aquagramTolerance, 'Aquagramの許容誤差', 0);
  const positions = new Set<number>();
  for (const target of targets) {
    if (target < grid[0] || target > grid.at(-1)!) fail(`Aquagramの波長 ${target} nm が解析範囲外です。`);
    let left = 0, right = grid.length - 1;
    while (left < right) {
      const middle = Math.floor((left + right) / 2);
      if (grid[middle] < target) left = middle + 1;
      else right = middle;
    }
    let position = left;
    if (position > 0 && Math.abs(grid[position - 1] - target) <= Math.abs(grid[position] - target)) position--;
    if (Math.abs(grid[position] - target) > tolerance + Math.max(1, Math.abs(target)) * 1e-12) fail(`Aquagramの波長 ${target} nm に許容誤差内の測定波長がありません。`);
    if (positions.has(position)) fail('Aquagramの複数の指定波長が同じ波長に対応しています。');
    positions.add(position);
  }
  let reference = text(input.aquagramReference, 'Aquagramの基準');
  if (['Global mean', '全体平均'].includes(reference)) reference = 'global';
  else if (reference !== 'global' && !reference.startsWith('group:')) reference = `group:${reference}`;
  if (reference === 'group:') fail('Aquagramの対照群名を指定してください。');
  const config: AnalysisConfig = {
    idColumn, groupColumn, wavelengthColumns: selected, range: [low, high],
    missing: choice(input.missing, ['error', 'median'], '欠損処理'),
    scatter: choice(input.scatter, ['none', 'snv', 'msc'], '散乱補正'),
    smooth, window, polyorder, derivative,
    pcaScale: boolean(input.pcaScale, 'PCAの標準化'), components: integer(input.components, 'PCA成分数', 1, MAX_VARIABLES),
    aquagramWavelengths: targets, aquagramReference: reference, aquagramTolerance: tolerance,
  };
  if (input.pls !== undefined) {
    const pls = record(input.pls, 'PLS設定');
    const enabled = boolean(pls.enabled, 'PLSの有効設定');
    const targetColumn = column(pls.targetColumn, 'PLS目的変数列', columns);
    const cvGroupColumn = column(pls.cvGroupColumn, 'PLS分割グループ列', columns);
    const split = choice(pls.split, ['kfold', 'group'], 'PLSの分割方式');
    if (enabled && targetColumn === null) fail('PLSの目的変数列を指定してください。');
    if (enabled && selected.includes(targetColumn!)) fail('PLS目的変数列を説明変数の波長列から外してください。');
    if (enabled && (targetColumn === idColumn || targetColumn === cvGroupColumn)) fail('PLS目的変数列を試料ID列・分割グループ列と分けてください。');
    if (enabled && split === 'group' && cvGroupColumn === null) fail('PLSのグループ分割列を指定してください。');
    const parsed: PLSConfig = {
      enabled, targetColumn, maxComponents: integer(pls.maxComponents, 'PLS最大成分数', 1, 10),
      folds: integer(pls.folds, 'PLS分割数', 2, 10), split, cvGroupColumn,
      seed: integer(pls.seed, 'PLS乱数seed', 0, 2_147_483_647), scale: boolean(pls.scale, 'PLSの標準化'),
    };
    config.pls = parsed;
  }
  return config;
}

/** A reproducible configuration only: no spectra, preview rows or fitted values. */
export function createSettingsDocument(config: AnalysisConfig, source: { name: string; sheet?: string | null } | null): SettingsDocument {
  safeTree(config); safeTree(source);
  return {
    format: 'aquaphotomics-workbench-settings', schemaVersion: 1, appVersion: '1.2',
    createdAt: new Date().toISOString(), source: sourceMetadata(source), config: validateConfig(config, null),
  };
}

export function parseSettingsDocument(textInput: string, summary: DatasetSummary): AnalysisConfig {
  if (typeof textInput !== 'string' || textInput.length > MAX_BYTES || new TextEncoder().encode(textInput).byteLength > MAX_BYTES) fail('設定ファイルは1 MiB以下にしてください。');
  let parsed: unknown;
  try { parsed = JSON.parse(textInput.replace(/^\uFEFF/, '')); } catch { fail('JSON形式を確認してください。'); }
  safeTree(parsed);
  const document = record(parsed, '設定ファイル');
  let config: unknown = document;
  if (own(document, 'format')) {
    if (document.format !== 'aquaphotomics-workbench-settings') fail('この設定ファイルのformatには対応していません。');
    if (document.schemaVersion !== 1 || document.appVersion !== '1.2') fail('この設定ファイルのバージョンには対応していません。');
    if (typeof document.createdAt !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/.test(document.createdAt) || !Number.isFinite(Date.parse(document.createdAt))) fail('設定の作成日時が不正です。');
    sourceMetadata(document.source);
    config = document.config;
  } else if (own(document, '_provenance')) {
    const provenance = record(document._provenance, '旧形式の来歴');
    if (own(provenance, 'requestedConfig')) config = provenance.requestedConfig;
  }
  return validateConfig(config, summary);
}
