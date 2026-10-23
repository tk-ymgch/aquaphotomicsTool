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
  importNotes?: string[];
  dataKind?: 'spectra' | 'unity-log' | 'table';
  experiment?: {files: {name: string; phase: ExperimentPhase; rows: number}[]; phases: ExperimentPhase[]; timeColumns: ExperimentTimeColumn[]; phaseTimeAnchors?:{phase:string;column:string;value:string|number;kind:string}[]; warnings: string[]};
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
  excludeOutliers?: boolean; outlierRange?: number;
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
  retainedIndices?: number[]; excludedIndices?: number[]; excludedIds?: string[];
}
export type AnalysisEngine = 'python' | 'aquap2' | 'aquap2py';
export interface PaperLoading {
  values: number[];
  source: {name: string; sha256: string};
  participantCount: number;
  energy?: number;
}
export interface PaperConfig {
  phaseColumn: string; baselineLabel: string; taskLabel: string;
  subjectColumn: string | null; timeColumn: string | null;
  timeUnit: 'seconds' | 'milliseconds' | 'datetime';
  inputKind: 'as-recorded' | 'reflectance';
  loading?: PaperLoading;
}
export interface PaperResult {
  profile: 'paper-v1';
  coordinateLabels: string[]; targetWavelengths: number[]; actualWavelengths: number[];
  preprocessing: {range: number[]; channels: number; actualRange: number[]; inputKind: 'as-recorded' | 'reflectance'; snvDdof: 1; columnSdDdof: 1; smoothing: false; normalizationPopulation: string; baselineRule: string};
  timeAxis: {kind: 'seconds' | 'sample-order'; definition: string};
  subjects: {id: string; rows: number; baselineRows: number; taskRows: number; postRows: number; baselineIndices: number[]; taskIndices: number[]; normalizerMean: number[]; normalizerSd: number[]; baselineCoordinateMean: number[]}[];
  rows: {id: string; subject: string; phase: string; timeSeconds: number | null; isTask: boolean; coordinates: number[]; modeObserved: number | null; modePredicted: number | null}[];
  mode: {available: boolean; source: 'external-loading' | 'loaded-subject-pooled-svd' | 'unavailable'; loading: number[] | null; participantCount: number; loadedSubjects: number; energy: number | null; referenceSource?: {name: string; sha256: string}; reason: string | null};
  fits: {subject: string; status: 'fitted' | 'unavailable'; reason: string | null; delay: number | null; amplitude: number | null; tau: number | null; noise: number | null; rmse: number | null; r2: number | null; cost: number | null; success: boolean; points: {time: number; observed: number; predicted: number; rate: number}[]; bounds?: Record<string, unknown>}[];
  blocks: {subject: string; phase: string; sourceFile: string | null; label: string; n: number; coordinateMean: number[]; modeMean: number | null; modeSd: number | null}[];
  provenance: Record<string, unknown>; limitations: string[];
}
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
  analysisProfile?: 'current' | 'paper-v1';
  paper?: PaperConfig;
  smooth: boolean; window: number; polyorder: number; derivative: 0 | 1 | 2;
  pcaScale: boolean; components: number; aquagramWavelengths: number[];
  aquagramReference: string; aquagramTolerance: number;
  pls?: PLSConfig;
  nativeAquagram?: NativeAquagramConfig;
  nativePlsr?: NativePLSRConfig;
  nativePreprocessing?: {detrend: boolean};
}
export interface AnalysisResult {
  metadata: {samples: number; variables: number; groups: string[]; range: [number, number]; warnings: string[]; settings: AnalysisConfig; execution?: ExecutionRecord; compatibilityReport?: CompatibilityReport};
  spectra: {wavelengths: number[]; raw: number[][]; processed: number[][]; ids: string[]; groups: string[]};
  pca: {scores: number[][]; loadings: number[][]; explainedVariance: number[]; ids: string[]; groups: string[]};
  aquagram: {wavelengths: number[]; labels: string[]; groups: {name: string; values: number[]; n: number}[]; reference: string; definition: string; sdDdof?: number | null; mode?: string; unit?: string; coordinateRanges?: number[][]; provenance?: Record<string, unknown>; samples?: {ids: string[]; groups: string[]; values: number[][]; definition: string; metadata?: Record<string, (string | number | null)[]>}};
  exports: Record<string, string>;
  pls?: PLSResult;
  nativePlsr?: NativePLSRResult;
  paper?: PaperResult;
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

export type ExperimentPhase = 'Baseline' | 'Task' | 'Recovery';
export type ExperimentFileRole = ExperimentPhase | 'Unity';
export interface ExperimentFile { file: File; phase: ExperimentFileRole }
export interface ExperimentImport {
  summary: DatasetSummary;
  unity: UnitySummary | null;
}
export interface UnitySummary {
  name: string; rowCount: number; columns: string[];
  timeColumns: ExperimentTimeColumn[];
  suggestedTimeColumn: string | null;
  suggestedTimeUnit: 'seconds' | 'milliseconds' | 'datetime';
  metricColumns: Record<string, unknown>;
  warnings?: string[];
  [key: string]: unknown;
}
export interface ExperimentConfig {
  spectraTimeMode: 'column' | 'manual'; spectraTimeColumn: string | null;
  spectraTimeUnit: 'seconds' | 'milliseconds' | 'datetime';
  unityTimeColumn: string; unityTimeUnit: 'seconds' | 'milliseconds' | 'datetime';
  unityStartTime: string | null; timeOffsetSeconds: number;
  manualPhases: Record<ExperimentPhase, {startSeconds: number; intervalSeconds: number}>;
  windowSeconds: number; maxGapSeconds: number; minCoverage: number; minSamples: number;
  blinkThreshold: number; blinkMinSeconds: number; blinkMaxSeconds: number;
  anchorConfirmation?: 'user-confirmed-task-first';
}
export interface ExperimentTimeColumn {column: string; kind: 'datetime' | 'seconds'; uniqueValues?: number; rows?: number}
export interface ExperimentRow {
  id: string; phase: string; sourceFile: string; sourceRow: number; timeSeconds: number;
  windowStart: number; windowEnd: number; unitySamples: number; coverage: number;
  valid: boolean; reason: string | null; metrics: Record<string, number | null>; pcaScores: number[] | null;
}
export interface ExperimentResult {
  rows: ExperimentRow[];
  phaseSummaries: {phase: string; totalSpectra: number; matchedSpectra: number; metrics: Record<string, {n: number; mean: number | null; sd: number | null}>}[];
  correlations: {metric: string; pca: {component: number; n: number; r: number | null}[]; spectra: {wavelength: number; n: number; r: number | null}[]}[];
  metrics: {key: string; label: string; unit: string}[];
  timeline: {timeSeconds: number; pupilMean: number | null; opennessMean: number | null; gazeAngleDeg: number | null}[];
  blinkEvents: {startSeconds: number; endSeconds: number; midpointSeconds: number; durationSeconds: number}[];
  warnings: string[];
  provenance: {config: ExperimentConfig; [key: string]: unknown};
  exports: Record<string, string>;
  [key: string]: unknown;
}
