export type Scatter = 'none' | 'snv' | 'msc';
export interface PLSConfig {
  enabled: boolean; targetColumn: string | null; maxComponents: number;
  folds: number; split: 'kfold' | 'group'; cvGroupColumn: string | null;
  seed: number; scale: boolean;
}
export interface PLSResult {
  targetColumn: string; method: 'nested-kfold' | 'nested-group-kfold';
  selectedComponents: number; folds: number; innerFolds: number; seed: number; scale: boolean;
  metrics: {rmseCV: number; maeCV: number; r2CV: number; biasCV: number; baselineRmseCV: number; rmseCalibration: number; r2Calibration: number};
  observed: number[]; predictedCV: number[]; predictedCalibration: number[];
  residuals: number[]; fold: number[]; ids: string[]; groups: string[];
  curve: {components: number; rmseCV: number}[];
  foldModels: {fold: number; components: number; train: number; test: number}[];
  coefficients: {wavelengths: number[]; values: number[]; intercept: number};
  warnings: string[]; definition: string;
}
export interface DatasetSummary {
  name: string; columns: string[]; preview: (string | number | null)[][];
  rowCount: number; sheets: string[]; sheet: string | null; artificial: boolean;
  suggestedId: string | null; suggestedGroup: string | null;
  wavelengthColumns: {column: string; wavelength: number}[];
}
export interface AnalysisConfig {
  idColumn: string | null; groupColumn: string | null; wavelengthColumns: string[];
  range: [number, number]; missing: 'error' | 'median' | 'mean'; scatter: Scatter;
  pipelineMode?: 'modern' | 'legacy-python';
  smooth: boolean; window: number; polyorder: number; derivative: 0 | 1 | 2;
  pcaScale: boolean; components: number; aquagramWavelengths: number[];
  aquagramReference: string; aquagramTolerance: number;
  pls?: PLSConfig;
}
export interface AnalysisResult {
  metadata: {samples: number; variables: number; groups: string[]; range: [number, number]; warnings: string[]; settings: AnalysisConfig};
  spectra: {wavelengths: number[]; raw: number[][]; processed: number[][]; ids: string[]; groups: string[]};
  pca: {scores: number[][]; loadings: number[][]; explainedVariance: number[]; ids: string[]; groups: string[]};
  aquagram: {wavelengths: number[]; labels: string[]; groups: {name: string; values: number[]; n: number}[]; reference: string; definition: string};
  exports: Record<string, string>;
  pls?: PLSResult;
}
export interface ComparisonRun {id: string; name: string; createdAt: string; result: AnalysisResult}
export type Progress = {phase: string; message: string};
