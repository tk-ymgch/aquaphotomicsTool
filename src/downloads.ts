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
  const columns = ['condition', 'created_at', 'samples', 'variables', 'pipeline_mode', 'missing', 'aquagram_reference', 'scatter', 'sg_smooth', 'derivative', 'pc1_variance', 'pc1_pc2_variance', 'pls_target', 'pls_cv_method', 'pls_folds', 'pls_seed', 'pls_components', 'pls_rmsecv', 'pls_maecv', 'pls_r2cv', 'pls_baseline_rmsecv'];
  return [columns, ...runs.map(run => {
    const {metadata, pca, pls} = run.result, settings = metadata.settings;
    return [run.name, run.createdAt, metadata.samples, metadata.variables, settings.pipelineMode ?? 'modern', settings.missing, metadata.settings.aquagramReference, settings.scatter, settings.smooth, settings.derivative, pca.explainedVariance[0], pca.explainedVariance.length>=2?pca.explainedVariance[0]+pca.explainedVariance[1]:null, pls?.targetColumn, pls?.method, pls?.folds, pls?.seed, pls?.selectedComponents, pls?.metrics.rmseCV, pls?.metrics.maeCV, pls?.metrics.r2CV, pls?.metrics.baselineRmseCV];
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
    'data/aquagram.csv': 'Aquagram', 'data/pls_predictions.csv': 'PLS予測・残差',
    'data/pls_cv_curve.csv': 'PLS成分選択', 'data/pls_folds.csv': 'PLS外側fold',
    'data/pls_coefficients.csv': 'PLS回帰係数',
  };
  return Object.entries(titles).filter(([path]) => typeof result.exports[path] === 'string').map(([path, title]) => {
    const [columns = [], ...rows] = parseCsv(result.exports[path]);
    return { id: path, title, columns, rows, exportPath: path };
  });
}

export function exportCsv(result: AnalysisResult, exportPath: string): void {
  const text = result.exports[exportPath];
  if (!exportPath.startsWith('data/') || !exportPath.endsWith('.csv') || typeof text !== 'string') throw new Error('保存する結果表がありません。');
  downloadBytes(new TextEncoder().encode(text), exportPath.split('/').at(-1)!, 'text/csv;charset=utf-8');
}

// An estimate bounds retained snapshots without serializing the matrices again.
export function snapshotBytes(result: ComparisonRun['result']) {
  return result.metadata.samples * result.metadata.variables * 16 +
    Object.values(result.exports).reduce((n, text) => n + text.length * 2, 0) +
    result.metadata.samples * result.pca.explainedVariance.length * 8;
}

