import type { AnalysisResult, DatasetSummary, Progress, ExperimentImport, ExperimentResult, UnitySummary, PaperLoading } from './types';
import type { WorkerRequest, WorkerResponse } from './client';

interface PyodideRuntime {
  globals: { set(name: string, value: unknown): void; has(name: string): boolean; delete(name: string): void };
  FS: { writeFile(path: string, data: string | Uint8Array, options?: { encoding: 'utf8' }): void };
  loadPackage(names: string[]): Promise<void>;
  runPythonAsync(code: string): Promise<unknown>;
}

interface WorkerScope {
  onmessage: ((event: MessageEvent<WorkerRequest>) => void) | null;
  postMessage(message: WorkerResponse): void;
  location: Location;
}

const scope = globalThis as unknown as WorkerScope;
const PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
let runtimePromise: Promise<PyodideRuntime> | null = null;
let activeRequest: number | null = null;
let excelReady = false;
const loadedPackages = new Set<string>();

function progress(id: number, phase: string, message: string): void {
  const value: Progress = { phase, message };
  scope.postMessage({ id, kind: 'progress', progress: value });
}

function detailOf(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  // PythonError includes a full traceback. Its final line contains the useful reason.
  return (message.split('\n').map(line => line.trim()).filter(Boolean).at(-1) || '原因を特定できませんでした。').slice(0, 700);
}

function clearGlobals(pyodide: PyodideRuntime, names: string[]): void {
  names.forEach(name => {
    if (pyodide.globals.has(name)) pyodide.globals.delete(name);
  });
}

async function ensurePackages(pyodide: PyodideRuntime, names: string[], id: number): Promise<void> {
  const missing = names.filter(name => !loadedPackages.has(name));
  if (!missing.length) return;
  progress(id, 'packages', `解析ライブラリを準備しています（${missing.join('、')}）。初回は時間がかかります。`);
  try {
    await pyodide.loadPackage(missing);
  } catch (error) {
    throw new Error(`解析ライブラリを読み込めませんでした。通信状態を確認してください。${detailOf(error)}`);
  }
  missing.forEach(name => loadedPackages.add(name));
}

async function ensureXlsx(pyodide: PyodideRuntime, pythonUrl: string, id: number): Promise<void> {
  if (excelReady) return;
  await ensurePackages(pyodide, ['micropip'], id);
  progress(id, 'excel', 'Excel（.xlsx）の読み込みライブラリを準備しています。');
  // openpyxl is not bundled with Pyodide 314.0.7. Pinned pure-Python wheels
  // are shipped with this app instead of resolving dependencies from PyPI.
  const wheelBase = new URL('../wheels/', pythonUrl);
  if (wheelBase.origin !== scope.location.origin) throw new Error('Excelライブラリの取得先が不正です。');
  const wheels = [
    new URL('et_xmlfile-2.0.0-py3-none-any.whl', wheelBase).href,
    new URL('openpyxl-3.1.5-py2.py3-none-any.whl', wheelBase).href,
  ];
  pyodide.globals.set('_excel_wheels_json', JSON.stringify(wheels));
  try {
    await pyodide.runPythonAsync(`
import micropip as _micropip
for _excel_wheel in _json.loads(_excel_wheels_json):
    await _micropip.install(_excel_wheel, deps=False)
`);
    excelReady = true;
  } catch (error) {
    throw new Error(`Excel（.xlsx）の読み込みライブラリを準備できませんでした。通信状態を確認して再度お試しください。${detailOf(error)}`);
  } finally {
    clearGlobals(pyodide, ['_excel_wheels_json', '_excel_wheel']);
  }
}

async function initialize(pythonUrl: string, id: number): Promise<PyodideRuntime> {
  if (!runtimePromise) {
    runtimePromise = (async () => {
      progress(id, 'runtime', 'Python実行環境を準備しています。初回は時間がかかります。');
      const moduleUrl = `${PYODIDE_URL}pyodide.mjs`;
      let pyodide: PyodideRuntime;
      try {
        const { loadPyodide } = await import(/* @vite-ignore */ moduleUrl) as {
          loadPyodide(options: { indexURL: string }): Promise<PyodideRuntime>;
        };
        pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
      } catch (error) {
        throw new Error(`Python実行環境を読み込めませんでした。通信状態を確認してください。${detailOf(error)}`);
      }
      await ensurePackages(pyodide, ['numpy', 'pandas'], id);
      progress(id, 'source', 'アクアフォトミクス解析処理を準備しています。');
      const sourceUrl = new URL(pythonUrl, scope.location.href);
      if (sourceUrl.origin !== scope.location.origin) throw new Error('解析プログラムの取得先が不正です。');
      const response = await fetch(sourceUrl, { cache: 'no-cache' });
      if (!response.ok) throw new Error(`解析プログラムを取得できませんでした（HTTP ${response.status}）。ページを再読み込みしてください。`);
      const source = await response.text();
      if (!source.includes('def inspect_bytes(') || !source.includes('def analyze(')) {
        throw new Error('解析プログラムの内容を確認できませんでした。ページを再読み込みしてください。');
      }
      pyodide.FS.writeFile('/home/pyodide/workbench.py', source, { encoding: 'utf8' });
      const experimentResponse = await fetch(new URL('experiment.py', sourceUrl), {cache:'no-cache'});
      if (!experimentResponse.ok) throw new Error(`実験データの解析処理を取得できませんでした（HTTP ${experimentResponse.status}）。`);
      pyodide.FS.writeFile('/home/pyodide/experiment.py',await experimentResponse.text(),{encoding:'utf8'});
      const paperResponse = await fetch(new URL('paper.py', sourceUrl), {cache:'no-cache'});
      if (!paperResponse.ok) throw new Error(`論文条件の解析処理を取得できませんでした（HTTP ${paperResponse.status}）。`);
      const paperSource = await paperResponse.text();
      if (!paperSource.includes('def analyze_paper(') || !paperSource.includes('def inspect_paper_reference_bytes(')) {
        throw new Error('論文条件の解析処理を確認できませんでした。ページを再読み込みしてください。');
      }
      pyodide.FS.writeFile('/home/pyodide/paper.py',paperSource,{encoding:'utf8'});
      const packageUrl = new URL('aquap2py.zip', sourceUrl);
      const packageResponse = await fetch(packageUrl, {cache:'no-cache'});
      if (!packageResponse.ok) throw new Error(`aquap2pyを取得できませんでした（HTTP ${packageResponse.status}）。`);
      pyodide.FS.writeFile('/home/pyodide/aquap2py.zip',new Uint8Array(await packageResponse.arrayBuffer()));
      await pyodide.runPythonAsync(`
import sys
import json as _json
if '/home/pyodide' not in sys.path:
    sys.path.insert(0, '/home/pyodide')
if '/home/pyodide/aquap2py.zip' not in sys.path:
    sys.path.insert(0, '/home/pyodide/aquap2py.zip')
from workbench import inspect_bytes, inspect_calibration_bytes, demo_dataset, analyze
from experiment import merge_phase_files, inspect_unity_bytes, synchronize_experiment
from paper import paper_demo_dataset, inspect_paper_reference_bytes
_dataset = None
_calibration_dataset = None
_unity_dataset = None
`);
      return pyodide;
    })().catch(error => {
      // A failed CDN request can be retried on the next operation.
      runtimePromise = null;
      excelReady = false;
      loadedPackages.clear();
      throw error;
    });
  }
  return runtimePromise;
}

async function jsonResult<T>(pyodide: PyodideRuntime, code: string): Promise<T> {
  const value = await pyodide.runPythonAsync(code);
  if (typeof value !== 'string') throw new Error('解析結果の形式を確認できませんでした。');
  return JSON.parse(value) as T;
}

async function execute(request: WorkerRequest): Promise<DatasetSummary | AnalysisResult | ExperimentImport | ExperimentResult | UnitySummary | PaperLoading> {
  const pyodide = await initialize(request.pythonUrl, request.id);
  if (request.kind === 'demo' || request.kind === 'paperDemo') {
    progress(request.id, 'demo', '人工スペクトルデータを作成しています。');
    pyodide.globals.set('_use_paper_demo',request.kind === 'paperDemo');
    try {
      return await jsonResult<DatasetSummary>(pyodide, `
_next_dataset, _next_summary = paper_demo_dataset() if _use_paper_demo else demo_dataset()
_response_json = _json.dumps(_next_summary, ensure_ascii=False, allow_nan=False)
_dataset = _next_dataset
_calibration_dataset = None
_unity_dataset = None
_response_json
`);
    } finally {
      clearGlobals(pyodide, ['_next_dataset', '_next_summary', '_response_json', '_use_paper_demo']);
    }
  }
  if (request.kind === 'loadPaperReference') {
    progress(request.id,'paper-reference','参加者ごとのTaskを等しく重み付けして、共通成分の参照を計算しています。');
    pyodide.globals.set('_paper_reference_data',new Uint8Array(request.data));
    pyodide.globals.set('_paper_reference_name',request.filename);
    try {
      return await jsonResult<PaperLoading>(pyodide,`
_json.dumps(inspect_paper_reference_bytes(bytes(_paper_reference_data.to_py()), _paper_reference_name), ensure_ascii=False, allow_nan=False)
`);
    } finally {
      clearGlobals(pyodide,['_paper_reference_data','_paper_reference_name']);
    }
  }
  if (request.kind === 'loadExperiment') {
    if (request.files.filter(file=>file.phase==='Unity').length>1) throw new Error('Unityログは1ファイルを指定してください。');
    if (!request.files.some(file=>file.phase!=='Unity') || request.files.filter(file=>file.phase!=='Unity').length>30) throw new Error('フェーズ別の測定CSVは1〜30ファイルを指定してください。');
    progress(request.id,'experiment','フェーズ別のスペクトルとUnityログを確認しています。');
    const names: string[] = [];
    const specs = request.files.map((file,index) => {
      const key = `_experiment_input_${index}`;
      names.push(key); pyodide.globals.set(key,new Uint8Array(file.data));
      return {name:file.filename,phase:file.phase,key};
    });
    pyodide.globals.set('_experiment_files_json',JSON.stringify(specs));
    try {
      return await jsonResult<ExperimentImport>(pyodide,`
_experiment_files = _json.loads(_experiment_files_json)
_phase_inputs = [dict(name=_f['name'], phase=_f['phase'], data=bytes(globals()[_f['key']].to_py())) for _f in _experiment_files if _f['phase'] != 'Unity']
_next_dataset, _next_summary = merge_phase_files(_phase_inputs)
_next_unity = None
_next_unity_summary = None
for _f in _experiment_files:
    if _f['phase'] == 'Unity':
        _next_unity, _next_unity_summary = inspect_unity_bytes(bytes(globals()[_f['key']].to_py()), _f['name'])
_response_json = _json.dumps(dict(summary=_next_summary, unity=_next_unity_summary), ensure_ascii=False, allow_nan=False)
_dataset = _next_dataset
_unity_dataset = _next_unity
_calibration_dataset = None
_response_json
`);
    } finally {
      clearGlobals(pyodide,[...names,'_experiment_files_json','_experiment_files','_phase_inputs','_next_dataset','_next_summary','_next_unity','_next_unity_summary','_response_json','_f']);
    }
  }
  if (request.kind === 'loadUnity') {
    progress(request.id,'unity','Unityログの時刻と生理指標の列を確認しています。');
    pyodide.globals.set('_input_data',new Uint8Array(request.data)); pyodide.globals.set('_input_name',request.filename);
    try {
      return await jsonResult<UnitySummary>(pyodide,`
_next_unity, _next_unity_summary = inspect_unity_bytes(bytes(_input_data.to_py()), _input_name)
_response_json = _json.dumps(_next_unity_summary, ensure_ascii=False, allow_nan=False)
_unity_dataset = _next_unity
_response_json
`);
    } finally { clearGlobals(pyodide,['_input_data','_input_name','_next_unity','_next_unity_summary','_response_json']); }
  }
  if (request.kind === 'synchronize') {
    await ensurePackages(pyodide,['scipy'],request.id);
    progress(request.id,'synchronize','測定時刻ごとにUnityログを集計し、対応率とスペクトルとの関係を計算しています。');
    pyodide.globals.set('_experiment_config_json',JSON.stringify(request.config));
    pyodide.globals.set('_experiment_analysis_json',JSON.stringify(request.analysis));
    try {
      return await jsonResult<ExperimentResult>(pyodide,`
if _dataset is None or _unity_dataset is None:
    raise ValueError('フェーズ別スペクトルとUnityログを先に読み込んでください。')
_json.dumps(synchronize_experiment(_dataset, _unity_dataset, _json.loads(_experiment_config_json), _json.loads(_experiment_analysis_json)), ensure_ascii=False, allow_nan=False)
`);
    } finally { clearGlobals(pyodide,['_experiment_config_json','_experiment_analysis_json']); }
  }
  if (request.kind === 'load' || request.kind === 'loadCalibration') {
    const extension = request.filename.toLowerCase().split('.').at(-1);
    if (extension === 'xlsx') await ensureXlsx(pyodide, request.pythonUrl, request.id);
    else if (extension === 'xls') await ensurePackages(pyodide, ['xlrd'], request.id);
    else if (extension !== 'csv') throw new Error('CSV、XLSX、XLS形式のファイルを選択してください。');
    progress(request.id, 'inspect', '列名、波長、プレビューを確認しています。');
    // File names and data are globals, never interpolated into executable Python.
    pyodide.globals.set('_input_data', new Uint8Array(request.data));
    pyodide.globals.set('_input_name', request.filename);
    pyodide.globals.set('_input_sheet_json', JSON.stringify(request.sheet));
    pyodide.globals.set('_input_is_calibration',request.kind === 'loadCalibration');
    try {
      return await jsonResult<DatasetSummary>(pyodide, `
_next_dataset, _next_summary = (inspect_calibration_bytes if _input_is_calibration else inspect_bytes)(
    bytes(_input_data.to_py()), _input_name, _json.loads(_input_sheet_json)
)
_response_json = _json.dumps(_next_summary, ensure_ascii=False, allow_nan=False)
if _input_is_calibration:
    _calibration_dataset = _next_dataset
else:
    _dataset = _next_dataset
    _calibration_dataset = None
    _unity_dataset = None
_response_json
`);
    } finally {
      clearGlobals(pyodide, ['_input_data', '_input_name', '_input_sheet_json', '_input_is_calibration', '_next_dataset', '_next_summary', '_response_json']);
    }
  }
  await ensurePackages(pyodide, ['scipy', 'scikit-learn'], request.id);
  progress(request.id, 'analyze', request.config.analysisProfile === 'paper-v1' ? '論文条件のSNV・座標標準化・Baseline差と、参照条件を満たす共通成分・時間モデルを計算しています。' : request.config.nativePlsr?.enabled && request.config.analysisEngine === 'aquap2py' ? '前処理、PCA、Aquagram、aquap2方式PLSR・交差検証を計算しています。' : request.config.pls?.enabled ? '前処理、PCA、Aquagram、PLSの二重交差検証を計算しています。' : '前処理、主成分分析、Aquagramを計算しています。');
  pyodide.globals.set('_config_json', JSON.stringify(request.config));
  try {
    return await jsonResult<AnalysisResult>(pyodide, `
if _dataset is None:
    raise ValueError('先にデータを読み込むか、人工データを選択してください。')
_json.dumps(analyze(_dataset, _json.loads(_config_json), calibration=_calibration_dataset), ensure_ascii=False, allow_nan=False)
`);
  } finally {
    clearGlobals(pyodide, ['_config_json']);
  }
}

scope.onmessage = (event: MessageEvent<WorkerRequest>) => {
  const request = event.data;
  if (!request || !Number.isSafeInteger(request.id)) return;
  if (!['load', 'loadCalibration', 'demo', 'paperDemo', 'loadPaperReference', 'analyze', 'loadExperiment', 'loadUnity', 'synchronize'].includes(request.kind)) {
    scope.postMessage({ id: request.id, kind: 'error', message: '解析環境への要求が不正です。' });
    return;
  }
  if (activeRequest !== null) {
    scope.postMessage({ id: request.id, kind: 'error', message: '別の処理を実行中です。完了するまでお待ちください。' });
    return;
  }
  activeRequest = request.id;
  void execute(request).then(result => {
    scope.postMessage({ id: request.id, kind: 'success', result });
  }).catch(error => {
    const action = request.kind === 'analyze' ? '解析' : 'データの読み込み';
    scope.postMessage({ id: request.id, kind: 'error', message: `${action}に失敗しました。${detailOf(error)}` });
  }).finally(() => {
    activeRequest = null;
  });
};
