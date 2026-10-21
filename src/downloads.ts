import type { ComparisonRun } from './types';

export function downloadBytes(bytes: Uint8Array, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([bytes as Uint8Array<ArrayBuffer>], {type}));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename;
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
const cell = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`;
export function comparisonCsv(runs: ComparisonRun[]) {
  const columns = ['condition', 'created_at', 'samples', 'variables', 'scatter', 'sg_smooth', 'derivative', 'pc1_variance', 'pc1_pc2_variance', 'pls_target', 'pls_cv_method', 'pls_folds', 'pls_seed', 'pls_components', 'pls_rmsecv', 'pls_maecv', 'pls_r2cv', 'pls_baseline_rmsecv'];
  return [columns, ...runs.map(run => {
    const {metadata, pca, pls} = run.result, settings = metadata.settings;
    return [run.name, run.createdAt, metadata.samples, metadata.variables, settings.scatter, settings.smooth, settings.derivative, pca.explainedVariance[0], pca.explainedVariance.length>=2?pca.explainedVariance[0]+pca.explainedVariance[1]:null, pls?.targetColumn, pls?.method, pls?.folds, pls?.seed, pls?.selectedComponents, pls?.metrics.rmseCV, pls?.metrics.maeCV, pls?.metrics.r2CV, pls?.metrics.baselineRmseCV];
  })].map(row => row.map(cell).join(',')).join('\n') + '\n';
}

// An estimate bounds retained snapshots without serializing the matrices again.
export function snapshotBytes(result: ComparisonRun['result']) {
  return result.metadata.samples * result.metadata.variables * 16 +
    Object.values(result.exports).reduce((n, text) => n + text.length * 2, 0) +
    result.metadata.samples * result.pca.explainedVariance.length * 8;
}
