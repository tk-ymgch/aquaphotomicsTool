export type Scatter = 'none' | 'snv' | 'msc';
export interface DatasetSummary {
  name: string; columns: string[]; preview: (string | number | null)[][];
  rowCount: number; sheets: string[]; sheet: string | null; artificial: boolean;
  suggestedId: string | null; suggestedGroup: string | null;
  wavelengthColumns: {column: string; wavelength: number}[];
}
export interface AnalysisConfig {
  idColumn: string | null; groupColumn: string | null; wavelengthColumns: string[];
  range: [number, number]; missing: 'error' | 'median'; scatter: Scatter;
  smooth: boolean; window: number; polyorder: number; derivative: 0 | 1 | 2;
  pcaScale: boolean; components: number; aquagramWavelengths: number[];
  aquagramReference: string; aquagramTolerance: number;
}
export interface AnalysisResult {
  metadata: {samples: number; variables: number; groups: string[]; range: [number, number]; warnings: string[]; settings: AnalysisConfig};
  spectra: {wavelengths: number[]; raw: number[][]; processed: number[][]; ids: string[]; groups: string[]};
  pca: {scores: number[][]; loadings: number[][]; explainedVariance: number[]; ids: string[]; groups: string[]};
  aquagram: {wavelengths: number[]; labels: string[]; groups: {name: string; values: number[]; n: number}[]; reference: string; definition: string};
  exports: Record<string, string>;
}
export type Progress = {phase: string; message: string};
