import type { DatasetSummary, ExperimentConfig, ExperimentFileRole, UnitySummary } from './types';

export const phaseOrder = ['Baseline','Task','Recovery'] as const;
export function detectExperimentRole(name: string): ExperimentFileRole {
  if (/unity/i.test(name)) return 'Unity';
  if (/baseline|ベースライン/i.test(name)) return 'Baseline';
  if (/recovery|リカバリ|回復/i.test(name)) return 'Recovery';
  return 'Task';
}
export function experimentDefaults(summary: DatasetSummary, unity: UnitySummary | null): ExperimentConfig {
  const time = summary.experiment?.timeColumns[0];
  return {
    spectraTimeMode: time ? 'column' : 'manual', spectraTimeColumn: time?.column ?? null,
    spectraTimeUnit: time?.kind === 'datetime' ? 'datetime' : 'seconds',
    unityTimeColumn: unity?.suggestedTimeColumn ?? unity?.timeColumns[0]?.column ?? 'Time',
    unityTimeUnit: unity?.suggestedTimeUnit ?? 'seconds', unityStartTime:null, timeOffsetSeconds:0,
    manualPhases:{Baseline:{startSeconds:0,intervalSeconds:1},Task:{startSeconds:0,intervalSeconds:1},Recovery:{startSeconds:0,intervalSeconds:1}},
    windowSeconds:5,maxGapSeconds:.25,minCoverage:.5,minSamples:3,
    blinkThreshold:.2,blinkMinSeconds:.05,blinkMaxSeconds:.8,
  };
}
function object(value: unknown): Record<string,unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('同期設定の形式を確認してください。');
  return value as Record<string,unknown>;
}
function num(value:unknown, name:string, min:number, max:number, positive=false):number {
  if(typeof value!=='number'||!Number.isFinite(value)||value<min||value>max||positive&&value===min)throw new Error(`${name}の値を確認してください。`);
  return value;
}
function choice<T extends string>(value:unknown, values:readonly T[], name:string):T {
  if(typeof value!=='string'||!values.includes(value as T))throw new Error(`${name}を確認してください。`);
  return value as T;
}
function text(value:unknown, name:string, nullable=false):string|null {
  if(nullable&&value===null)return null;
  if(typeof value!=='string'||!value.trim()||value.length>4096)throw new Error(`${name}を指定してください。`);
  return value;
}
export function validateExperimentConfig(value:unknown):ExperimentConfig {
  const input=object(value), manual=object(input.manualPhases);
  const units=['seconds','milliseconds','datetime'] as const;
  const manualPhases={} as ExperimentConfig['manualPhases'];
  for(const phase of phaseOrder){const p=object(manual[phase]);manualPhases[phase]={startSeconds:num(p.startSeconds,`${phase}の開始秒`,-1e12,1e12),intervalSeconds:num(p.intervalSeconds,`${phase}の測定間隔`,0,1e9,true)};}
  const min=num(input.blinkMinSeconds,'瞬き候補の最短時間',0,10,true), max=num(input.blinkMaxSeconds,'瞬き候補の最長時間',0,10,true);
  if(max<min)throw new Error('瞬き候補の最長時間は最短時間以上にしてください。');
  const minSamples=num(input.minSamples,'窓内の最低サンプル数',2,1e7);
  if(!Number.isSafeInteger(minSamples))throw new Error('最低サンプル数は整数にしてください。');
  return {
    spectraTimeMode:choice(input.spectraTimeMode,['column','manual'],'スペクトルの時刻方式'),
    spectraTimeColumn:text(input.spectraTimeColumn,'スペクトル時刻列',true),
    spectraTimeUnit:choice(input.spectraTimeUnit,units,'スペクトル時刻単位'),
    unityTimeColumn:text(input.unityTimeColumn,'Unity時刻列')!,unityTimeUnit:choice(input.unityTimeUnit,units,'Unity時刻単位'),
    unityStartTime:text(input.unityStartTime,'Unity開始日時',true),timeOffsetSeconds:num(input.timeOffsetSeconds,'補正秒',-1e12,1e12),
    manualPhases,windowSeconds:num(input.windowSeconds,'集計窓の幅',0,3600,true),maxGapSeconds:num(input.maxGapSeconds,'欠測とみなす間隔',0,60,true),
    minCoverage:num(input.minCoverage,'最低カバー率',0,1),minSamples,
    blinkThreshold:num(input.blinkThreshold,'閉眼しきい値',0,1),blinkMinSeconds:min,blinkMaxSeconds:max,
    ...(input.anchorConfirmation==='user-confirmed-task-first'?{anchorConfirmation:'user-confirmed-task-first' as const}:{}),
  };
}
export function createExperimentSettings(config:ExperimentConfig){
  return {format:'aquaphotomics-experiment-settings',schemaVersion:1,createdAt:new Date().toISOString(),config:validateExperimentConfig(config)};
}
export function parseExperimentSettings(contents:string):ExperimentConfig {
  if(new TextEncoder().encode(contents).length>1024*1024)throw new Error('同期設定は1 MiB以下にしてください。');
  let value:unknown;try{value=JSON.parse(contents.replace(/^\uFEFF/,''));}catch{throw new Error('同期設定のJSON形式を確認してください。');}
  const doc=object(value);
  if(doc.format!=='aquaphotomics-experiment-settings'||doc.schemaVersion!==1)throw new Error('この同期設定ファイルには対応していません。');
  return validateExperimentConfig(doc.config);
}
