import type { AnalysisResult, ExperimentResult } from './types';

export type ExplorerSamples = NonNullable<AnalysisResult['aquagram']['samples']>;
export type ExplorerAxis = {values: number[]; label: string; unit: string; kind: 'order' | 'seconds' | 'numeric'; warnings: string[]};
export type ExplorerSettings = {seriesColumn: string; seriesValue: string; timeColumn: string; timeUnit: 'seconds' | 'milliseconds' | 'datetime' | 'numeric'; speed: number; selectedId: string; activeCoordinate: number | null; yaw: number; tilt: number};

export function validExplorerSamples(aq: AnalysisResult['aquagram']): boolean {
  const samples = aq.samples;
  return !!samples?.ids.length && aq.labels.length >= 3 && aq.wavelengths.length === aq.labels.length && samples.groups.length === samples.ids.length && samples.values.length === samples.ids.length && samples.values.every(row => row.length === aq.labels.length && row.every(Number.isFinite)) && Object.values(samples.metadata ?? {}).every(column => column.length === samples.ids.length);
}
export function explorerScale(values: number[][]): number {
  let maximum = 0;
  for (const row of values) for (const value of row) if (Number.isFinite(value)) maximum = Math.max(maximum, Math.abs(value));
  return maximum || 1;
}
// A shared zero ring preserves the sign of every coordinate. The center is not zero.
export function explorerRadius(value: number, scale: number): number { return 1 + .58 * value / scale; }
export function explorerPoint(coordinate: number, count: number, value: number, scale: number): [number, number] {
  const angle = 2 * Math.PI * coordinate / count - Math.PI / 2, radius = explorerRadius(value, scale);
  return [Math.cos(angle) * radius, Math.sin(angle) * radius];
}
export function aquagramRms(values: number[]): number {
  if (!values.length || !values.every(Number.isFinite)) return NaN;
  const maximum=values.reduce((a,b)=>Math.max(a,Math.abs(b)),0);
  return maximum ? maximum*Math.sqrt(values.reduce((sum,value)=>sum+(value/maximum)**2,0)/values.length) : 0;
}
export function seriesColumns(samples: ExplorerSamples): {key: string; values: string[]}[] {
  const columns = [{key: '$group', values: samples.groups}, ...Object.entries(samples.metadata ?? {}).map(([key, values]) => ({key, values: values.map(value => value === null ? '' : String(value))}))];
  return columns.map(column => ({key: column.key, values: [...new Set(column.values)].filter(Boolean)})).filter(column => column.values.length > 1 && column.values.length <= 100);
}
export function explorerIndices(samples: ExplorerSamples, column: string, value: string): number[] {
  const values = column === '$group' ? samples.groups : samples.metadata?.[column];
  return samples.ids.map((_, index) => index).filter(index => !column || !value || !!values && String(values[index] ?? '') === value);
}
function datetimeSeconds(value: string | number | null): number {
  // Parse only explicit year-first clocks; a naive clock has the same UTC
  // convention as the analysis worker, independent of the browser's timezone.
  if (typeof value !== 'string') return NaN;
  const match=value.trim().match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})[T ](\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:?\d{2})?$/i);
  if(!match)return NaN;
  const [,year,month,day,hour,minute,second='0',fraction='',offset]=match;
  const [y,mo,d,h,mi,s]=[year,month,day,hour,minute,second].map(Number),ms=Number((fraction+'000').slice(0,3));
  if(mo<1||mo>12||d<1||d>31||h>23||mi>59||s>59)return NaN;
  const date=new Date(0);date.setUTCFullYear(y,mo-1,d);date.setUTCHours(h,mi,s,ms);
  if(date.getUTCFullYear()!==y||date.getUTCMonth()!==mo-1||date.getUTCDate()!==d)return NaN;
  let seconds=date.getTime()/1000;
  if(offset&&offset.toUpperCase()!=='Z'){
    const parts=offset.slice(1).replace(':',''),oh=Number(parts.slice(0,2)),om=Number(parts.slice(2));
    if(oh>23||om>59)return NaN;
    seconds-=(offset[0]==='-'?-1:1)*(oh*3600+om*60);
  }
  return seconds;
}
export function explorerAxis(samples: ExplorerSamples, column: string, unit: ExplorerSettings['timeUnit'], experiment?: ExperimentResult | null): ExplorerAxis {
  if (!column) return {values: samples.ids.map((_, i) => i + 1), label: '試料の順序', unit: '試料番号', kind: 'order', warnings: []};
  if (column === '$synchronized') {
    const times = new Map(experiment?.rows.map(row => [row.id, row.timeSeconds]) ?? []);
    const values = samples.ids.map(id => times.get(id) ?? NaN);
    return {values, label: 'Unityと同期した測定時刻', unit: 's', kind: 'seconds', warnings: values.some(value => !Number.isFinite(value)) ? ['同期時刻のない試料は時系列表示から除きます。'] : []};
  }
  const input = samples.metadata?.[column] ?? [];
  let values = samples.ids.map((_, i) => input[i] === null || input[i] === undefined || typeof input[i] === 'string' && !String(input[i]).trim() ? NaN : unit === 'datetime' ? datetimeSeconds(input[i]) : Number(input[i]) / (unit === 'milliseconds' ? 1000 : 1));
  if (unit === 'datetime') {
    const first = values.find(Number.isFinite);
    if (first !== undefined) values = values.map(value => value - first);
  }
  return {values, label: unit === 'datetime' ? `${column}・最初の有効日時から` : column, unit: unit === 'numeric' ? '列の値' : 's', kind: unit === 'numeric' ? 'numeric' : 'seconds', warnings: values.some(value => !Number.isFinite(value)) ? ['時刻列の欠損・解釈できない値を持つ試料は時系列表示から除きます。日時は年から始まる形式を指定してください。'] : []};
}
export function orderedExplorerIndices(indices: number[], axis: ExplorerAxis): number[] { return indices.filter(index => Number.isFinite(axis.values[index])).sort((a, b) => axis.values[a] - axis.values[b] || a - b); }
export function nearestExplorerIndex(indices: number[], axis: ExplorerAxis, value: number): number {
  return indices.reduce((nearest, index) => nearest < 0 || Math.abs(axis.values[index] - value) < Math.abs(axis.values[nearest] - value) ? index : nearest, -1);
}
export function explorerDisplayIndices(indices: number[], selected: number, limit = 120): number[] {
  if (indices.length <= limit) return [...indices];
  const shown = new Set(Array.from({length: limit}, (_, i) => indices[Math.round(i * (indices.length - 1) / (limit - 1))]));
  if (indices.includes(selected)) shown.add(selected);
  return indices.filter(index => shown.has(index));
}
export function playbackDelay(current: number, next: number, kind: ExplorerAxis['kind'], speed: number): number {
  return kind === 'seconds' ? Math.max(16, Math.min(2_147_483_647,(next - current) * 1000 / speed)) : 1000 / speed;
}
export function explorerCsv(samples: ExplorerSamples, labels: string[], axis: ExplorerAxis, indices: number[]): string {
  const cell = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  return [['sample_id', 'group', `axis (${axis.unit})`, ...labels], ...indices.map(i => [samples.ids[i], samples.groups[i], axis.values[i], ...samples.values[i]])].map(row => row.map(cell).join(',')).join('\n') + '\n';
}
