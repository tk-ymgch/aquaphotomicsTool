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
export interface CalibrationSummary extends DatasetSummary {
  sourceSha256: string;
  temperatureColumns: {column: string; observedTemperatures: number[]}[];
}
export type TemperatureAquagramMode = 'sfc' | 'sfc-diff' | 'aucs' | 'aucs-diff' | 'aucs.tn' | 'aucs.tn-diff' | 'aucs.tn.dce' | 'aucs.tn.dce-diff' | 'aucs.dce' | 'aucs.dce-diff';
export interface NativeAquagramConfig {
  enabled: boolean; mode: TemperatureAquagramMode; coordinateSystem: 'ot1.12' | 'ot1.15';
  temperatureColumn: string | null; calibrationSmoothN: number;
  tCalib: [number, number]; tExp: number; smoothN: number; msc: boolean;
  referenceGroup: string | null;
  calibrationSource?: {name: string; sheet: string | null; sha256: string};
}
export interface NativePLSRConfig {
  enabled: boolean; targetColumn: string | null; components: number | null;
  validation: 'LOO' | 'group'; cvGroupColumn: string | null;
}
export interface NativePLSRResult {
  schemaVersion: number; algorithm: string; selectedComponents: number;
  targetColumn: string; ids: string[]; groups: string[];
  observed: number[]; predictedCV: number[]; predictedCalibration: number[];
  residuals: number[]; fold: number[];
  metrics: {rmseCV: number; rmseAdjCV: number; rmseCalibration: number; r2CV: number; r2Calibration: number; biasCV: number; maeCV: number; baselineRmseCV: number};
  curve: {components: number; rmseCV: number; rmseAdjCV: number; rmseCalibration: number; r2CV: number; r2Calibration: number}[];
  coefficients: {values: number[]; intercept: number};
  selection: {mode: string; iterations?: number; [key: string]: unknown};
  model: Record<string, unknown>; modelPlus: Record<string, unknown>;
  settings: Record<string, unknown>; provenance: Record<string, unknown>;
  warnings: string[]; definition: string;
}
export type AnalysisEngine = 'python' | 'aquap2' | 'aquap2py';
export interface CompatibilityReport {
  schemaVersion: number;
  implementation: {name: string; version: string; unofficial: boolean};
  reference: {name: string; version: string; commit: string};
  completeCompatibility: boolean;
  apiEntries: {name: string; kind: string; status: string; notes?: string}[];
  features: {id: string; label: string; implemented: boolean; status: string;
    oracleValidation: {status: string; scope: string; reportId?: string}; notes?: string}[];
  limitations: string[]; verifiedScope: string[];
  currentRunComparedWithR?: boolean;
}
export interface AnalysisConfig {
  idColumn: string | null; groupColumn: string | null; wavelengthColumns: string[];
  range: [number, number]; missing: 'error' | 'median' | 'mean'; scatter: Scatter;
  pipelineMode?: 'modern' | 'legacy-python';
  analysisEngine?: AnalysisEngine;
  smooth: boolean; window: number; polyorder: number; derivative: 0 | 1 | 2;
  pcaScale: boolean; components: number; aquagramWavelengths: number[];
  aquagramReference: string; aquagramTolerance: number;
  pls?: PLSConfig;
  nativeAquagram?: NativeAquagramConfig;
  nativePlsr?: NativePLSRConfig;
}
export interface AnalysisResult {
  metadata: {samples: number; variables: number; groups: string[]; range: [number, number]; warnings: string[]; settings: AnalysisConfig; execution?: ExecutionRecord; compatibilityReport?: CompatibilityReport};
  spectra: {wavelengths: number[]; raw: number[][]; processed: number[][]; ids: string[]; groups: string[]};
  pca: {scores: number[][]; loadings: number[][]; explainedVariance: number[]; ids: string[]; groups: string[]};
  aquagram: {wavelengths: number[]; labels: string[]; groups: {name: string; values: number[]; n: number}[]; reference: string; definition: string; sdDdof?: number | null; mode?: string; unit?: string; coordinateRanges?: number[][]; provenance?: Record<string, unknown>};
  exports: Record<string, string>;
  pls?: PLSResult;
  nativePlsr?: NativePLSRResult;
}
export interface ExecutionRecord {
  engine: AnalysisEngine; preprocessingEngine: 'python' | 'aquap2py';
  pcaEngine: AnalysisEngine; aquagramEngine: AnalysisEngine;
  packageApiExecuted: boolean; aquap2Version?: string; rVersion?: string;
  api?: string; aquagramMode?: string;
  implementationName?: string; implementationVersion?: string;
  referenceAquap2Version?: string; aquagramSdDdof?: number | null;
}
export interface ComparisonRun {id: string; name: string; createdAt: string; result: AnalysisResult}
export type Progress = {phase: string; message: string};
