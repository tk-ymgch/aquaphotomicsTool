# 実装契約

## v1.4の実aquap2実行経路

- `analysisEngine?: 'python' | 'aquap2'`。省略はPython。`pipelineMode`は独立で両エンジン共通のPython前処理を選び、エンジン切替で設定を変更しない。
- `Aquap2Client.connect()`はloopbackサービスのhealthと短期sessionを確認。トークン・接続先はAppのstate/refのみで、設定・ZIPに含めない。未接続は実行不可。
- WorkerのPython解析完了後、前処理済み行列・実波長・ID・群とPCA/AQ条件だけを送信。固定aquap2本体の公開`gdmm`出力でPCA/AQを置換する。失敗時にPython結果をaquap2結果として採用しない。
- 対応は平均中心化/scale=falseのPCA、AQ classic/global・classic-diff/groupのみ。PCA標準化・AQ none・PLS有効は明示ブロック。旧R互換、温度校正、AUC/sfc、任意Rコード実行は含めない。
- `metadata.execution`に実エンジン・前処理エンジン・aquap2/R版・APIを記録。AQのPython ddof0とaquap2 ddof1、および必須恒等SG3/p2/m0の丸め効果を実行provenanceへ残す。
- サービスは127.0.0.1:8787だけにbindし、Origin/Host・短期Bearer・入力上限を検証する。元ファイル・目的変数を送らない。起動は利用者の前景ターミナルで行い自動起動しない。
- v1.3の限定source harnessと、インストール済み本体APIの比較は別証跡として保持する。

## v1.2の追加

- AnalysisConfig.plsは任意。単一数値目的変数、最大成分1〜10、outer folds2〜10、seed0〜2147483647。無効時は従来PCA/Aquagram解析を維持。
- PLSは生データ列から独立したtrain-only前処理を使用。outer学習区画内でinner CV（最大3分割）で成分選択、outer OOFで性能評価。GroupKFoldでは内側・外側とも同一CV群の混入を防ぐ。
- 大きさの上限は500試料/2000波長/10万行列要素と推定計算量。PCA/Aquagramの従来上限は維持。
- PLSResult、PLSConfig、ComparisonRunの正式型はsrc/types.ts。src/AdvancedPanels.tsxのplsFiguresとcomparisonFiguresを画面・PNG保存で共有する。
- src/settings.tsは版付き設定JSONと旧settings.jsonのrequestedConfigを検証して再読込する。外部JSONは1 MiB上限。結果内の大きなprovenanceは内部で要求設定だけ抽出して現行JSONへ再包装する。
- 条件比較は同一データの最大4件/推定96 MiBのメモリー内スナップショット。新データ/シートの読込成功時に消去する。比較ZIPには各条件の結果・設定・同じ表示図を保存する。
- v1.2時点のR交換は結果ZIPのr/にbase R scriptと手順を同梱するオフライン方式。v1.4のローカルaquap2実行経路とは別。

## 基本構成

- React + Vite + TypeScript、Pyodide Web Worker。Streamlit不要。
- データ型はsrc/types.ts。変更は親に連絡。UI担当はApp.tsx/styles.css/Plot.tsxのみ、Worker担当はworker.ts/client.ts/vite-env.d.ts、Python担当はpython/workbench.py/tests/test_workbench.py/samplesのみ。
- Python API: inspect_bytes(data: bytes, filename: str, sheet: str | None = None) -> tuple[pandas.DataFrame, DatasetSummary dict]。データ保持はWorker内の _dataset。
- Python API: demo_dataset() -> tuple[pandas.DataFrame, DatasetSummary dict]。人工データ45程度×波長1300〜1600nm。
- Python API: analyze(df: pandas.DataFrame, config: dict) -> AnalysisResult dict。result.exportsはCSV/JSON/READMEテキストをfile名→文字列で返す。
- Worker client公開API: class AnalysisClient { constructor(onProgress?: (p: Progress)=>void); load(file:File,sheet?:string):Promise<DatasetSummary>; demo():Promise<DatasetSummary>; analyze(config:AnalysisConfig):Promise<AnalysisResult>; dispose():void; }。worker中止時dispose後に作り直す。
- PyodideはVKCと同じ固定CDN https://cdn.jsdelivr.net/pyodide/v314.0.7/full/。NumPy/pandas/SciPy/scikit-learn/openpyxl/xlrdを必要時にロード。Pythonソースはpublic/python/workbench.pyへビルド時同期。
- 表示は日本語。初期状態は読み込み前、人工データで開始できる。ファイルは.csv/.xlsx/.xls、Excelシート選択。
- 前処理: missing処理→scatter→SG smooth/derivative。不等間隔はSG前に等間隔補間し明示。入力検証、pca成分数制限、Aquagramの指定波長・許容誤差検証。
- Aquagramは標準化した群平均差の方式を明記（全体/対照平均との差÷全試料標準偏差）。S1/S2/S3など分子種の断定を出さない。人工データは常に人工と表示。
- UIはグレースケールの透明感、黒のナビ、白の半透明パネル、大きいグラフ。グループの識別はグレー階調＋線種/マーカー。
- 設定が変わった後は結果が古いことを表示し、古い結果を新設定名で保存しない。計算/読込が失敗したら画面に理由。
- 保存: data/preprocessed.csv,pca_scores.csv,pca_loadings.csv,pca_variance.csv,aquagram.csv,settings.json,README.txtなどとPlotly PNGをfflate ZIPへ。CSVはUTF-8 BOM可。設定は実際に適用されたもの。
