import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Activity, ArrowDownToLine, ArrowRight, ArrowUpRight, Check, ChevronRight, CircleHelp, Database, FileSpreadsheet, FlaskConical, LogOut, Menu, MousePointer2, Play, Plus, Radar, RefreshCw, ScatterChart, Settings2, ShieldCheck, SlidersHorizontal, Upload, Waves, X } from 'lucide-react';
import { strToU8, zipSync } from 'fflate';
import { AnalysisClient } from './client';
import { Aquap2Client } from './aquap2Client';
import type { AnalysisConfig, AnalysisResult, CalibrationSummary, NativeAquagramConfig, NativePLSRConfig, DatasetSummary, Progress } from './types';
import Plot, { figurePng } from './Plot';
import type { Figure } from './Plot';
import { PLSSettings, PLSResults, ComparisonPanel, plsFigures, comparisonFigures } from './AdvancedPanels';
import { createSettingsDocument, parseSettingsDocument } from './settings';
import type { ComparisonRun } from './types';
import rImportScript from '../scripts/r_import.R?raw';
import rBridgeGuide from '../docs/R_AQUAP2.md?raw';
import aquap2ComparisonGuide from '../docs/AQUAP2_COMPARISON.md?raw';
import { downloadBytes, comparisonCsv, snapshotBytes, getResultTables, exportCsv } from './downloads';
import MethodPanel, { EngineSelector, PipelineSelector } from './MethodPanel';
import {NativeAquagramSettings, NativePLSRSettings, NativePLSRResults, nativePlsrFigures} from './NativeAnalysisPanel';
import './styles.css';

type View = 'setup' | 'spectra' | 'pca' | 'aquagram' | 'pls' | 'compare' | 'tables' | 'methods';
type Source = { kind: 'file'; file: File; sheet?: string } | { kind: 'demo' };
const palette = ['#161616', '#747474', '#a5a5a5', '#424242', '#c1c1c1', '#878787'];
const dashes = ['solid', 'dash', 'dot', 'dashdot', 'longdash', 'longdashdot'];
const symbols = ['circle', 'square', 'diamond', 'triangle-up', 'cross', 'triangle-down'];
const viewNames: Record<View, string> = { setup: 'データと解析設定', spectra: 'スペクトル', pca: '主成分分析', aquagram: 'Aquagram', pls: 'PLS回帰', compare: '条件間比較', tables: '数値表', methods: '解析方式' };
const fmt = (value: unknown) => typeof value === 'number' ? Number.isFinite(value) ? value.toLocaleString('ja-JP', { maximumFractionDigits: 5 }) : '—' : value === null || value === undefined || value === '' ? '—' : String(value);
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const aquap2Endpoint = 'http://127.0.0.1:8787';
type Aquap2Health = Awaited<ReturnType<Aquap2Client['connect']>>;

const nativeAquagramDefaults = (): NativeAquagramConfig => ({enabled:false,mode:'aucs.dce',coordinateSystem:'ot1.12',temperatureColumn:null,calibrationSmoothN:17,tCalib:[20,30],tExp:25,smoothN:21,msc:false,referenceGroup:null});
const nativePlsrDefaults = (summary?:DatasetSummary): NativePLSRConfig => ({enabled:false,targetColumn:summary?.columns.includes('synthetic_target')?'synthetic_target':null,components:null,validation:'LOO',cvGroupColumn:null});
function defaults(summary: DatasetSummary): AnalysisConfig {
  const waves = [...summary.wavelengthColumns].sort((a, b) => a.wavelength - b.wavelength);
  const min = waves[0]?.wavelength ?? 1300, max = waves.at(-1)?.wavelength ?? 1600;
  const preset = [1342, 1364, 1374, 1384, 1412, 1426, 1440, 1452, 1462, 1478, 1488, 1512];
  const aq = min <= 1342 && max >= 1512 ? preset : Array.from(new Set(Array.from({ length: Math.min(12, waves.length) }, (_, i) => waves[Math.round(i * (waves.length - 1) / Math.max(1, Math.min(12, waves.length) - 1))]?.wavelength).filter(Number.isFinite)));
  const gaps = waves.slice(1).map((wave, i) => wave.wavelength - waves[i].wavelength).filter(x => x > 0).sort((a, b) => a - b);
  return { idColumn: summary.suggestedId, groupColumn: summary.suggestedGroup, wavelengthColumns: waves.map(x => x.column), range: [min, max], pipelineMode: 'modern', analysisEngine: 'aquap2py', missing: 'error', scatter: 'snv', smooth: true, window: Math.max(3, Math.min(11, waves.length % 2 ? waves.length : waves.length - 1)), polyorder: 2, derivative: 0, pcaScale: false, components: Math.min(5, Math.max(1, summary.rowCount - 1), Math.max(1, waves.length)), aquagramWavelengths: aq, aquagramReference: 'global', aquagramTolerance: Math.max(1, (gaps[Math.floor(gaps.length / 2)] ?? 2) * .6), nativeAquagram:nativeAquagramDefaults(),nativePlsr:nativePlsrDefaults(summary),pls:{enabled:false,targetColumn:summary.columns.includes('synthetic_target')?'synthetic_target':summary.columns.includes('target')?'target':null,maxComponents:5,folds:5,split:'kfold',cvGroupColumn:null,seed:20261021,scale:true} };
}
function modeName(settings: AnalysisConfig) { return settings.analysisEngine === 'aquap2py' ? settings.pipelineMode === 'legacy-python' ? 'SG→散乱補正順' : '散乱補正→SG順' : settings.pipelineMode === 'legacy-python' ? '旧Python互換' : '標準方式'; }
function resultEngineName(result: AnalysisResult) {
  const execution = result.metadata.execution;
  return execution?.engine === 'aquap2' ? `aquap2 ${execution.aquap2Version ?? ''} · R本体`.trim() : execution?.engine === 'aquap2py' ? `aquap2py ${execution.implementationVersion ?? ''}`.trim() : 'Workbench標準Python';
}
function engineRestrictions(settings: AnalysisConfig): string[] {
  if (settings.analysisEngine !== 'aquap2' && settings.analysisEngine !== 'aquap2py') return [];
  const name = settings.analysisEngine === 'aquap2py' ? 'aquap2py' : 'aquap2本体のR参照実行';
  return [settings.analysisEngine === 'aquap2py' && settings.missing !== 'error' ? 'aquap2pyの欠損値処理は「欠損があれば解析を停止」だけに対応します。平均値・中央値の補完は使用できません。' : '', settings.components > 10 ? `${name}のPCAは10成分までです。` : '', settings.aquagramWavelengths.length > 24 ? `${name}のAquagramは24波長までです。` : '', settings.pcaScale ? `PCAの「波長ごとに標準化」を解除してください。${name}では平均中心化のみ実行できます。` : '', aquagramIsMean(settings) && !(settings.analysisEngine === 'aquap2py' && settings.nativeAquagram?.enabled) ? `${name}ではAquagramの「基準なし」は未対応です。全体平均か対照群を選択してください。` : '', settings.pls?.enabled ? `${name}ではWorkbenchのnested PLS設定を解除してください。aquap2pyのPLSRは専用設定を使います。` : ''].filter(Boolean);
}
function preprocessingStages(settings: AnalysisConfig): string[] {
  const scatter = settings.scatter === 'none' ? '散乱補正なし' : settings.scatter.toUpperCase();
  const sg = settings.smooth || settings.derivative > 0 ? `SG ${settings.window}点${settings.derivative ? `・${settings.derivative}次微分` : '・平滑化'}` : 'SG処理なし';
  return settings.pipelineMode === 'legacy-python' ? [sg, scatter] : [scatter, sg];
}
function missingLabel(settings: AnalysisConfig) { return settings.missing === 'mean' ? '列平均で補完' : settings.missing === 'median' ? '列中央値で補完' : '欠損時は停止'; }
function aquagramIsMean(settings: AnalysisConfig) { return settings.aquagramReference === 'none' || settings.aquagramReference === 'None'; }

function parseWaves(text: string) {
  const tokens = text.trim().split(/[,、;\s]+/).filter(Boolean);
  const waves = tokens.map(Number);
  return { waves, valid: tokens.length >= 3 && waves.every(x => Number.isFinite(x) && x > 0) && new Set(waves).size === waves.length };
}
function layout(title: string, x = '', y = ''): Record<string, any> {
  return { title: { text: title, x: .035, xanchor: 'left', y: .985, yanchor: 'top', font: { size: 14, color: '#666' } }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(255,255,255,0)', font: { family: 'Arial, "Noto Sans JP", sans-serif', color: '#464646', size: 11 }, margin: { l: 72, r: 32, t: 100, b: 66 }, xaxis: { title: { text: x, standoff: 20 }, gridcolor: '#ebedef', zerolinecolor: '#d2d5d8', showline: true, linecolor: '#d5d8da', ticks: 'outside', tickcolor: '#d5d8da' }, yaxis: { title: { text: y, standoff: 18 }, gridcolor: '#ebedef', zerolinecolor: '#d2d5d8', showline: false }, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom', font: { size: 11 }, bgcolor: 'rgba(255,255,255,0)' }, hovermode: 'closest', hoverlabel: { bgcolor: '#fff', bordercolor: '#d5d5d5', font: { color: '#171717', size: 12 } }, uirevision: title };
}
function spectralFigure(result: AnalysisResult, mode: 'raw' | 'processed', selected: string | null): Figure {
  const spectra = result.spectra, groups = [...new Set(spectra.groups)], matrix = spectra[mode];
  // The display cap does not affect calculations or exported CSVs.
  const shown = new Set(Array.from({ length: Math.min(200, spectra.ids.length) }, (_, i) => Math.floor(i * spectra.ids.length / Math.min(200, spectra.ids.length))));
  if (selected) spectra.ids.forEach((id, i) => { if (id === selected) shown.add(i); });
  const data = groups.map((group, gi) => {
    const x: (number | null)[] = [], y: (number | null)[] = [], ids: (string | null)[] = [];
    spectra.ids.forEach((id, i) => { if (spectra.groups[i] !== group || !shown.has(i)) return; for (let j = 0; j < spectra.wavelengths.length; j++) { x.push(spectra.wavelengths[j]); y.push(matrix[i][j]); ids.push(id); } x.push(null); y.push(null); ids.push(null); });
    return { type: 'scatter', mode: 'lines', name: group, x, y, customdata: ids, line: { color: palette[gi % palette.length], width: 1.15, dash: dashes[gi % dashes.length] }, opacity: selected ? .22 : .75, connectgaps: false, hovertemplate: '%{customdata}<br>波長 %{x:.1f} nm<br>信号 %{y:.5g}<extra>' + group + '</extra>' };
  });
  if (selected) spectra.ids.forEach((id, i) => { if (id === selected) data.push({ type: 'scatter', mode: 'lines', name: id, x: spectra.wavelengths, y: matrix[i], customdata: spectra.wavelengths.map(() => id), line: { color: '#050505', width: 2.7, dash: 'solid' }, opacity: 1, connectgaps: false, hovertemplate: '%{customdata}<br>波長 %{x:.1f} nm<br>信号 %{y:.5g}<extra>選択した試料</extra>' }); });
  const y = mode === 'raw' ? '元の信号値' : result.metadata.settings.derivative ? `${result.metadata.settings.derivative} 次微分信号` : result.metadata.settings.scatter === 'none' ? '前処理後の信号値' : '前処理後の相対信号';
  return { data, layout: layout(mode === 'raw' ? 'RAW SPECTRA' : 'PREPROCESSED SPECTRA', '波長 / nm', y) };
}
function scoreFigure(result: AnalysisResult, x: number, y: number, selected: string | null): Figure {
  const pca = result.pca, hasY = (pca.scores[0]?.length ?? 0) > 1, groups = [...new Set(pca.groups)];
  return { data: groups.map((group, gi) => { const indices = pca.ids.map((_, i) => i).filter(i => pca.groups[i] === group); return { type: 'scatter', mode: 'markers', name: group, x: indices.map(i => pca.scores[i][x]), y: indices.map(i => hasY ? pca.scores[i][y] : i + 1), customdata: indices.map(i => pca.ids[i]), text: indices.map(i => pca.ids[i]), marker: { color: palette[gi % palette.length], size: indices.map(i => pca.ids[i] === selected ? 14 : 9), symbol: symbols[gi % symbols.length], line: { color: '#fff', width: 1.5 }, opacity: indices.map(i => selected && pca.ids[i] !== selected ? .2 : .85) }, hovertemplate: '%{customdata}<br>x: %{x:.4g}<br>y: %{y:.4g}<extra>' + group + '</extra>' }; }), layout: { ...layout('PCA SCORE PLOT', `PC${x + 1} · ${pct(pca.explainedVariance[x] ?? 0)}`, hasY ? `PC${y + 1} · ${pct(pca.explainedVariance[y] ?? 0)}` : '試料番号（第2成分なし）'), xaxis: { ...layout('').xaxis, title: `PC${x + 1} · ${pct(pca.explainedVariance[x] ?? 0)}`, zeroline: true }, yaxis: { ...layout('').yaxis, title: hasY ? `PC${y + 1} · ${pct(pca.explainedVariance[y] ?? 0)}` : '試料番号（第2成分なし）', zeroline: true } } };
}
function loadingFigure(result: AnalysisResult): Figure {
  const n = Math.min(3, result.pca.explainedVariance.length);
  return { data: Array.from({ length: n }, (_, c) => ({ type: 'scatter', mode: 'lines', name: `PC${c + 1}`, x: result.spectra.wavelengths, y: result.pca.loadings.map(row => row[c]), line: { color: palette[c], width: 2, dash: dashes[c] }, hovertemplate: '%{x:.1f} nm<br>%{y:.5g}<extra>PC' + (c + 1) + '</extra>' })), layout: layout('PCA LOADINGS', '波長 / nm', 'Loading') };
}
function varianceFigure(result: AnalysisResult): Figure {
  const values = result.pca.explainedVariance, x = values.map((_, i) => `PC${i + 1}`);
  let sum = 0;
  return { data: [{ type: 'bar', name: '各成分', x, y: values.map(v => v * 100), marker: { color: '#43484b', line: { width: 0 } }, hovertemplate: '%{x}<br>寄与率 %{y:.2f}%<extra></extra>' }, { type: 'scatter', mode: 'lines+markers', name: '累積', x, y: values.map(v => (sum += v * 100)), line: { color: '#a5a9ab', width: 2 }, marker: { color: '#151515', size: 6 }, hovertemplate: '%{x}<br>累積寄与率 %{y:.2f}%<extra></extra>' }], layout: { ...layout('EXPLAINED VARIANCE', '主成分', '寄与率 / %'), yaxis: { ...layout('').yaxis, title: '寄与率 / %', range: [0, 105] }, bargap: .58 } };
}
function aquagramFigure(result: AnalysisResult): Figure {
  const aq = result.aquagram, meanOnly = aquagramIsMean(result.metadata.settings), valueLabel = aquagramValueLabel(result), maximum = aq.groups.reduce((max, g) => g.values.reduce((current, value) => Math.max(current, Math.abs(value)), max), 0), limit = Math.max(1, Math.ceil(maximum * 1.15 * 2) / 2);
  return { data: [{ type: 'scatterpolar', r: [...aq.labels, aq.labels[0]].map(() => 0), theta: [...aq.labels, aq.labels[0]], mode: 'lines', name: '基準 0', hoverinfo: 'skip', line: { color: '#babfc1', width: 1, dash: 'dot' }, showlegend: false }, ...aq.groups.map((g, i) => ({ type: 'scatterpolar', mode: 'lines+markers', name: `${g.name} (n=${g.n})`, r: [...g.values, g.values[0]], theta: [...aq.labels, aq.labels[0]], line: { color: palette[i % palette.length], width: 2, dash: dashes[i % dashes.length] }, marker: { size: 5, symbol: symbols[i % symbols.length] }, fill: 'toself', fillcolor: `rgba(40,45,48,${i === 0 ? .04 : .015})`, hovertemplate: '%{theta}<br>' + valueLabel + ' %{r:.3f}<extra>' + g.name + '</extra>' }))], layout: { ...layout(isTemperatureAquagram(result) ? 'AQUAGRAM · '+aq.mode?.toUpperCase()+' · '+(aq.unit ?? '') : meanOnly ? 'AQUAGRAM · GROUP MEANS' : 'AQUAGRAM · STANDARDIZED GROUP DIFFERENCES'), margin: { l: 80, r: 80, t: 70, b: 55 }, legend: { orientation: 'h', x: 0, y: -.05 }, polar: { bgcolor: 'rgba(255,255,255,0)', radialaxis: { range: [-limit, limit], tickfont: { size: 10, color: '#999' }, gridcolor: '#e1e5e7', linecolor: '#d5d9db', ticks: '' }, angularaxis: { direction: 'clockwise', rotation: 90, gridcolor: '#e1e5e7', linecolor: '#d5d9db', tickfont: { size: 11, color: '#555' } } } } };
}
function isTemperatureAquagram(result: AnalysisResult): boolean { return /^(sfc|aucs)/.test(result.aquagram.mode ?? ''); }
function aquagramValueLabel(result: AnalysisResult): string {
  return isTemperatureAquagram(result) ? `${result.aquagram.mode} · ${result.aquagram.unit ?? '値'}` : aquagramIsMean(result.metadata.settings) ? '群平均値' : '標準化差';
}
function Field({ label, hint, children, wide = false }: { label: string; hint?: string; children: ReactNode; wide?: boolean }) { return <label className={`field ${wide ? 'field-wide' : ''}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>; }
function SectionTitle({ index, title, caption }: { index: string; title: string; caption: string }) { return <div className="section-title"><span className="step-index">{index}</span><div><h2>{title}</h2><p>{caption}</p></div></div>; }
function ExecutionSummary({ result }: { result: AnalysisResult }) {
  const execution = result.metadata.execution;
  const ddof = result.aquagram.sdDdof ?? execution?.aquagramSdDdof;
  return <div className="engine-result-record glass-panel"><span>前処理 <strong>{execution?.preprocessingEngine === 'aquap2py' ? `aquap2py ${execution.implementationVersion ?? ''}` : 'Python'} · {modeName(result.metadata.settings)}</strong></span><span>PCA・Aquagram <strong>{resultEngineName(result)}</strong></span>{execution?.engine === 'aquap2py' && <><span>参照aquap2版 <code>{execution.referenceAquap2Version ?? '—'}</code></span><span>R本体API <strong>実行なし</strong></span></>}{execution?.engine === 'aquap2' && <><span>R <code>{execution.rVersion ?? '—'}</code></span><span>実行API <code>{execution.api ?? '—'}</code></span></>}{execution?.aquagramMode && <span>Aquagram <code>{execution.aquagramMode}</code></span>}<span>AQ標準化 <strong>{isTemperatureAquagram(result) ? result.aquagram.mode?.startsWith('sfc') ? '校正平均を中心とする分母（n−1）' : 'AUC校正・'+result.aquagram.unit : aquagramIsMean(result.metadata.settings) ? 'なし' : ddof === 1 ? '標本SD（n−1）' : ddof === 0 ? '母SD（n）' : 'SD定義の記録なし'}</strong></span></div>;
}

export default function App() {
  const [view, setView] = useState<View>('setup');
  const [menu, setMenu] = useState(false);
  const [summary, setSummary] = useState<DatasetSummary | null>(null);
  const [calibrationSummary,setCalibrationSummary] = useState<CalibrationSummary|null>(null);
  const [config, setConfig] = useState<AnalysisConfig | null>(null);
  const [waterText, setWaterText] = useState('');
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [lastRunKey, setLastRunKey] = useState('');
  const [resultName, setResultName] = useState('');
  const [demo, setDemo] = useState(false);
  const [busy, setBusy] = useState<'load' | 'analyze' | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [dragging, setDragging] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [spectrumMode, setSpectrumMode] = useState<'raw' | 'processed'>('processed');
  const [pcaMode, setPcaMode] = useState<'scores' | 'loadings' | 'variance'>('scores');
  const [axisX, setAxisX] = useState(0), [axisY, setAxisY] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState('');
  const [help, setHelp] = useState(false);
  const [runs, setRuns] = useState<ComparisonRun[]>([]);
  const [runName, setRunName] = useState('条件 1');
  const [tableId, setTableId] = useState('data/pca_scores.csv');
  const [tablePage, setTablePage] = useState(0);
  const [aquap2Health, setAquap2Health] = useState<Aquap2Health | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectionError, setConnectionError] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const settingsInput = useRef<HTMLInputElement>(null);
  const client = useRef<AnalysisClient | null>(null);
  const aquap2Client = useRef<Aquap2Client | null>(null);
  const connectionAttempt = useRef(0);
  const source = useRef<Source | null>(null);
  const datasetReady = useRef(false);
  const calibrationReady = useRef(false);
  const calibrationSource = useRef<{file:File;sheet?:string}|null>(null);
  const calibrationFiles = useRef(new Map<string,File>());
  const operation = useRef(0);
  const parsedWater = parseWaves(waterText);
  const stale = !!result && (!!config && JSON.stringify(config) !== lastRunKey || !parsedWater.valid);
  const disabled = !!busy || exporting || connecting;
  const usesLocalR = config?.analysisEngine === 'aquap2';
  const usesPort = config ? config.analysisEngine === 'aquap2py' : true;
  const restrictions = config ? [...engineRestrictions(config),...(usesPort && config.nativeAquagram?.enabled && (!calibrationSummary || calibrationSummary.sourceSha256 !== config.nativeAquagram.calibrationSource?.sha256 || calibrationSummary.sheet !== config.nativeAquagram.calibrationSource?.sheet) ? ['温度校正ファイルを読み込んでください。設定が指定するSHA-256・シートと一致するファイルが必要です。'] : []),...(usesPort && config.nativePlsr?.enabled && (!config.nativePlsr.targetColumn || config.nativePlsr.validation === 'group' && !config.nativePlsr.cvGroupColumn) ? ['aquap2方式PLSRの目的変数・CV群を確認してください。'] : [])] : [];
  const engineReady = restrictions.length === 0 && (!usesLocalR || !!aquap2Health);
  const resultTables = useMemo(() => result && view === 'tables' ? getResultTables(result) : [], [result, view]);
  const activeTable = resultTables.find(table => table.id === tableId) ?? resultTables[0];
  const tablePages = Math.max(1, Math.ceil((activeTable?.rows.length ?? 0) / 50));
  const currentTablePage = Math.min(tablePage, tablePages - 1);
  const tableStart = currentTablePage * 50;
  const visibleTableColumns = activeTable?.columns.slice(0, 20) ?? [];
  useEffect(() => { setTablePage(0); }, [result, tableId]);
  useEffect(()=>{const keep=new Set([config?.nativeAquagram?.calibrationSource?.sha256,result?.metadata.settings.nativeAquagram?.calibrationSource?.sha256,...runs.map(run=>run.result.metadata.settings.nativeAquagram?.calibrationSource?.sha256)]);for(const key of calibrationFiles.current.keys())if(!keep.has(key))calibrationFiles.current.delete(key);},[config?.nativeAquagram?.calibrationSource?.sha256,result,runs]);
  const groups = useMemo(() => {
    if (result && config?.groupColumn === result.metadata.settings.groupColumn) return result.metadata.groups;
    if (!summary || !config?.groupColumn) return [];
    const col = summary.columns.indexOf(config.groupColumn);
    return [...new Set(summary.preview.map(row => String(row[col] ?? '')).filter(Boolean))];
  }, [summary, config?.groupColumn, result]);
  useEffect(() => () => { client.current?.dispose(); aquap2Client.current?.disconnect(); connectionAttempt.current += 1; }, []);
  const getClient = () => client.current ??= new AnalysisClient(setProgress);
  async function connectAquap2() {
    if (disabled) return;
    const attempt = ++connectionAttempt.current;
    aquap2Client.current?.disconnect();
    const remote = new Aquap2Client(aquap2Endpoint);
    aquap2Client.current = remote; setConnecting(true); setAquap2Health(null); setConnectionError('');
    try { const health = await remote.connect(); if (attempt === connectionAttempt.current) setAquap2Health(health); }
    catch (cause) { if (attempt === connectionAttempt.current) { remote.disconnect(); aquap2Client.current = null; setConnectionError(cause instanceof Error ? cause.message : String(cause)); } }
    finally { if (attempt === connectionAttempt.current) setConnecting(false); }
  }
  function disconnectAquap2() { connectionAttempt.current += 1; aquap2Client.current?.disconnect(); aquap2Client.current = null; setAquap2Health(null); setConnecting(false); setConnectionError(''); }
  function update<K extends keyof AnalysisConfig>(key: K, value: AnalysisConfig[K]) { setConfig(old => old ? { ...old, [key]: value, ...(key === 'groupColumn' ? { aquagramReference: 'global' } : {}) } : null); setNotice(''); }
  function navigate(next: View) { setView(next); setMenu(false); window.scrollTo({ top: 0, behavior: 'auto' }); }
  async function load(next: Source) {
    if (disabled) return;
    const id = ++operation.current;
    setBusy('load'); setError(''); setNotice(''); setProgress({ phase: 'load', message: next.kind === 'demo' ? '人工サンプルデータを準備しています' : 'データを読み込んでいます' });
    try {
      const data = next.kind === 'demo' ? await getClient().demo() : await getClient().load(next.file, next.sheet);
      if (id !== operation.current) return;
      source.current = next.kind === 'file' ? { ...next, sheet: data.sheet ?? undefined } : next;
      datasetReady.current = true;
      calibrationReady.current = false; calibrationSource.current=null; calibrationFiles.current.clear(); setCalibrationSummary(null);
      const initial = defaults(data);
      setSummary(data); setConfig(initial); setWaterText(initial.aquagramWavelengths.join(', ')); setDemo(data.artificial); setResult(null); setLastRunKey(''); setSelected(null); setAxisX(0); setAxisY(1); setRuns([]); setRunName('条件 1'); navigate('setup');
      if (!data.wavelengthColumns.length) setError(data.dataKind === 'unity-log' ? 'このファイルはUnityの位置・視線・瞳孔などの時系列ログです。波長スペクトルを含まないため、PCA・Aquagramの入力には使えません。波長列を含む測定CSVを選択してください。' : '波長列を検出できませんでした。スペクトルの列名が 1300、1300nm など波長を示す形式のデータを選択してください。');
    } catch (cause) { if (id === operation.current) { client.current?.dispose(); client.current = null; datasetReady.current = false; calibrationReady.current = false; setError(cause instanceof Error ? cause.message : String(cause)); } }
    finally { if (id === operation.current) { setBusy(null); setProgress(null); } }
  }
  async function loadCalibration(file:File,sheet?:string) {
    if(disabled) return;
    const id=++operation.current;setBusy('load');setError('');setProgress({phase:'calibration',message:'温度校正ファイルを確認しています'});
    try {
      const loaded=await getClient().loadCalibration(file,sheet);
      if(id!==operation.current) return;
      calibrationSource.current={file,sheet:loaded.sheet??undefined};calibrationReady.current=true;
      calibrationFiles.current.set(loaded.sourceSha256,file);setCalibrationSummary(loaded);
      setConfig(old=>{if(!old)return old;const current=old.nativeAquagram??nativeAquagramDefaults();const name=loaded.temperatureColumns.some(c=>c.column===current.temperatureColumn)?current.temperatureColumn:loaded.temperatureColumns.find(c=>/temp|温度/i.test(c.column))?.column??loaded.temperatureColumns[0]?.column??null;
        return {...old,nativeAquagram:{...current,temperatureColumn:name,calibrationSource:{name:loaded.name,sheet:loaded.sheet,sha256:loaded.sourceSha256}}};});
      setNotice('温度校正データを読み込みました。温度列と観測温度・測定側の尺度を確認してください。');
    }catch(cause){if(id===operation.current){client.current?.dispose();client.current=null;datasetReady.current=false;calibrationReady.current=false;setError(cause instanceof Error?cause.message:String(cause));}}
    finally{if(id===operation.current){setBusy(null);setProgress(null);}}
  }
  function chooseFile(file?: File) { if (file) { if (!/\.(csv|xlsx|xls)$/i.test(file.name)) { setError('CSV、Excel（.xlsx / .xls）ファイルを選んでください。'); return; } void load({ kind: 'file', file }); } if (fileInput.current) fileInput.current.value = ''; }
  function cancel() {
    operation.current += 1; client.current?.dispose(); client.current = null; datasetReady.current = false; calibrationReady.current = false; if (usesLocalR) disconnectAquap2(); setBusy(null); setProgress(null); setNotice(usesLocalR ? '処理を中止し、aquap2との接続を解除しました。再実行前に接続を確認してください。' : '処理を中止しました。再実行時にデータを読み直します。');
  }
  async function analyze() {
    if (!config || !summary || disabled) return;
    if (!parsedWater.valid) { setError('Aquagramの波長は、重複のない正の数値を3個以上、カンマで区切って指定してください。'); navigate('setup'); return; }
    if (config.wavelengthColumns.length < 3) { setError('解析する波長列を3列以上選んでください。'); navigate('setup'); return; }
    if (!engineReady || usesLocalR && !aquap2Client.current) { setError(restrictions[0] ?? 'aquap2の接続を確認してから解析してください。'); navigate('setup'); return; }
    const applied = structuredClone({ ...config, aquagramWavelengths: parsedWater.waves });
    const id = ++operation.current;
    setBusy('analyze'); setError(''); setNotice(''); setProgress({ phase: 'analyze', message: '解析を開始しています' });
    try {
      if (!datasetReady.current && source.current) { const src = source.current; if (src.kind === 'demo') await getClient().demo(); else await getClient().load(src.file, src.sheet); datasetReady.current = true; calibrationReady.current=false; }
      if(applied.analysisEngine === 'aquap2py' && applied.nativeAquagram?.enabled && !calibrationReady.current){const cal=calibrationSource.current;if(!cal)throw new Error('温度校正ファイルを読み込んでください。');await getClient().loadCalibration(cal.file,cal.sheet);calibrationReady.current=true;}
      let analysis = await getClient().analyze(applied);
      if (id !== operation.current) return;
      if (applied.analysisEngine === 'aquap2') {
        if (!aquap2Client.current) throw new Error('aquap2に接続されていません。接続を確認してください。');
        setProgress({phase:'aquap2',message:'前処理後のデータを端末上のaquap2へ送り、PCA・Aquagramを実行しています'});
        analysis = await aquap2Client.current.analyze(analysis);
      }
      if (id !== operation.current) return;
      setResult(analysis); setLastRunKey(JSON.stringify(applied)); setResultName(summary.name); setSelected(null); setAxisX(0); setAxisY(Math.min(1, analysis.pca.explainedVariance.length - 1)); navigate('spectra');
    } catch (cause) { if (id === operation.current) { client.current?.dispose(); client.current = null; datasetReady.current = false; calibrationReady.current = false; if (applied.analysisEngine === 'aquap2') { disconnectAquap2(); setConnectionError('解析中にエラーが発生しました。サービスの状態を確認し、再接続してください。'); } setError(cause instanceof Error ? cause.message : String(cause)); } }
    finally { if (id === operation.current) { setBusy(null); setProgress(null); } }
  }
  const figures = useMemo(() => result ? { raw: spectralFigure(result, 'raw', selected), processed: spectralFigure(result, 'processed', selected), scores: scoreFigure(result, Math.min(axisX, result.pca.explainedVariance.length - 1), Math.min(axisY, result.pca.explainedVariance.length - 1), selected), loadings: loadingFigure(result), variance: varianceFigure(result), aquagram: aquagramFigure(result), ...(result.pls ? plsFigures(result.pls) : {}),...(result.nativePlsr ? nativePlsrFigures(result.nativePlsr,result.spectra.wavelengths) : {}) } : null, [result, selected, axisX, axisY]);

  function requestedSettings(saved:AnalysisResult):AnalysisConfig {
    if (!summary) throw new Error('先に解析データを読み込んでください。');
    // This provenance comes from our Worker. Extract only the requested config
    // before applying the external-file parser's 1 MiB bound; large provenance
    // arrays must not prevent a valid analysis from being exported or restored.
    const document=saved.exports['settings.json']?JSON.parse(saved.exports['settings.json']):null;
    const requested=document?._provenance?.requestedConfig ?? saved.metadata.settings;
    return parseSettingsDocument(JSON.stringify(createSettingsDocument(requested,{name:summary.name,sheet:summary.sheet})),summary);
  }
  function saveSettings() {
    if (!config || !summary || disabled) return;
    try {
      if (!parsedWater.valid) throw new Error('Aquagramの波長を確認してください。');
      const checked = parseSettingsDocument(JSON.stringify(createSettingsDocument(config, {name:summary.name,sheet:summary.sheet})), summary);
      downloadBytes(strToU8(JSON.stringify(createSettingsDocument(checked, {name:summary.name,sheet:summary.sheet}), null, 2)), 'aquaphotomics-settings.json', 'application/json');
      setNotice('現在の解析設定を保存しました。測定データは含みません。'); setError('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }
  async function readSettings(file?: File) {
    if (settingsInput.current) settingsInput.current.value = '';
    if (!file || !summary || disabled) return;
    const id = ++operation.current;
    setBusy('load'); setError(''); setProgress({phase:'settings',message:'解析設定を読み込んでいます'});
    try {
      if (file.size > 1024 * 1024) throw new Error('設定ファイルは1 MiB以下にしてください。');
      const imported = parseSettingsDocument(await file.text(), summary);
      if (id !== operation.current) return;
      setConfig(imported); setWaterText(imported.aquagramWavelengths.join(', ')); navigate('setup');
      setNotice('解析設定を読み込みました。設定を確認して再解析してください。');
    } catch (cause) { if (id === operation.current) setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { if (id === operation.current) {setBusy(null);setProgress(null);} }
  }
  function retainRun() {
    if (!result || stale || disabled) return;
    if (runs.length >= 4) {setError('比較できる解析結果は4件までです。不要な条件を取り除いてください。');return;}
    if (runs.reduce((total,run)=>total+snapshotBytes(run.result),0)+snapshotBytes(result)>96*1024*1024) {setError('比較結果の保持容量は96 MiBまでです。不要な条件を取り除くか、データを小さくしてください。');return;}
    const label = runName.trim().slice(0,80) || `条件 ${runs.length+1}`;
    setRuns(old=>[...old,{id:crypto.randomUUID(),name:label,createdAt:new Date().toISOString(),result:structuredClone(result)}]);
    setRunName(`条件 ${runs.length+2}`);setError('');setNotice(`「${label}」を比較用に保持しました。`);
  }
  function restoreRun(id:string) {
    const run=runs.find(item=>item.id===id);
    if (!run || !summary || disabled) return;
    try {
      const restored = requestedSettings(run.result);
      setConfig(restored);setWaterText(restored.aquagramWavelengths.join(', '));navigate('setup');setNotice(`「${run.name}」の設定を復元しました。再解析で適用できます。`);setError('');
    } catch(cause) {setError(cause instanceof Error?cause.message:String(cause));}
  }
  async function saveComparison() {
    if (!runs.length || disabled) return;
    setExporting(true);setError('');setExportStatus('比較結果をまとめています');
    const savedRuns=structuredClone(runs);
    try {
      const files:Record<string,Uint8Array>={'comparison.csv':strToU8('\uFEFF'+comparisonCsv(savedRuns)),'docs/AQUAP2_COMPARISON.md':strToU8(aquap2ComparisonGuide),'comparison.json':strToU8(JSON.stringify({format:'aquaphotomics-comparison',schemaVersion:1,source:summary?.name,runs:savedRuns.map(({id,name,createdAt,result})=>({id,name,createdAt,settings:result.metadata.settings,execution:result.metadata.execution??null,compatibilityReport:result.metadata.compatibilityReport??null,nativePlsr:result.nativePlsr?{algorithm:result.nativePlsr.algorithm,settings:result.nativePlsr.settings,metrics:result.nativePlsr.metrics}:null,pls:result.pls?{method:result.pls.method,metrics:result.pls.metrics}:null}))},null,2)), 'README.txt':strToU8('同じデータに適用した解析条件の比較です。各条件の結果と適用設定を保存しています。\nPC寄与率は前処理により分散の基準が異なるためモデル性能の優劣ではありません。\nPLSのOOF性能も、同じ目的変数・分割設定で比較してください。条件比較を見て選んだモデルの性能確認には別の独立データが必要です。\n再読込できるのは各条件フォルダーのanalysis-settings.json（推奨）またはsettings.jsonです。比較一覧や結果そのもののセッション再読込は行いません。\n')};
      for (let i=0;i<savedRuns.length;i++) {
        const run=savedRuns[i], prefix=`condition-${i+1}/`;
        for (const [name,text] of Object.entries(run.result.exports)) {
          const safe=name.replace(/\\/g,'/').split('/').filter(part=>part&&part!=='.'&&part!=='..').join('/');
          files[prefix+safe]=strToU8(safe.endsWith('.csv')?'\uFEFF'+text.replace(/^\uFEFF/,''):text);
        }
        files[prefix+'analysis-settings.json']=strToU8(JSON.stringify(createSettingsDocument(requestedSettings(run.result),{name:summary?.name??resultName,sheet:summary?.sheet}),null,2));
        const identity=run.result.metadata.settings.nativeAquagram?.calibrationSource; if(run.result.metadata.settings.nativeAquagram?.enabled && identity){const file=calibrationFiles.current.get(identity.sha256);if(!file)throw new Error('比較条件の元の校正ファイルを再読込してください。');files[prefix+'calibration/source/'+file.name.replace(/[\\/:*?"<>|]/g,'_')]=new Uint8Array(await file.arrayBuffer());}
        const runFigures={...comparisonFigures(run.result),...(run.result.nativePlsr?nativePlsrFigures(run.result.nativePlsr,run.result.spectra.wavelengths):{})};
        for (const [name,figure] of Object.entries(runFigures)) {
          setExportStatus(`比較グラフを保存しています ${i+1} / ${savedRuns.length}`);
          const url=await figurePng(figure); files[prefix+`figures/${name}.png`]=Uint8Array.from(atob(url.split(',')[1]),char=>char.charCodeAt(0));
        }
      }
      downloadBytes(zipSync(files,{level:6}),`aquaphotomics-comparison-${new Date().toISOString().slice(0,10)}.zip`,'application/zip');
      setNotice('比較一覧・各条件の結果と設定・グラフをZIPに保存しました。');
    }catch(cause){setError(`比較結果を保存できませんでした。${cause instanceof Error?cause.message:String(cause)}`);}
    finally{setExporting(false);setExportStatus('');}
  }
  async function saveZip() {
    if (!result || !figures || disabled) return;
    setExporting(true); setError(''); setExportStatus('解析データをまとめています');
    const saved = result, savedFigures = figures, src = source.current;
    try {
      const files: Record<string, Uint8Array> = {};
      for (const [name, contents] of Object.entries(saved.exports)) {
        const safe = name.replace(/\\/g, '/').split('/').filter(part => part && part !== '.' && part !== '..').join('/');
        files[safe.endsWith('.csv') && !safe.includes('/') ? `data/${safe}` : safe] = strToU8(safe.endsWith('.csv') ? '\uFEFF' + contents.replace(/^\uFEFF/, '') : contents);
      }
      if (!files['settings.json']) files['settings.json'] = strToU8(JSON.stringify(saved.metadata.settings, null, 2));
      if (summary) files['analysis-settings.json']=strToU8(JSON.stringify(createSettingsDocument(requestedSettings(saved),{name:resultName,sheet:summary.sheet}),null,2));
      files['r/r_import.R']=strToU8(rImportScript);
      files['r/R_AQUAP2.md']=strToU8(rBridgeGuide);
      files['docs/AQUAP2_COMPARISON.md']=strToU8(aquap2ComparisonGuide);
      files['metadata.json'] = strToU8(JSON.stringify({ source: resultName, artificial: demo, ...saved.metadata }, null, 2));
      if (src?.kind === 'file') files[`source/${src.file.name.replace(/[\\/:*?"<>|]/g, '_')}`] = new Uint8Array(await src.file.arrayBuffer());
      const calIdentity=saved.metadata.settings.nativeAquagram?.calibrationSource; if(saved.metadata.settings.nativeAquagram?.enabled && calIdentity){const file=calibrationFiles.current.get(calIdentity.sha256);if(!file)throw new Error('元の校正ファイルを再読込してください。');files['calibration/source/'+file.name.replace(/[\\/:*?"<>|]/g,'_')]=new Uint8Array(await file.arrayBuffer());}
      const entries = Object.entries(savedFigures);
      for (let i = 0; i < entries.length; i++) {
        const [name, figure] = entries[i]; setExportStatus(`グラフを保存しています ${i + 1} / ${entries.length}`);
        const url = await figurePng(figure), binary = atob(url.split(',')[1]);
        files[`figures/${name}.png`] = Uint8Array.from(binary, c => c.charCodeAt(0));
      }
      const extra = `\n\nAquaphotomics Workbench\n元データ: ${resultName}\n${demo ? 'このデータは動作確認用の人工サンプルです。実測データではありません。\n' : ''}設定ファイルは表示結果に実際に適用された設定です。\n解析エンジン: ${resultEngineName(saved)}\n前処理: ${saved.metadata.execution?.preprocessingEngine === 'aquap2py' ? 'aquap2py' : 'Python'} / ${modeName(saved.metadata.settings)}\n${saved.metadata.execution?.api ? `実行API: ${saved.metadata.execution.api}\n` : ''}${saved.metadata.execution?.rVersion ? `R: ${saved.metadata.execution.rVersion}\n` : ''}${stale ? '画面の未適用設定は含めていません。保存された結果は直前に完了した解析です。\n' : ''}Aquagramは${saved.aquagram.definition}\n図の選択試料: ${selected ?? 'なし'}\n図のPCA軸: PC${axisX + 1}, ${saved.pca.explainedVariance.length > 1 ? `PC${axisY + 1}` : '試料番号'}\n`;
      files['README.txt'] = strToU8((saved.exports['README.txt'] ?? '') + extra);
      setExportStatus('ZIPファイルを作成しています');
      const bytes = zipSync(files, { level: 6 });
      const url = URL.createObjectURL(new Blob([bytes as Uint8Array<ArrayBuffer>], { type: 'application/zip' }));
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `aquaphotomics_${resultName.replace(/\.[^.]+$/, '').replace(/[^\p{L}\p{N}_-]/gu, '_')}_${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}.zip`; document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 30_000);
      setNotice('解析データ・適用設定・グラフをZIPにまとめました。');
    } catch (cause) { setError(`ZIPを作成できませんでした。${cause instanceof Error ? cause.message : String(cause)}`); }
    finally { setExporting(false); setExportStatus(''); }
  }
  const selectedIndex = result && selected ? result.spectra.ids.indexOf(selected) : -1;
  const selectedGroup = result && selectedIndex >= 0 ? result.spectra.groups[selectedIndex] : '';
  const processing = config ? `${modeName(config)} · ${preprocessingStages(config).join(' → ')}` : '';
  const resultProcessing = result ? preprocessingStages(result.metadata.settings).join(' → ') : '';

  return <div className="app-shell">
    <a className="skip-link" href="#workspace">解析画面へ移動</a>
    <input className="visually-hidden" type="file" accept=".csv,.xlsx,.xls" ref={fileInput} onChange={e => chooseFile(e.target.files?.[0])} disabled={disabled} />
    <input className="visually-hidden" type="file" accept=".json,application/json" ref={settingsInput} aria-label="解析設定JSONファイル" onChange={e => void readSettings(e.target.files?.[0])} disabled={!summary || disabled} />
    {menu && <button className="sidebar-scrim" aria-label="メニューを閉じる" onClick={() => setMenu(false)} />}
    <aside className={`sidebar ${menu ? 'is-open' : ''}`}>
      <a className="brand" href="#" onClick={e => { e.preventDefault(); navigate('setup'); }}><span className="brand-mark"><Waves size={25} strokeWidth={1.3} /></span><span>aquaphotomics<small>ANALYSIS WORKBENCH</small></span></a>
      <div className="sidebar-divider" />
      <div className="nav-caption">WORKSPACE <span>01</span></div>
      <nav aria-label="解析メニュー">{([{ id: 'setup', icon: SlidersHorizontal, name: 'データと解析設定', index: '01' }, { id: 'spectra', icon: Activity, name: 'スペクトル', index: '02' }, { id: 'pca', icon: ScatterChart, name: '主成分分析', index: '03' }, { id: 'aquagram', icon: Radar, name: 'Aquagram', index: '04' }, { id: 'pls', icon: ScatterChart, name: 'PLS回帰', index: '05' }, { id: 'compare', icon: Settings2, name: '条件間比較', index: '06' }, { id: 'tables', icon: Database, name: '数値表', index: '07' }, { id: 'methods', icon: CircleHelp, name: '解析方式', index: '08' }] as const).map(item => <button key={item.id} className={`nav-item ${view === item.id ? 'active' : ''}`} onClick={() => navigate(item.id)} aria-current={view === item.id ? 'page' : undefined}><item.icon size={18} strokeWidth={1.5} /><span>{item.name}</span><small>{item.index}</small></button>)}</nav>
      <div className="sidebar-data"><div className="nav-caption">DATA SOURCE <Database size={12} /></div>{summary ? <><div className="source-icon"><FileSpreadsheet size={18} /><span title={summary.name}>{summary.name}</span></div><p>{summary.rowCount.toLocaleString()} samples <i /> {summary.wavelengthColumns.length.toLocaleString()} wavelengths</p>{demo && <span className="demo-label dark"><FlaskConical size={11} /> 人工サンプル</span>}<button className="sidebar-link" disabled={disabled} onClick={() => fileInput.current?.click()}>データを変更 <Plus size={13} /></button></> : <><p className="no-source">データが読み込まれていません</p><button className="sidebar-link" disabled={disabled} onClick={() => fileInput.current?.click()}>ファイルを読み込む <Plus size={13} /></button></>}</div>
      <div className="sidebar-bottom"><div className="local-status"><span /> {usesLocalR ? 'AQUAP2 · LOCAL R' : usesPort ? 'AQUAP2PY · BROWSER' : 'PYTHON · BROWSER'}</div><p>{usesLocalR ? <>前処理後のデータを、このPCの<br />Rサービスへ送って解析します。</> : <>測定データはブラウザー内で処理します。<br />Python解析では外部へ送信しません。</>}</p><button onClick={() => setHelp(true)}><CircleHelp size={14} /> このワークベンチについて <ArrowUpRight size={12} /></button><div className="sidebar-version">AQUAPHOTOMICS TOOL <span>v1.6.1</span></div></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb"><button className="mobile-menu icon-button" aria-label="メニューを開く" onClick={() => setMenu(true)}><Menu size={20} /></button><span>WORKSPACE</span><ChevronRight size={12} /><strong>{viewNames[view]}</strong></div><div className="topbar-actions"><span className="local-pill"><span /> {usesLocalR ? 'LOCAL R · AQUAP2' : usesPort ? 'BROWSER · AQUAP2PY' : 'BROWSER · PYTHON'}</span><button className="icon-button help-button" aria-label="使い方と解析方法" onClick={() => setHelp(true)}><CircleHelp size={17} /></button><span className="topbar-separator" /><button className="export-button" onClick={() => void saveZip()} disabled={!result || disabled}><ArrowDownToLine size={15} /><span>{exporting ? '保存中' : '解析を保存'}</span></button><form method="post" action="/auth/logout" className="logout-form"><button type="submit" className="logout-button"><LogOut size={14} /><span>ログアウト</span></button></form></div></header>
      <main id="workspace" className="main-content">
        {(busy || exporting) && <div className="processing-banner" role="status" aria-live="polite"><span className="spinner" /><span>{exporting ? exportStatus : progress?.message ?? '処理しています'}</span>{busy && <button onClick={cancel}><X size={13} /> 中止</button>}</div>}
        {error && <div className="notice error" role="alert"><span>{error}</span><button aria-label="エラーを閉じる" onClick={() => setError('')}><X size={15} /></button></div>}
        {notice && <div className="notice success" role="status"><Check size={15} /><span>{notice}</span><button aria-label="通知を閉じる" onClick={() => setNotice('')}><X size={15} /></button></div>}
        {view === 'methods' ? <MethodPanel selectedMode={config?.pipelineMode ?? 'modern'} selectedEngine={config ? config.analysisEngine ?? 'python' : 'aquap2py'} health={aquap2Health} execution={result?.metadata.execution} compatibilityReport={result?.metadata.compatibilityReport} onConfigure={() => navigate('setup')} legacyVerified /> : view === 'compare' ? <>
          <div className="page-heading"><div><div className="eyebrow">ANALYSIS COMPARISON</div><h1>解析条件の比較</h1><p>同じデータで実行した条件を最大4件保持し、結果を比較します。データの再読込・ページ更新で保持内容は消えます。</p></div><button className="button outline" disabled={disabled} onClick={()=>navigate('setup')}><SlidersHorizontal size={14}/>解析設定</button></div>
          <section className="glass-panel comparison-actions"><label className="field"><span>比較に追加する条件名</span><input value={runName} maxLength={80} onChange={e=>setRunName(e.target.value)} disabled={disabled}/></label><button className="button primary" disabled={disabled || !result || stale || runs.length>=4} onClick={retainRun}><Plus size={15}/>直前の解析を追加</button><button className="button outline" disabled={disabled || !runs.length} onClick={()=>void saveComparison()}><ArrowDownToLine size={15}/>比較結果を保存</button>{!result && <p>先にデータを読み込み、解析を実行してください。</p>}{stale && <p>未適用の設定があります。再解析後に比較へ追加できます。</p>}</section>
          <ComparisonPanel runs={runs} onRemove={id=>setRuns(old=>old.filter(run=>run.id!==id))} onClear={()=>setRuns([])} onRestore={restoreRun} disabled={disabled}/>
        </> : view === 'tables' ? <>
          <div className="page-heading"><div><div className="eyebrow">NUMERICAL RESULTS</div><h1>解析結果の数値表</h1><p>保存される数値表を確認し、必要なCSVを個別に取得できます。</p></div><button className="button outline" onClick={() => navigate('setup')}><SlidersHorizontal size={14} />解析設定</button></div>
          {!result || !activeTable ? <section className="empty-results glass-panel"><Database size={34} strokeWidth={1.2} /><h2>解析結果がありません</h2><p>データを読み込み、解析を実行すると数値表を表示できます。</p><button className="button primary" onClick={() => navigate('setup')}>解析設定へ<ArrowRight size={15} /></button></section> : <>
            <ExecutionSummary result={result} /><div className="result-table-context"><span title={resultName}>{resultName}{demo ? ' · 人工サンプル' : ''}</span><button className="result-method-pill" onClick={() => navigate('methods')}>{resultEngineName(result)} · {modeName(result.metadata.settings)}<ArrowUpRight size={10} /></button></div>
            <ExecutionSummary result={result} />
          {stale && <div className="notice stale"><RefreshCw size={15} /><span>未適用の設定があります。数値表とCSVは、直前に完了した解析結果です。</span><button disabled={disabled || !engineReady} onClick={() => void analyze()}>再解析<ArrowRight size={13} /></button></div>}
            <section className="glass-panel result-table-panel"><div className="result-table-toolbar"><label className="field"><span>表示する結果表</span><select value={activeTable.id} onChange={event => setTableId(event.target.value)}>{resultTables.map(table => <option value={table.id} key={table.id}>{table.title}</option>)}</select></label><button className="button outline" disabled={disabled} onClick={() => { try { exportCsv(result, activeTable.exportPath); setNotice(`${activeTable.title}の全行・全列をCSVに保存しました。`); setError(''); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); } }}><ArrowDownToLine size={14} />この表をCSVで保存</button></div>
            <div className="result-table-info"><span>保存CSVと同じ値を表示します。{activeTable.columns.length > 20 ? `表示は先頭20列に限定しています（全${activeTable.columns.length}列）。CSVには全列を含みます。` : '横にスクロールして各列を確認できます。'}</span><span>{activeTable.rows.length.toLocaleString()} rows × {activeTable.columns.length.toLocaleString()} columns</span></div>
            {activeTable.rows.length ? <div className="result-table-scroll"><table><thead><tr><th scope="col">行</th>{visibleTableColumns.map((column, index) => <th key={`${column}-${index}`} scope="col" title={column}>{column}</th>)}</tr></thead><tbody>{activeTable.rows.slice(tableStart, tableStart + 50).map((row, index) => <tr key={tableStart + index}><th scope="row">{tableStart + index + 1}</th>{visibleTableColumns.map((_, column) => <td key={column} title={String(row[column] ?? '')} className={typeof row[column] === 'number' || typeof row[column] === 'string' && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(row[column] as string) ? 'numeric' : undefined}>{row[column] === null || row[column] === undefined || row[column] === '' ? '—' : String(row[column])}</td>)}</tr>)}</tbody></table></div> : <p className="result-table-empty">この表にデータ行はありません。</p>}
            <div className="result-table-pagination"><span>{activeTable.rows.length ? `${tableStart + 1}–${Math.min(tableStart + 50, activeTable.rows.length)} / ${activeTable.rows.length} 行` : '0 行'}<span> · 1ページ50行</span></span><div><button disabled={currentTablePage === 0} onClick={() => setTablePage(page => Math.max(0, page - 1))}>前のページ</button><span>{currentTablePage + 1} / {tablePages}</span><button disabled={currentTablePage >= tablePages - 1} onClick={() => setTablePage(page => Math.min(tablePages - 1, page + 1))}>次のページ</button></div></div></section>
          </>}
        </> : view === 'setup' ? <>
          {!summary && <section className="hero"><div className="hero-copy"><div className="eyebrow"><span /> AQUAPHOTOMICS ANALYSIS WORKBENCH</div><h1>アクアフォトミクス<br />解析ワークベンチ</h1><p>近赤外スペクトルの前処理、PCA・PLS回帰、<br />Aquagramと解析条件の比較・保存に対応しています。</p><div className="hero-foot"><span>PREPROCESSING</span><i /><span>PCA</span><i /><span>AQUAGRAM</span></div></div><div className="water-art" aria-hidden="true"><div className="water-disc"><span /><span /><span /><span /><span /></div><div className="water-coordinate coordinate-top">H₂O — NIR SPECTROSCOPY</div><div className="water-coordinate coordinate-bottom">SPECTRAL ANALYSIS / RESEARCH WORKSPACE</div></div></section>}
          <div className="page-heading"><div><div className="eyebrow">{summary ? 'ANALYSIS CONFIGURATION' : 'DATA IMPORT'}</div><h1>{summary ? 'データと解析設定' : '解析データの読み込み'}</h1><p>{summary ? '解析対象の列、波長範囲、前処理および解析条件を設定します。' : 'CSVまたはExcelファイルを読み込んで、解析条件を設定してください。'}</p></div>{summary && <button className="button outline" disabled={disabled} onClick={() => { const initial = defaults(summary); setConfig(initial); setWaterText(initial.aquagramWavelengths.join(', ')); }}><RefreshCw size={14} /> 設定をリセット</button>}</div>
          {!summary ? <section className={`upload-panel glass-panel ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); if (!disabled) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); if (!disabled) chooseFile(e.dataTransfer.files?.[0]); }}><div className="upload-symbol"><Upload size={25} strokeWidth={1.3} /></div><div className="upload-copy"><h2>解析データをドラッグ＆ドロップ</h2><p>CSV / Excel（.xlsx, .xls）<span>試料 × 波長の表形式</span></p></div><button className="button primary" disabled={disabled} onClick={() => fileInput.current?.click()}>ファイルを選択 <ArrowUpRight size={15} /></button><div className="upload-divider" /><button className="demo-start" disabled={disabled} onClick={() => void load({ kind: 'demo' })}><FlaskConical size={19} strokeWidth={1.3} /><span>サンプルで試す<small>動作確認用の人工スペクトル</small></span><ArrowRight size={16} /></button></section> : config && <>
            <section className="dataset-bar glass-panel"><div className="dataset-file"><div className="dataset-file-icon"><FileSpreadsheet size={23} strokeWidth={1.3} /></div><div><strong title={summary.name}>{summary.name}</strong><p>{summary.rowCount.toLocaleString()} 試料<span>×</span>{summary.wavelengthColumns.length.toLocaleString()} 波長列 {demo && <span className="demo-label"><FlaskConical size={11} /> 人工サンプル</span>}</p></div></div><button className="button subtle" disabled={disabled} onClick={() => fileInput.current?.click()}>別のファイル <Upload size={14} /></button></section>
            {demo && <div className="demo-note"><FlaskConical size={14} /> このデータは動作確認用の人工サンプルです。実測データや研究上の結論を示すものではありません。</div>}
            {!!summary.importNotes?.length && <div className="notice" role="status"><FileSpreadsheet size={15}/><span>{summary.importNotes.join(' ')}</span></div>}
            <section className="settings-actions glass-panel"><div><strong>解析設定の保存・再読込</strong><p>設定JSONを保存し、同じ列構成のデータに再適用できます。測定データは含みません。</p></div><div><button className="button outline" disabled={disabled} onClick={saveSettings}><ArrowDownToLine size={14}/>設定を保存</button><button className="button outline" disabled={disabled} onClick={()=>settingsInput.current?.click()}><Upload size={14}/>設定を読み込む</button></div></section>
            <EngineSelector engine={config.analysisEngine ?? 'python'} health={aquap2Health} connecting={connecting} error={connectionError} endpoint={aquap2Endpoint} onChange={engine => update('analysisEngine', engine)} onConnect={() => void connectAquap2()} onDisconnect={disconnectAquap2} onDetails={() => navigate('methods')} disabled={!!busy || exporting} /><PipelineSelector engine={config.analysisEngine ?? 'python'} mode={config.pipelineMode ?? 'modern'} onChange={mode => update('pipelineMode', mode)} onDetails={() => navigate('methods')} disabled={disabled} /><fieldset disabled={disabled} className="config-fieldset"><section className="glass-panel settings-panel"><SectionTitle index="01" title="データの構成" caption="試料情報と、解析する波長列を指定します。" /><div className="data-settings"><div className="form-grid">{summary.sheets.length > 0 && <Field label="Excelシート" wide><select value={summary.sheet ?? ''} onChange={e => { if (source.current?.kind === 'file') void load({ ...source.current, sheet: e.target.value }); }}>{summary.sheets.map(sheet => <option key={sheet}>{sheet}</option>)}</select></Field>}<Field label="試料IDの列" hint="指定しない場合は行番号を使用"><select value={config.idColumn ?? ''} onChange={e => update('idColumn', e.target.value || null)}><option value="">行番号を使用</option>{summary.columns.map(col => <option key={col}>{col}</option>)}</select></Field><Field label="グループの列" hint="グラフとAquagramの群分けに使用"><select value={config.groupColumn ?? ''} onChange={e => update('groupColumn', e.target.value || null)}><option value="">グループなし</option>{summary.columns.map(col => <option key={col}>{col}</option>)}</select></Field></div><div className="wave-columns"><div><strong>波長列</strong><span>{config.wavelengthColumns.length} / {summary.wavelengthColumns.length} 列を選択</span></div><p>列名から波長を検出しました。単位は nm として扱います。</p><details><summary>解析する列を確認・変更 <ChevronRight size={13} /></summary><div className="column-actions"><button type="button" onClick={() => update('wavelengthColumns', summary.wavelengthColumns.map(x => x.column))}>すべて選択</button><button type="button" onClick={() => update('wavelengthColumns', [])}>解除</button></div><div className="column-list">{summary.wavelengthColumns.map(col => <label key={col.column}><input type="checkbox" checked={config.wavelengthColumns.includes(col.column)} onChange={e => update('wavelengthColumns', e.target.checked ? [...config.wavelengthColumns, col.column] : config.wavelengthColumns.filter(x => x !== col.column))} />{col.column}<small>{col.wavelength} nm</small></label>)}</div></details></div></div><details className="data-preview"><summary>データプレビュー <span>先頭 {Math.min(5, summary.preview.length)} 行・{Math.min(10, summary.columns.length)} 列</span><ChevronRight size={14} /></summary><div className="preview-table-wrap"><table><thead><tr>{summary.columns.slice(0, 10).map(col => <th key={col}>{col}</th>)}</tr></thead><tbody>{summary.preview.slice(0, 5).map((row, i) => <tr key={i}>{row.slice(0, 10).map((value, j) => <td key={j}>{fmt(value)}</td>)}</tr>)}</tbody></table></div></details></section>
            <div className="analysis-settings-grid"><section className="glass-panel settings-panel"><SectionTitle index="02" title="スペクトルの前処理" caption={config.pipelineMode === 'legacy-python' ? '欠損処理 → SG処理 → 散乱補正の順に適用します。' : '欠損処理 → 散乱補正 → SG処理の順に適用します。'} /><div className="field-range"><label>解析する波長範囲 <small>nm</small></label><div><input aria-label="波長範囲の下限" type="number" step="any" value={config.range[0]} onChange={e => update('range', [Number(e.target.value), config.range[1]])} /><span>—</span><input aria-label="波長範囲の上限" type="number" step="any" value={config.range[1]} onChange={e => update('range', [config.range[0], Number(e.target.value)])} /></div></div><div className="form-grid"><Field label="欠損値"><select value={config.missing} onChange={e => update('missing', e.target.value as AnalysisConfig['missing'])}><option value="error">欠損があれば解析を停止</option><option value="median">波長列ごとの中央値で補完</option><option value="mean">波長列ごとの平均値で補完</option></select></Field><Field label="散乱補正"><select value={config.scatter} onChange={e => update('scatter', e.target.value as AnalysisConfig['scatter'])}><option value="none">補正なし</option><option value="snv">SNV · 標準正規変量</option><option value="msc">MSC · 乗算散乱補正</option></select></Field></div><div className="setting-divider" /><label className="toggle-row"><span><strong>Savitzky–Golay 平滑化</strong><small>局所多項式でスペクトルを平滑化</small></span><input type="checkbox" role="switch" checked={config.smooth} onChange={e => update('smooth', e.target.checked)} /><i /></label><div className="form-grid triple"><Field label="ウィンドウ幅" hint="奇数の点数"><input type="number" min={3} step={2} value={config.window} disabled={!config.smooth && config.derivative === 0} onChange={e => update('window', Number(e.target.value))} /></Field><Field label="多項式次数"><input type="number" min={1} max={6} value={config.polyorder} disabled={!config.smooth && config.derivative === 0} onChange={e => update('polyorder', Number(e.target.value))} /></Field><Field label="微分"><select value={config.derivative} onChange={e => update('derivative', Number(e.target.value) as 0 | 1 | 2)}><option value={0}>微分なし</option><option value={1}>1 次微分</option><option value={2}>2 次微分</option></select></Field></div><p className="field-note">{usesPort ? 'aquap2pyのSGは列の位置（間隔1）で計算し、不等間隔でも波長を補間しません。SNVは試料内の標本SD（n−1）、MSCは入力行列の平均スペクトルを使用します。' : config.pipelineMode === 'legacy-python' ? '旧Python互換では波長を補間せず、波長間隔の中央値を使ってSG処理します。' : '不等間隔の波長は、SG処理前に等間隔へ線形補間します。'}</p></section>
            <section className="glass-panel settings-panel"><SectionTitle index="03" title="PCA・Aquagram" caption="前処理後のデータを、2つの視点で探索します。" /><div className="pca-config"><div className="form-grid"><Field label="PCAの主成分数"><input type="number" min={1} max={Math.min(usesLocalR || usesPort ? 10 : 20, summary.rowCount - 1, config.wavelengthColumns.length)} value={config.components} onChange={e => update('components', Number(e.target.value))} /></Field><div className="pca-scale"><label><input type="checkbox" checked={config.pcaScale} onChange={e => update('pcaScale', e.target.checked)} /><span>波長ごとに標準化<small>平均中心化は常に適用</small></span></label></div></div></div><div className="setting-divider" />{usesPort && config.nativeAquagram?.enabled && <p className="field-note">温度校正を使用中です。以下の波長はsfcで使います。AUC系は専用設定の帯域座標を使い、基準群も専用設定を適用します。</p>}<Field label="Aquagramの波長 / nm" hint="数値をカンマ区切りで指定。3点以上。"><textarea rows={2} value={waterText} onChange={e => { setWaterText(e.target.value); update('aquagramWavelengths', parseWaves(e.target.value).waves); }} aria-invalid={!parsedWater.valid} /></Field><div className="form-grid aquagram-config"><Field label="Aquagramの基準"><select value={aquagramIsMean(config) ? 'none' : config.aquagramReference === 'global' ? 'global' : 'group'} onChange={e => update('aquagramReference', e.target.value === 'group' ? `group:${groups[0] ?? ''}` : e.target.value)}><option value="global">全体平均との差を標準化</option><option value="group">対照群平均との差を標準化</option><option value="none">基準なし（群平均値）</option></select></Field><Field label="波長の許容誤差 / nm"><input type="number" min={0} step="0.1" value={config.aquagramTolerance} onChange={e => update('aquagramTolerance', Number(e.target.value))} /></Field>{!aquagramIsMean(config) && config.aquagramReference !== 'global' && <Field label="対照群の名前" hint="グラフの群分けで指定した列の値を入力" wide><input list="reference-groups" placeholder="対照群名を入力" value={config.aquagramReference.replace(/^group:/, '')} onChange={e => update('aquagramReference', `group:${e.target.value}`)} /><datalist id="reference-groups">{groups.map(group => <option key={group} value={group} />)}</datalist></Field>}</div><p className="field-note">{aquagramIsMean(config) ? '基準差と標準偏差による標準化を行わず、前処理後の群平均値を表示します。' : usesLocalR || usesPort ? 'classicは標本標準偏差で標準化します。対照群を選ぶとclassic-diffを使用します。' : '群平均との差を全試料の母標準偏差で割った値を表示します。'} 波長から分子種を自動判定しません。</p></section></div>{usesPort&&<NativeAquagramSettings value={config.nativeAquagram??nativeAquagramDefaults()} onChange={value=>update('nativeAquagram',value)} disabled={disabled} calibration={calibrationSummary} onCalibrationFile={file=>void loadCalibration(file)} onCalibrationSheet={sheet=>{if(calibrationSource.current)void loadCalibration(calibrationSource.current.file,sheet);}} groups={groups}/ >}{(!usesPort||config.pls?.enabled)&&<PLSSettings summary={summary} config={config} onChange={value=>update('pls',value)} disabled={disabled}/ >}{usesPort&&<NativePLSRSettings value={config.nativePlsr??nativePlsrDefaults(summary)} onChange={value=>update('nativePlsr',value)} disabled={disabled} summary={summary}/ >}</fieldset>
            <>{(restrictions.length > 0 || usesLocalR && !aquap2Health) && <div className="engine-run-blockers" role="status"><strong>{usesPort ? 'aquap2py' : 'aquap2本体'}で実行する前に確認してください</strong><ul>{usesLocalR && !aquap2Health && <li>同じPCのRサービスとの接続を確認してください。</li>}{restrictions.map(reason => <li key={reason}>{reason}</li>)}</ul></div>}<div className="run-panel"><div><span className="ready-dot" /><strong>{engineReady ? '解析の準備ができました' : usesLocalR ? '接続・解析設定の確認が必要です' : '解析設定の確認が必要です'}</strong><p>{config.range[0]}–{config.range[1]} nm <span>·</span> {processing}</p>{usesPort && <p>aquap2py 0.2.0 · ブラウザー内で計算／R不要 · aquap2の部分移植</p>}{usesLocalR && <p>前処理 Python／PCA・Aquagram aquap2 <span>·</span> 実行時にこのPCのRへデータ送信</p>}</div><button className="button primary run-button" disabled={disabled || !engineReady || config.wavelengthColumns.length < 3 || !parsedWater.valid} onClick={() => void analyze()}><Play size={14} fill="currentColor" /> {usesLocalR ? 'R本体で参照解析' : usesPort ? 'aquap2pyで解析を実行' : result ? '設定を適用して再解析' : '解析を実行'}<ArrowRight size={17} /></button></div></>
          </>}
          {!summary && <div className="initial-notes"><div><ShieldCheck size={17} strokeWidth={1.3} /><span>解析エンジンを選択<small>aquap2pyはブラウザー内で実行・R不要。</small></span></div><div><Settings2 size={17} strokeWidth={1.3} /><span>適用設定と解析結果を保存<small>適用設定と結果をまとめて保存。</small></span></div><div><Activity size={17} strokeWidth={1.3} /><span>前処理・多変量解析に対応<small>スペクトル・PCA・Aquagramを表示。</small></span></div></div>}
        </> : !result || !figures ? <section className="empty-results glass-panel"><div className="empty-visual"><Waves size={42} strokeWidth={1.1} /></div><span className="eyebrow">ANALYSIS NOT RUN</span><h1>{viewNames[view]}の解析結果</h1><p>{summary ? 'データと解析条件を確認して、解析を実行してください。' : '測定データを読み込むか、人工サンプルで操作を試してください。'}</p><button className="button primary" disabled={disabled} onClick={() => navigate('setup')}>{summary ? '解析設定へ' : 'データを読み込む'}<ArrowRight size={16} /></button></section> : <>
          <div className="page-heading result-heading"><div><div className="eyebrow">{view === 'spectra' ? 'SPECTRAL ANALYSIS' : view === 'pca' ? 'PRINCIPAL COMPONENT ANALYSIS' : view === 'pls' ? 'PARTIAL LEAST SQUARES REGRESSION' : 'WATER SPECTRAL PATTERN'}</div><h1>{view === 'pca' ? '主成分分析（PCA）' : view === 'aquagram' ? 'Aquagram' : view === 'pls' ? 'PLS回帰と交差検証' : 'スペクトルの表示'}</h1><p>{view === 'spectra' ? '元データと前処理後のスペクトルを比較できます。' : view === 'pca' ? '主成分スコア、ローディング、寄与率を確認できます。' : view === 'pls' ? result.nativePlsr ? 'aquap2方式の成分選択・交差検証です。成分選択から独立した外側CVによる性能評価ではありません。' : '数値の目的変数を予測し、外側CVの予測性能を確認します。' : isTemperatureAquagram(result) ? aquagramValueLabel(result) : aquagramIsMean(result.metadata.settings) ? '前処理後の群平均値を比較します。' : '指定波長における標準化した群平均差を比較します。'}</p></div><button className="button outline" onClick={() => navigate('setup')}><SlidersHorizontal size={14} /> 解析設定</button></div>
          <div className="result-context"><div><span className="source-indicator" /><span title={resultName}>{resultName}</span>{demo && <span className="demo-label"><FlaskConical size={11} /> 人工サンプル</span>}<button className="result-method-pill" onClick={() => navigate('methods')}>{resultEngineName(result)} · {modeName(result.metadata.settings)}<ArrowUpRight size={10} /></button></div><span>{result.metadata.samples} 試料 <i /> {result.metadata.variables} 波長 <i /> {result.metadata.range[0]}–{result.metadata.range[1]} nm</span></div>
          <ExecutionSummary result={result} />
          {stale && <div className="notice stale"><RefreshCw size={15} /><span>設定が変更されています。表示と保存は、直前に完了した解析結果です。</span><button disabled={disabled || !engineReady} onClick={() => void analyze()}>再解析 <ArrowRight size={13} /></button></div>}
          {result.metadata.warnings.length > 0 && <details className="warnings"><summary>解析時の確認事項 <span>{result.metadata.warnings.length}</span><ChevronRight size={13} /></summary><ul>{result.metadata.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details>}
          {view === 'pls' ? result.nativePlsr ? <NativePLSRResults result={result.nativePlsr} wavelengths={result.spectra.wavelengths}/> : result.pls ? <><PLSResults result={result.pls} onSelect={id=>setSelected(id)}/>{selected && <section className="glass-panel comparison-actions"><strong>選択試料：{selected}</strong><button className="button outline" onClick={()=>navigate('spectra')}>スペクトルで確認<ArrowUpRight size={14}/></button><button className="button subtle" onClick={()=>setSelected(null)}>選択を解除</button></section>}</> : <section className="empty-results glass-panel"><h2>PLS回帰は実行されていません</h2><p>解析設定でPLS回帰を有効にし、数値の目的変数列と交差検証条件を指定してください。</p><button className="button primary" disabled={disabled} onClick={()=>navigate('setup')}>PLSの解析設定へ<ArrowRight size={15}/></button></section> : <>
          <section className="chart-panel glass-panel"><div className="chart-toolbar"><div className="segmented" aria-label="表示を切り替え">{view === 'spectra' ? <><button aria-pressed={spectrumMode === 'processed'} onClick={() => setSpectrumMode('processed')}>前処理後</button><button aria-pressed={spectrumMode === 'raw'} onClick={() => setSpectrumMode('raw')}>元のスペクトル</button></> : view === 'pca' ? <><button aria-pressed={pcaMode === 'scores'} onClick={() => setPcaMode('scores')}>スコア</button><button aria-pressed={pcaMode === 'loadings'} onClick={() => setPcaMode('loadings')}>ローディング</button><button aria-pressed={pcaMode === 'variance'} onClick={() => setPcaMode('variance')}>寄与率</button></> : <span className="chart-type-label"><Radar size={16} /> {aquagramValueLabel(result)}</span>}</div><div className="chart-toolbar-end">{view === 'pca' && pcaMode === 'scores' && <div className="axis-controls"><label>X<select value={axisX} onChange={e => setAxisX(Number(e.target.value))}>{result.pca.explainedVariance.map((_, i) => <option value={i} key={i}>PC{i + 1}</option>)}</select></label>{result.pca.explainedVariance.length > 1 && <label>Y<select value={axisY} onChange={e => setAxisY(Number(e.target.value))}>{result.pca.explainedVariance.map((_, i) => <option value={i} key={i}>PC{i + 1}</option>)}</select></label>}</div>}{view === 'spectra' && <span className="processing-label" title={spectrumMode === 'processed' ? resultProcessing : 'RAW DATA'}>{spectrumMode === 'processed' ? resultProcessing : 'RAW DATA'}</span>}<button className="icon-button" aria-label="グラフの操作方法" onClick={() => setHelp(true)}><CircleHelp size={16} /></button></div></div>
            <Plot figure={view === 'spectra' ? figures[spectrumMode] : view === 'pca' ? figures[pcaMode] : figures.aquagram} label={`${viewNames[view]}グラフ`} onSelect={view === 'aquagram' || view === 'pca' && pcaMode !== 'scores' ? undefined : id => setSelected(old => old === id ? null : id)} />
            <div className="chart-footer">{view === 'aquagram' ? <span>基準：{result.aquagram.reference} <i /> {result.aquagram.coordinateRanges ? '帯域座標で表示' : '適用した実波長で表示'}</span> : <span><MousePointer2 size={12} /> {view === 'pca' && pcaMode !== 'scores' ? 'ドラッグで拡大。ダブルクリックで表示をリセット。' : '線や点をクリックして試料を選択。スペクトルとPCAに連動します。'}</span>}<span>{view === 'spectra' && result.metadata.samples > 200 ? '最大200試料を表示・選択試料を追加' : 'スクロールでズーム'}</span></div>
          </section>
          {view !== 'aquagram' && <div className="result-bottom-grid"><section className="selection-panel glass-panel"><div className="panel-caption">SELECTED SAMPLE</div>{selected ? <><div className="selected-sample"><div><h3>{selected}</h3><p>グループ：{selectedGroup}</p></div><button className="icon-button" aria-label="試料の選択を解除" onClick={() => setSelected(null)}><X size={15} /></button></div><button className="text-link" onClick={() => navigate(view === 'spectra' ? 'pca' : 'spectra')}>{view === 'spectra' ? 'PCAでこの試料を見る' : 'この試料のスペクトルを見る'}<ArrowUpRight size={13} /></button></> : <><h3>試料を選択してください</h3><p>グラフ上の線・点、または試料IDから選択できます。</p></>}<select className="sample-select" aria-label="表示する試料を選ぶ" value={selected ?? ''} onChange={e => setSelected(e.target.value || null)}><option value="">試料IDから選択</option>{result.spectra.ids.map((id, i) => <option key={`${id}-${i}`} value={id}>{id}</option>)}</select></section><section className="insight-panel glass-panel"><div className="panel-caption">{view === 'spectra' ? 'PROCESSING SUMMARY' : 'EXPLAINED VARIANCE'}</div>{view === 'spectra' ? <><div className="method-result-order"><span>{missingLabel(result.metadata.settings)}</span>{preprocessingStages(result.metadata.settings).map((stage, index) => <span key={index}>→ {stage}</span>)}</div><p>{modeName(result.metadata.settings)}で実際に適用された処理順です。<button className="text-link" onClick={() => navigate('tables')}>前処理後の数値表<ArrowUpRight size={12} /></button></p></> : <><div className="variance-metrics"><div><span>PC1</span><strong>{pct(result.pca.explainedVariance[0] ?? 0)}</strong></div><div><span>{result.pca.explainedVariance.length > 1 ? 'PC1 + PC2' : '累積寄与率'}</span><strong>{pct(result.pca.explainedVariance.slice(0, 2).reduce((a, b) => a + b, 0))}</strong></div><div><span>算出した成分</span><strong>{result.pca.explainedVariance.length}<small> components</small></strong></div></div><p>平均中心化{result.metadata.settings.pcaScale ? ' ＋ 波長ごとの標準化' : '・波長ごとの標準化なし'}。寄与率は全分散に対する割合です。</p></>}</section></div>}
          {view === 'aquagram' && <div className="aquagram-method glass-panel"><div><div className="panel-caption">CALCULATION METHOD</div><h3>{isTemperatureAquagram(result) ? aquagramValueLabel(result) : aquagramIsMean(result.metadata.settings) ? '群平均値の表示' : '標準化差の計算方法'}</h3></div><p>{result.aquagram.definition}<br />{isTemperatureAquagram(result) ? '単位と校正条件は保存された来歴を確認してください。' : aquagramIsMean(result.metadata.settings) ? '表示値は前処理後の群平均で、基準差・標準偏差による標準化を含みません。' : '0は選択した基準と同じ平均値を表します。'} この図だけから水の分子種や試料の優劣を断定しません。</p></div>}
          </>}
        </>}
        <footer className="workspace-footer"><span>AQUAPHOTOMICS WORKBENCH · v1.6.1</span><span>PREPROCESSING / PCA / PLS / AQUAGRAM</span></footer>
      </main>
    </div>
    {help && <div className="modal-backdrop" onClick={() => setHelp(false)}><section className="help-modal glass-panel" role="dialog" aria-modal="true" aria-labelledby="help-title" onClick={e => e.stopPropagation()}><button className="modal-close icon-button" aria-label="説明を閉じる" onClick={() => setHelp(false)}><X size={19} /></button><Waves size={30} strokeWidth={1.2} /><div className="eyebrow">AQUAPHOTOMICS WORKBENCH</div><h2 id="help-title">データの準備と、解析の読み方</h2><ol><li><strong>表を読み込む</strong><p>1行が1試料、波長名の列が測定値です。CSVはUTF-8、Excelはシートを選択できます。列名は1300、1300nmなど、波長を示す形式にしてください。</p></li><li><strong>解析方式を確認する</strong><p>aquap2pyはaquap2の部分移植をブラウザー内で実行し、Rを必要としません。Workbench標準Pythonと、任意のR本体参照実行も選べます。「解析方式」画面で機能ごとの実装・数値検証・未対応を確認してください。</p></li><li><strong>前処理と解析条件を設定</strong><p>ID・グループを指定し、欠損処理、散乱補正、SG処理を確認します。PCAは平均中心化を行い、波長ごとの標準化は選択できます。</p></li><li><strong>解析結果を確認する</strong><p>グラフをドラッグして拡大、ダブルクリックでリセット。線やスコア点をクリックすると同じ試料を連動表示します。Aquagramは全体・対照群との差を標準化する方式と、群平均値をそのまま示す方式（Workbench標準Pythonのみ）を選択できます。</p></li><li><strong>PLS回帰と条件間比較</strong><p>PLS回帰にはWorkbench標準Pythonを選び、PLSを有効にして数値の目的変数列を指定します。aquap2pyにはaquap2方式PLSRの専用設定があります。R参照実行ではPLSを実行しません。反復測定がある場合はCV群に個体・試料の列を指定してください。予測性能は外側OOFの指標で確認します。条件間比較に解析結果を追加し、設定を変えて再解析すると比較できます。</p></li><li><strong>解析を保存する</strong><p>元ファイル、前処理後CSV、PCA、Aquagram、適用設定、PNGをZIPに保存します。PLSを有効にした場合はOOF予測・成分選択曲線・係数も保存します。「数値表」から結果表の閲覧とCSVの個別保存ができます。設定JSONだけの保存・再読込にも対応します。条件間比較には解析後の結果を追加してください。設定変更後も、再解析するまでは直前の結果が表示・保存されます。</p></li></ol><div className="help-privacy"><ShieldCheck size={17} /><p>aquap2pyとWorkbench標準Pythonは測定データをブラウザー内で処理します。任意の「aquap2本体：R参照実行」を選んだ場合だけ、前処理後の測定行列・波長・試料ID・群名を、このPCのRサービス（127.0.0.1:8787）へ送ります。初回はPython実行環境と解析ライブラリの取得にインターネット接続が必要です。大きなデータの処理速度・メモリ使用量は端末に依存します。</p></div><button className="button primary" onClick={() => setHelp(false)}>ワークスペースに戻る <ArrowRight size={15} /></button></section></div>}
  </div>;
}
