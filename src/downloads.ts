import type { AnalysisResult, ComparisonRun } from './types';

export function downloadBytes(bytes: Uint8Array, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([bytes as Uint8Array<ArrayBuffer>], {type}));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename;
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
const cell = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`;
export function comparisonCsv(runs: ComparisonRun[]) {
  const columns = ['condition', 'created_at', 'samples', 'variables', 'analysis_engine', 'aquap2_version', 'implementation_name', 'implementation_version', 'reference_aquap2_version', 'aquagram_sd_ddof', 'r_package_executed', 'pipeline_mode', 'missing', 'aquagram_reference', 'scatter', 'sg_smooth', 'derivative', 'pc1_variance', 'pc1_pc2_variance', 'pls_target', 'pls_cv_method', 'pls_folds', 'pls_seed', 'pls_components', 'pls_rmsecv', 'pls_maecv', 'pls_r2cv', 'pls_baseline_rmsecv','native_plsr_target','native_plsr_validation','native_plsr_components','native_plsr_rmsecv','native_plsr_adjusted_rmsecv','aquagram_mode','aquagram_unit','calibration_sha256','native_detrend','native_plsr_retained','native_plsr_excluded','tcalib_low','tcalib_high','texp','analysis_profile','paper_input_kind','paper_loading_participants','paper_reference_sha256'];
  return [columns, ...runs.map(run => {
    const {metadata, pca, pls} = run.result, settings = metadata.settings;
    const paper = run.result.paper;
    return [run.name, run.createdAt, metadata.samples, metadata.variables, metadata.execution?.engine ?? 'python', metadata.execution?.aquap2Version, metadata.execution?.implementationName ?? (metadata.execution?.engine === 'aquap2' ? 'aquap2' : 'Workbench Python'), metadata.execution?.implementationVersion, metadata.execution?.referenceAquap2Version, run.result.aquagram.mode?.startsWith('aucs') ? null : run.result.aquagram.sdDdof ?? metadata.execution?.aquagramSdDdof ?? (metadata.execution?.engine === 'aquap2' ? 1 : (settings.aquagramReference === 'none' ? null : 0)), metadata.execution?.packageApiExecuted ?? false, settings.pipelineMode ?? 'modern', settings.missing, metadata.settings.aquagramReference, settings.scatter, settings.smooth, settings.derivative, pca.explainedVariance[0], pca.explainedVariance.length>=2?pca.explainedVariance[0]+pca.explainedVariance[1]:null, pls?.targetColumn, pls?.method, pls?.folds, pls?.seed, pls?.selectedComponents, pls?.metrics.rmseCV, pls?.metrics.maeCV, pls?.metrics.r2CV, pls?.metrics.baselineRmseCV,run.result.nativePlsr?.targetColumn,run.result.nativePlsr?.settings.validation,run.result.nativePlsr?.selectedComponents,run.result.nativePlsr?.metrics.rmseCV,run.result.nativePlsr?.metrics.rmseAdjCV,run.result.aquagram.mode,run.result.aquagram.unit,settings.nativeAquagram?.calibrationSource?.sha256,settings.nativePreprocessing?.detrend??false,run.result.nativePlsr?.ids?.length,run.result.nativePlsr?.excludedIds?.length,settings.nativeAquagram?.tCalib?.[0],settings.nativeAquagram?.tCalib?.[1],settings.nativeAquagram?.tExp,settings.analysisProfile??'current',paper?.preprocessing.inputKind,paper?.mode.participantCount,paper?.mode.referenceSource?.sha256];
  })].map(row => row.map(cell).join(',')).join('\n') + '\n';
}

export interface ResultTable {
  id: string; title: string; columns: string[];
  rows: (string | number | null)[][]; exportPath: string;
}

// Parse the actual saved CSV, preserving IDs, quoted delimiters and embedded newlines.
// Keep strings as strings so the on-screen table never rounds a saved value.
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], value = '', quoted = false;
  const input = text.replace(/^\uFEFF/, '');
  for (let i = 0; i < input.length; i++) {
    const char = input[i];
    if (char === '"') {
      if (quoted && input[i + 1] === '"') { value += '"'; i++; }
      else quoted = !quoted;
    } else if (!quoted && (char === ',' || char === '\n' || char === '\r')) {
      row.push(value); value = '';
      if (char !== ',') {
        rows.push(row); row = [];
        if (char === '\r' && input[i + 1] === '\n') i++;
      }
    } else value += char;
  }
  if (value.length || row.length) { row.push(value); rows.push(row); }
  return rows;
}

export function getResultTables(result: AnalysisResult): ResultTable[] {
  const titles: Record<string, string> = {
    'data/preprocessed.csv': '前処理後スペクトル', 'data/pca_scores.csv': 'PCAスコア',
    'data/pca_loadings.csv': 'PCAローディング', 'data/pca_variance.csv': 'PCA寄与率',
    'data/aquagram.csv': 'Aquagram', 'data/aquap2_vs_python_aquagram.csv': 'aquap2とPythonの比較', 'data/python_reference_aquagram.csv': 'Python参照Aquagram', 'data/pls_predictions.csv': 'PLS予測・残差',
    'data/pls_cv_curve.csv': 'PLS成分選択', 'data/pls_folds.csv': 'PLS外側fold',
    'data/pls_coefficients.csv': 'PLS回帰係数',
    'paper/normalized_coordinates.csv': '論文条件 · 標準化座標C',
    'paper/delta_coordinates.csv': '論文条件 · Baseline差ΔC',
    'paper/common_mode.csv': '論文条件 · 共通モード',
    'paper/task_fits.csv': '論文条件 · Taskモデル',
    'paper/post_blocks.csv': '論文条件 · Task後のブロック',
    'paper/reference_loading.csv': '論文条件 · 共通loading',
    'data/native_plsr_exclusions.csv':'aquap2方式PLSRの除外試料','data/native_plsr_predictions.csv':'aquap2方式PLSR予測・残差','data/native_plsr_curve.csv':'aquap2方式PLSR成分選択','data/native_plsr_coefficients.csv':'aquap2方式PLSR係数','data/calibration_input.csv':'温度校正の入力データ',
  };
  return Object.entries(titles).filter(([path]) => typeof result.exports[path] === 'string').map(([path, title]) => {
    const [columns = [], ...rows] = parseCsv(result.exports[path]);
    return { id: path, title, columns, rows, exportPath: path };
  });
}

export function exportCsv(result: AnalysisResult, exportPath: string): void {
  const text = result.exports[exportPath];
  if ((!exportPath.startsWith('data/') && !/^paper\/(?:normalized_coordinates|delta_coordinates|common_mode|task_fits|post_blocks|reference_loading)\.csv$/.test(exportPath)) || !exportPath.endsWith('.csv') || typeof text !== 'string') throw new Error('保存する結果表がありません。');
  downloadBytes(new TextEncoder().encode(text), exportPath.split('/').at(-1)!, 'text/csv;charset=utf-8');
}

// An estimate bounds retained snapshots without serializing the matrices again.
export function snapshotBytes(result: ComparisonRun['result']) {
  return result.metadata.samples * result.metadata.variables * 16 +
    Object.values(result.exports).reduce((n, text) => n + text.length * 2, 0) +
    result.metadata.samples * result.pca.explainedVariance.length * 8;
}
