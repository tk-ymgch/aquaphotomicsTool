import type { AnalysisResult, ExecutionRecord } from './types';

export interface Aquap2Health {
  connected: true; engine: 'aquap2'; aquap2Version: string; rVersion: string;
  api: 'aquap2::gdmm';
  capabilities: { pca: true; classic: true; classicDiff: true; pls: false; temperatureCalibration: false };
}
interface ROutput {
  warnings?: string[];
  pca: AnalysisResult['pca'];
  aquagram: Omit<AnalysisResult['aquagram'], 'labels'> & { ddof: 1; mode: 'classic' | 'classic-diff' };
  runtime: { engine: 'aquap2'; aquap2Version: string; rVersion: string;
    packageApiExecuted: true; api: 'aquap2::gdmm'; [key: string]: unknown };
}
const DEFAULT_ENDPOINT = 'http://127.0.0.1:8787';
const csvCell = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`;
const csv = (rows: unknown[][]) => rows.map(row => row.map(csvCell).join(',')).join('\n') + '\n';
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function validateEndpoint(endpoint: string): string {
  if (![DEFAULT_ENDPOINT, 'http://localhost:8787'].includes(endpoint.replace(/\/$/, ''))) throw new Error('R接続はこのPCの http://127.0.0.1:8787 または http://localhost:8787 を指定してください。');
  return endpoint.replace(/\/$/, '');
}

function matrix(value: unknown, rows: number, columns: number): value is number[][] {
  return Array.isArray(value) && value.length === rows && value.every(row => Array.isArray(row) && row.length === columns && row.every(finite));
}

export function validateROutput(output: unknown, result: AnalysisResult): ROutput {
  const value = output as ROutput;
  const { samples: n, variables: p } = result.metadata;
  const k = result.pca.explainedVariance.length;
  if (!value?.runtime || value.runtime.engine !== 'aquap2' || value.runtime.installedPackage !== true || value.runtime.packageApiExecuted !== true || value.runtime.api !== 'aquap2::gdmm' || typeof value.runtime.aquap2Version !== 'string' || !value.runtime.aquap2Version || typeof value.runtime.rVersion !== 'string') throw new Error('aquap2本体の実行記録を確認できません。');
  if (value.warnings !== undefined && (!Array.isArray(value.warnings) || value.warnings.length > 30 || !value.warnings.every(w => typeof w === 'string' && w.length < 4096))) throw new Error('Rの解析上の注意を読み取れません。');
  const pc = value.pca, aq = value.aquagram;
  if (!pc || !matrix(pc.scores, n, k) || !matrix(pc.loadings, p, k) || !Array.isArray(pc.explainedVariance) || pc.explainedVariance.length !== k || !pc.explainedVariance.every(v => finite(v) && v >= 0 && v <= 1 + 1e-10) || pc.explainedVariance.reduce((a, b) => a + b, 0) > 1 + 1e-8 || !same(pc.ids, result.spectra.ids) || !same(pc.groups, result.spectra.groups)) throw new Error('RのPCA結果の形状・試料順・値が一致しません。');
  if (!aq || aq.ddof !== 1 || aq.mode !== (result.metadata.settings.aquagramReference === 'global' ? 'classic' : 'classic-diff') || !same(aq.wavelengths, result.aquagram.wavelengths) || !Array.isArray(aq.groups) || aq.groups.length !== result.aquagram.groups.length || typeof aq.definition !== 'string' || typeof aq.reference !== 'string') throw new Error('RのAquagram結果の波長・群・計算定義を確認できません。');
  const names = new Set<string>();
  for (const group of aq.groups) {
    const expected = result.aquagram.groups.find(g => g.name === group.name);
    if (!expected || names.has(group.name) || group.n !== expected.n || !Array.isArray(group.values) || group.values.length !== aq.wavelengths.length || !group.values.every(finite)) throw new Error('RのAquagram結果の群・試料数・値が一致しません。');
    names.add(group.name);
  }
  return value;
}

/** Merge only actual R results. Preserve the Python preprocessing and a labelled baseline. */
export function mergeAquap2Result(result: AnalysisResult, output: ROutput): AnalysisResult {
  const checked = validateROutput(output, result);
  const converted = structuredClone(result);
  const execution: ExecutionRecord = {engine:'aquap2',preprocessingEngine:'python',pcaEngine:'aquap2',aquagramEngine:'aquap2',packageApiExecuted:true,aquap2Version:checked.runtime.aquap2Version,rVersion:checked.runtime.rVersion,api:'aquap2::gdmm',aquagramMode:result.metadata.settings.aquagramReference === 'global' ? 'classic' : 'classic-diff'};
  converted.metadata.settings.analysisEngine = 'aquap2';
  converted.metadata.execution = execution;
  converted.pca = structuredClone(checked.pca);
  converted.aquagram = {...structuredClone(checked.aquagram),labels:result.aquagram.labels};
  // No endpoint or connection token is included in saved results.
  const runtime = {...checked.runtime, stageExecution:execution};
  converted.exports['aquap2_runtime.json'] = JSON.stringify(runtime, null, 2);
  const settings = JSON.parse(result.exports['settings.json']);
  settings.analysisEngine = 'aquap2';
  settings._provenance = {...settings._provenance, execution,
    aquap2_not_executed:false, aquagramDefinition:checked.aquagram.definition,
    warnings:[...result.metadata.warnings,...(checked.warnings ?? [])],
    implementation:'Python Workbench preprocessing + installed aquap2 package PCA/Aquagram',
    aquap2Runtime:runtime, pcaEngine:'aquap2', aquagramEngine:'aquap2',
    preprocessingImplementation:'Python Workbench; identical preprocessed matrix supplied to aquap2'};
  converted.exports['settings.json'] = JSON.stringify(settings, null, 2);
  const pc = converted.pca, spectrum = result.spectra;
  const components = pc.explainedVariance.map((_,i)=>`PC${i+1}`);
  converted.exports['data/pca_scores.csv'] = csv([['sample_id','group',...components],...pc.scores.map((row,i)=>[spectrum.ids[i],spectrum.groups[i],...row])]);
  converted.exports['data/pca_loadings.csv'] = csv([['wavelength_nm',...components],...pc.loadings.map((row,i)=>[spectrum.wavelengths[i],...row])]);
  let cumulative = 0;
  converted.exports['data/pca_variance.csv'] = csv([['component','explained_variance_ratio','cumulative_ratio'],...pc.explainedVariance.map((v,i)=>[components[i],v,cumulative+=v])]);
  converted.exports['data/aquagram.csv'] = csv([['group','wavelength_nm','value','n'],...converted.aquagram.groups.flatMap(g=>g.values.map((value,i)=>[g.name,converted.aquagram.wavelengths[i],value,g.n]))]);
  converted.exports['data/python_reference_aquagram.csv'] = result.exports['data/aquagram.csv'];
  const factor = Math.sqrt((result.metadata.samples-1)/result.metadata.samples);
  const differences: unknown[][] = [['group','wavelength_nm','python_population_sd','aquap2_sample_sd','expected_aquap2','difference_from_expected']];
  let maximum = 0;
  for (const group of converted.aquagram.groups) {
    const baseline = result.aquagram.groups.find(g=>g.name===group.name)!;
    group.values.forEach((value,i)=>{const expected=baseline.values[i]*factor, difference=value-expected;maximum=Math.max(maximum,Math.abs(difference));differences.push([group.name,converted.aquagram.wavelengths[i],baseline.values[i],value,expected,difference]);});
  }
  converted.exports['data/aquap2_vs_python_aquagram.csv'] = csv(differences);
  converted.exports['aquap2_comparison.json'] = JSON.stringify({scope:'same Python-preprocessed matrix, same actual wavelengths and samples; classic/classic-diff',samples:result.metadata.samples,factor,maximumAbsoluteDifferenceAfterSdConversion:maximum,temperatureCalibrationCompared:false,packageApiExecuted:true},null,2);
  converted.exports['README.txt'] = (converted.exports['README.txt'] ?? '') + '\n実行エンジン: aquap2本体（このPCのR）。前処理はPython、PCA・Aquagramはaquap2::gdmmの実出力です。\nPython前処理後の同一行列を送信し、aquap2側の追加処理はaquap2_runtime.jsonへ記録しています。\nPythonとのAQ比較はdata/aquap2_vs_python_aquagram.csvを参照。標本SD/母SDの違いを換算した後の差です。\n';
  // Older Python README/provenance explicitly said aquap2 was not executed.
  converted.exports['README.txt'] = converted.exports['README.txt'].replaceAll('実装はNumPy・SciPy・scikit-learnによるPython処理です。aquap2は実行していません。','前処理はPythonで実行し、PCA・Aquagramはaquap2本体で実行しました。');
  converted.metadata.warnings = [...converted.metadata.warnings,...(checked.warnings ?? []),`PCA・Aquagramはaquap2 ${execution.aquap2Version}で実行しました。前処理はPythonです。`];
  if (converted.pls) throw new Error('aquap2接続ではPLS結果を混在させません。PLSを解除してください。');
  return converted;
}

export class Aquap2Client {
  readonly endpoint: string;
  private token = '';
  private expires = 0;
  private active: AbortController | null = null;
  constructor(endpoint = DEFAULT_ENDPOINT) { this.endpoint = validateEndpoint(endpoint); }

  disconnect(): void { this.active?.abort(); this.active=null; this.token=''; this.expires=0; }

  private async request(path: string, body?: unknown, token?: string, timeout = 45_000): Promise<any> {
    if (this.active) throw new Error('R接続の処理が進行中です。');
    const controller = new AbortController(); this.active=controller;
    const timer=setTimeout(()=>controller.abort(),timeout);
    try {
      const response = await fetch(this.endpoint+path,{method:body===undefined?'GET':'POST',headers:{'X-Aquaphotomics-Client':'1',...(body===undefined?{}:{'Content-Type':'application/json'}),...(token?{Authorization:`Bearer ${token}`}:{})},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal,credentials:'omit',redirect:'error',cache:'no-store'});
      const value=await response.json();
      if (!response.ok) throw new Error(typeof value.error==='string'?value.error.slice(0,500):'R接続先が要求を受け付けませんでした。');
      return value;
    } catch(error) {
      if (error instanceof TypeError || error instanceof SyntaxError) throw new Error('このPCのR接続に到達できません。サービスの起動とブラウザーのローカル接続許可を確認してください。');
      if (controller.signal.aborted) throw new Error('R接続を中止したか、待機時間を超えました。');
      throw error;
    } finally {clearTimeout(timer);if(this.active===controller)this.active=null;}
  }

  async connect(): Promise<Aquap2Health> {
    this.disconnect();
    const health=await this.request('/health');
    if (health.schemaVersion!==1 || health.available!==true || health.engine!=='aquap2' || health.api!=='aquap2::gdmm' || typeof health.aquap2Version!=='string' || typeof health.rVersion!=='string' || health.capabilities?.pca!==true || health.capabilities?.classic!==true) throw new Error('対応するaquap2サービスを確認できません。');
    const session=await this.request('/session',{client:'aquaphotomics-workbench'});
    if (typeof session.token!=='string' || session.token.length<32 || session.token.length>128 || !finite(session.expiresIn) || session.expiresIn<=0 || session.expiresIn>1800) throw new Error('R接続の有効期限を確認できません。');
    this.token=session.token;this.expires=Date.now()+session.expiresIn*1000;
    return {connected:true,engine:'aquap2',aquap2Version:health.aquap2Version,rVersion:health.rVersion,api:'aquap2::gdmm',capabilities:{pca:true,classic:true,classicDiff:true,pls:false,temperatureCalibration:false}};
  }

  async analyze(result: AnalysisResult): Promise<AnalysisResult> {
    const settings=result.metadata.settings;
    if (!this.token || Date.now()>=this.expires) throw new Error('先にRの接続テストを実行してください。');
    if (settings.pcaScale) throw new Error('aquap2接続ではPCAの波長ごとの標準化を解除してください。');
    if (settings.aquagramReference==='none') throw new Error('aquap2 classicでは全体平均または対照群を選択してください。');
    if (result.pls || settings.pls?.enabled) throw new Error('aquap2接続ではPLSを解除してください。');
    if (result.aquagram.wavelengths.length > 24) throw new Error('aquap2接続のAquagramは24波長までです。');
    const payload={schemaVersion:1,matrix:result.spectra.processed,wavelengths:result.spectra.wavelengths,ids:result.spectra.ids,groups:result.spectra.groups,aquagram:{wavelengths:result.aquagram.wavelengths,reference:settings.aquagramReference},pca:{components:result.pca.explainedVariance.length,scale:false}};
    return mergeAquap2Result(result,await this.request('/analyze',payload,this.token,195_000));
  }
}
