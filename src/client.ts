import type { AnalysisConfig, AnalysisResult, CalibrationSummary, DatasetSummary, Progress, ExperimentConfig, ExperimentFile, ExperimentImport, ExperimentResult, UnitySummary, PaperLoading } from './types';

export type WorkerPayload =
  | { kind: 'load'; data: ArrayBuffer; filename: string; sheet: string | null }
  | { kind: 'loadCalibration'; data: ArrayBuffer; filename: string; sheet: string | null }
  | { kind: 'demo' }
  | { kind: 'paperDemo' }
  | { kind: 'loadPaperReference'; filename: string; data: ArrayBuffer }
  | { kind: 'loadExperiment'; files: {filename: string; data: ArrayBuffer; phase: ExperimentFile['phase']}[] }
  | { kind: 'loadUnity'; filename: string; data: ArrayBuffer }
  | { kind: 'synchronize'; config: ExperimentConfig; analysis: AnalysisResult | null }
  | { kind: 'analyze'; config: AnalysisConfig };

export type WorkerRequest = WorkerPayload & { id: number; pythonUrl: string };
export type WorkerResponse =
  | { id: number; kind: 'progress'; progress: Progress }
  | { id: number; kind: 'success'; result: ClientResult }
  | { id: number; kind: 'error'; message: string };

type ClientResult = DatasetSummary | AnalysisResult | ExperimentImport | ExperimentResult | UnitySummary | PaperLoading;
interface PendingRequest {
  id: number;
  resolve: (value: ClientResult) => void;
  reject: (reason: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

// Initial downloads can be substantial; a bounded request still allows cancellation
// through dispose() while the worker is fetching packages or executing Python.
const REQUEST_TIMEOUT_MS = 5 * 60 * 1000;
const MAX_FILE_BYTES = 50 * 1024 * 1024;

export class AnalysisClient {
  private readonly worker: Worker;
  private readonly pythonUrl: string;
  private readonly onProgress?: (progress: Progress) => void;
  private pending: PendingRequest | null = null;
  private disposed = false;
  private sequence = 0;

  constructor(onProgress?: (progress: Progress) => void) {
    this.onProgress = onProgress;
    this.pythonUrl = new URL(`${import.meta.env.BASE_URL}python/workbench.py`, window.location.href).href;
    try {
      this.worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
    } catch {
      throw new Error('解析環境を起動できませんでした。Web Workerに対応したブラウザーでページを再読み込みしてください。');
    }
    this.worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
      const response = event.data;
      const pending = this.pending;
      if (!pending || response.id !== pending.id) return;
      if (response.kind === 'progress') {
        this.report(response.progress);
        return;
      }
      clearTimeout(pending.timer);
      this.pending = null;
      if (response.kind === 'success') pending.resolve(response.result);
      else if (response.kind === 'error') pending.reject(new Error(response.message));
      else pending.reject(new Error('解析環境から不正な応答が返されました。データを読み直してください。'));
    };
    this.worker.onerror = (event) => {
      event.preventDefault();
      this.stop(new Error('解析環境を起動または実行できませんでした。ページを再読み込みしてお試しください。'));
    };
    this.worker.onmessageerror = () => {
      this.stop(new Error('解析環境とのデータ通信に失敗しました。データを読み直してください。'));
    };
  }

  load(file: File, sheet?: string): Promise<DatasetSummary> {
    return this.request<DatasetSummary>(async () => {
      if (!/\.(csv|xlsx|xls)$/i.test(file.name)) {
        throw new Error('CSV、XLSX、XLS形式のファイルを選択してください。');
      }
      if (file.size === 0) throw new Error('ファイルが空です。データのあるファイルを選択してください。');
      if (file.size > MAX_FILE_BYTES) throw new Error('ファイルは50 MB以下にしてください。');
      this.report({ phase: 'reading', message: 'ファイルをブラウザー内に読み込んでいます。' });
      let data: ArrayBuffer;
      try {
        data = await file.arrayBuffer();
      } catch {
        throw new Error('ファイルを読み込めませんでした。ファイルが利用可能か確認してください。');
      }
      return { kind: 'load', data, filename: file.name, sheet: sheet ?? null };
    });
  }

  demo(): Promise<DatasetSummary> {
    return this.request<DatasetSummary>(async () => ({ kind: 'demo' }));
  }

  paperDemo(): Promise<DatasetSummary> {
    return this.request<DatasetSummary>(async () => ({ kind: 'paperDemo' }));
  }

  loadPaperReference(file: File): Promise<PaperLoading> {
    return this.request<PaperLoading>(async () => {
      if (!/\.csv$/i.test(file.name) || file.size === 0 || file.size > MAX_FILE_BYTES) {
        throw new Error('論文条件の共通成分参照には、空でない50 MB以下のCSVを選択してください。');
      }
      this.report({phase:'reading', message:'共通成分の参照データをブラウザー内で読み込んでいます。'});
      return {kind:'loadPaperReference', filename:file.name, data:await file.arrayBuffer()};
    });
  }

  loadExperiment(files: ExperimentFile[]): Promise<ExperimentImport> {
    return this.request<ExperimentImport>(async () => {
      if (!files.length || files.length > 32) throw new Error('実験データは1〜32ファイルを選択してください。');
      if (files.filter(item => item.phase === 'Unity').length > 1) throw new Error('Unityログは1ファイルを指定してください。');
      if (files.filter(item => item.phase !== 'Unity').length > 30) throw new Error('フェーズ別の測定CSVは合計30ファイルまでにしてください。');
      let total = 0;
      const prepared = [];
      for (const {file, phase} of files) {
        if (!/\.csv$/i.test(file.name)) throw new Error('実験の一括読込にはCSVファイルを選択してください。');
        if (file.size === 0 || file.size > MAX_FILE_BYTES) throw new Error('各ファイルは空でない50 MB以下のCSVにしてください。');
        total += file.size;
        if (total > 100 * 1024 * 1024) throw new Error('一括読込は合計100 MB以下にしてください。');
        this.report({phase:'reading',message:`実験データをブラウザー内で読み込んでいます（${prepared.length + 1} / ${files.length}）`});
        prepared.push({filename:file.name, phase, data:await file.arrayBuffer()});
      }
      if (!prepared.some(item => item.phase !== 'Unity')) throw new Error('少なくとも1つの測定フェーズのCSVを指定してください。');
      return {kind:'loadExperiment',files:prepared};
    });
  }

  loadUnity(file: File): Promise<UnitySummary> {
    return this.request<UnitySummary>(async () => {
      if (!/\.csv$/i.test(file.name) || file.size === 0 || file.size > MAX_FILE_BYTES) throw new Error('Unityログは空でない50 MB以下のCSVを選択してください。');
      return {kind:'loadUnity',filename:file.name,data:await file.arrayBuffer()};
    });
  }

  synchronize(config: ExperimentConfig, analysis: AnalysisResult | null): Promise<ExperimentResult> {
    const snapshot = structuredClone(config), saved = analysis ? structuredClone(analysis) : null;
    return this.request<ExperimentResult>(async () => ({kind:'synchronize',config:snapshot,analysis:saved}));
  }

  loadCalibration(file: File, sheet?: string): Promise<CalibrationSummary> {
    return this.request<CalibrationSummary>(async () => {
      if (!/\.(csv|xlsx|xls)$/i.test(file.name)) throw new Error('温度校正にはCSV、XLSX、XLSを選択してください。');
      if (file.size === 0 || file.size > MAX_FILE_BYTES) throw new Error('校正ファイルは空でない50 MB以下のファイルを選択してください。');
      this.report({phase:'reading',message:'温度校正データをブラウザー内に読み込んでいます。'});
      const data = await file.arrayBuffer();
      return {kind:'loadCalibration',data,filename:file.name,sheet:sheet??null};
    });
  }

  analyze(config: AnalysisConfig): Promise<AnalysisResult> {
    // Clone synchronously so later UI changes cannot change an in-flight request.
    let snapshot: AnalysisConfig;
    try {
      snapshot = structuredClone(config);
    } catch {
      return Promise.reject(new Error('解析設定を読み取れませんでした。設定を確認してください。'));
    }
    return this.request<AnalysisResult>(async () => ({ kind: 'analyze', config: snapshot }));
  }

  dispose(): void {
    this.stop(new Error('処理を中止しました。再開するにはデータを読み直してください。'));
  }

  private report(progress: Progress): void {
    // A UI callback must not prevent requests from settling.
    try { this.onProgress?.(progress); } catch { /* The computation remains usable. */ }
  }

  private request<T extends ClientResult>(prepare: () => Promise<WorkerPayload>): Promise<T> {
    if (this.disposed) return Promise.reject(new Error('解析環境は終了しています。データを読み直してください。'));
    if (this.pending) return Promise.reject(new Error('別の処理を実行中です。完了するまでお待ちください。'));
    const id = ++this.sequence;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.stop(new Error('処理が5分以内に完了しなかったため中止しました。通信状態やデータ量を確認して、データを読み直してください。'));
      }, REQUEST_TIMEOUT_MS);
      this.pending = { id, resolve: value => resolve(value as T), reject, timer };
      void prepare().then(payload => {
        if (this.disposed || this.pending?.id !== id) return;
        const request: WorkerRequest = { ...payload, id, pythonUrl: this.pythonUrl };
        const transfer = payload.kind === 'load' || payload.kind === 'loadCalibration' || payload.kind === 'loadUnity' || payload.kind === 'loadPaperReference' ? [payload.data] : payload.kind === 'loadExperiment' ? payload.files.map(item => item.data) : [];
        try {
          this.worker.postMessage(request, transfer);
        } catch {
          throw new Error('解析環境にデータを送れませんでした。データを読み直してください。');
        }
      }).catch(error => {
        if (this.pending?.id !== id) return;
        clearTimeout(timer);
        this.pending = null;
        reject(error instanceof Error ? error : new Error('処理の準備に失敗しました。'));
      });
    });
  }

  private stop(reason: Error): void {
    if (this.disposed) return;
    this.disposed = true;
    this.worker.terminate();
    this.worker.onmessage = null;
    this.worker.onerror = null;
    this.worker.onmessageerror = null;
    if (this.pending) {
      clearTimeout(this.pending.timer);
      const { reject } = this.pending;
      this.pending = null;
      reject(reason);
    }
  }
}
