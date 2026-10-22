# Aquaphotomics Workbench v1.6

CSV・Excelのスペクトルを読み込み、前処理、PCA、交差検証付きPLS回帰、Aquagram、解析条件の比較・保存を行う研究用Webアプリです。React・Vite・TypeScript、Pyodide Web Workerを用い、VKC Visualizer 2のWeb版と技術構成を揃えています。

黒・白・グレーの日本語UIで、新しく読み込んだデータの既定エンジンは **aquap2py 0.2.0** です。aquap2互換のPython部分移植をブラウザー内で実行し、Rの導入・接続を必要としません。温度校正・AUC系Aquagramとaquap2方式PLSRを条件限定で追加しました。初回のPython実行環境・ライブラリ取得にはネット接続が必要です。既存のWorkbench標準Pythonと、任意のR本体参照実行も残しています。

## aquap2pyを使う（v1.6 / package 0.2.0）

`aquap2py` はaquap2の計算をPythonで扱う意図を表す名称で、公式Python版・全機能の移植を意味しません。参照先は固定 **aquap2 0.4.5 / commit `d31c1231bf71f0e73f1a630a32934602782be488`** です。アプリ版1.6と、Pythonパッケージ版0.2.0、参照Rパッケージ版0.4.5を区別します。

| エンジン | 用途・主な範囲 | 実行先 |
| --- | --- | --- |
| aquap2py（新規既定） | 前処理、平均中心化PCA、classic／classic-diff、観測温度限定の校正AQ10モード、PLS1/kernelplsのnative CV | ブラウザー内、R不要 |
| Workbench標準Python | 既存の前処理、PCA、母SDのAQ、nested CVのPLS | ブラウザー内、R不要 |
| aquap2本体：R参照実行 | Workbench前処理後のPCA・AQを本体で実行する任意の比較経路 | 同じPCのRサービス |

「解析方式」で、機能ごとの移植状態、本体との数値照合状態、条件・未対応を解析前から確認できます。`completeCompatibility=false` は全体互換を主張しないという明示値です。個々の機能が条件限定で照合済みでも、全API・全データ・全設定への対応にはなりません。今回の解析でR本体を実行したかどうかは、機能検証とは別に結果へ記録します。

aquap2pyでは欠損値補完、PCAの波長標準化、AQ基準なしを実行しません。温度校正の未観測温度LOESS補間、bootstrap/観測数補正、分類、装置固有I/O、PLSRの全method・outlier除外、R metadata・実験設計・描画の全体互換も未対応です。選択した設定を黙って変えずに停止します。従来の群平均AQや外側nested CVのPLSにはWorkbench標準Pythonを選びます。以前の設定に保存された明示的なPython選択は維持します。

使い方・通常Pythonへのローカル導入・検証の読み方は[AQUAP2PY.md](docs/AQUAP2PY.md)、[互換範囲](docs/AQUAP2PY_COVERAGE.md)を参照してください。0.2.0の基礎数値は `qa/v1.6-classic-verification.json` の12条件・60数値チェック、温度AQは `qa/v1.6-temperature-verification.json` の26条件・1,026値、PLSRは `qa/v1.6-plsr-verification.json` の13条件・420数値チェックが許容差内です。420は配列・指標のチェック件数です。0.1.0の検証は履歴として残し、古い全source SHAを現版全体の再検証とは扱いません。

## 温度校正Aquagram・aquap2方式PLSR（v1.6）

aquap2pyの「温度校正Aquagram」を有効にし、測定データとは別に校正CSV・Excelを読み込み、温度列を選びます。TCalib両端とTexpは校正で観測した温度へ完全一致させます。校正用SGの既定17点と、測定AQ内部SGの既定21点は別設定です。sfc/diffとAUC系8モード、12/15固定帯に対応します。AUCの座標は波長帯の多角形面積比で、図の帯中央nmは単一点の測定値ではありません。DCEは℃相当の尺度で、試料温度の推定や有意差を意味しません。sfcは測定格子と校正の1300〜1600 nm内格子の一致が必要です。設定JSONに校正値は含めず、再開時に校正ファイルを再読込し、保存したSHA-256と照合します。結果ZIPには校正入力CSV、校正モデル、AQ結果と来歴を含めます。

「aquap2方式PLSR」は単一数値目的変数、平均中心化・非スケーリングのkernelplsを使います。固定成分または反復adjCV誤差による自動選択、LOO/群単位CVを選びます。全Xへ前処理してからCVを行うaquap2側の計算で、学習区画内で前処理・成分選択を行うWorkbenchの外側nested CVとは異なります。自動選択に使ったCV誤差を、独立な外側性能評価として解釈しないでください。Python APIの乱数CVはRの同一seed分割を保証せず、数値照合した乱数ケースはRから書き出した具体的分割を再生した条件です。未知データ予測APIには同じ前処理済み変数空間のXを渡します。未知試料ファイルの予測UIは含みません。

## 起動

Node.js >=22.18、pnpm 11.25.0。

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

表示されたローカルURLを開きます。`pnpm dev` と `pnpm preview` はローカルでUIを確認するためのコマンドで、パスワード認証を実行しません。解析プログラムとaquap2pyのソース・対応レポートは、開発・ビルド前に `python/` からブラウザー配布資源へ同期されます。

## 任意のR本体参照実行（v1.4から継続）

この経路はaquap2pyの通常利用には不要です。Workbench標準／旧Python互換の前処理後の同一行列を、インストール済みaquap2 0.4.5（固定commit `d31c1231bf71f0e73f1a630a32934602782be488`）へ渡し、`aquap2::ttap`・`getap`で準備したデータに対して公開API `aquap2::gdmm` を実行します。PCA・Aquagramを実出力で置換し、PythonのAquagramは明示した比較用CSVとして残します。エンジンを切り替えても設定を自動変更しません。aquap2py固有のR本体照合は開発用の別処理で、温度校正・PLSRの参照経路を通常Web解析のRサービスへ追加したものではありません。

WindowsでPython 3.10以降とRを用意し、プロジェクトのフォルダーで実行します。

```powershell
# 初回だけ。固定版と依存をqa下へ導入し、導入状態を確認
pwsh -File scripts/start-aquap2.ps1 -Setup -CheckOnly
# 通常利用。ターミナルを開いたままにし、終了はCtrl+C
pwsh -File scripts/start-aquap2.ps1
```

`Rscript.exe`やPythonが見つからない場合は `-Rscript`／`-Python` に実行ファイルのパスを指定します。`-RuntimePath` は本プロジェクトの `qa/` 下の専用フォルダーだけを受け付け、既定は `qa/aquap2-runtime-v1.4` です。Rのlibrary・home・settings・tempを隔離します。通常起動ではパッケージを導入せず、自動起動・外部アドレスへのbindも行いません。

Web画面で「aquap2本体：R参照実行」を選び「接続を確認」を押してください。接続確認だけでは測定データを送りません。短期接続トークンをアプリ内部で取得し、設定JSON・結果ZIP・比較ZIPには接続先やトークンを保存しません。OriginとHostを制限し、解析POSTは短期Bearerが必要です。接続許可・有効期限切れ・サービス停止時には再接続してください。ブラウザーのローカルネットワーク許可や端末の設定により接続できない場合があります。

Web接続経路の上限は3～500試料、3～2000波長、10万行列要素、PCA最大10成分、Aquagram3～24実波長です。PCA標準化・Aquagram基準なし・PLS有効は明示的に実行を止めます。aquap2 0.4.5の公開APIはAquagramの `smoothN=NULL` を拒否するため、恒等変換に相当する3点・2次・0次微分SGを内部で呼び、その丸め差を `aquap2_runtime.json` に記録します。Pythonの前処理をaquap2独自前処理へ置き換えたものではありません。

以下はv1.4からのR参照経路の確認記録で、aquap2py移植の検証値ではありません。標準・旧Python互換それぞれの人工36×61、群サイズ9/12/15による本体API比較は各6条件・24チェック、合計12条件・48数値チェックが許容内でした。PCA符号整列後の最大差は標準4.36e-15・旧互換3.98e-15、AQのSD定義換算後は標準1.21e-13・旧互換1.51e-13です。ローカルブラウザーの人工45×61ではaquap2実行・結果ZIPの再計算と、両エンジンの比較ZIP保存も確認しました。これは実測データや全モードの妥当性を示すものではありません。[検証範囲と詳細](docs/VALIDATION.md)を参照してください。

結果には実行エンジン、aquap2/Rの版、API、AQモード、Python前処理条件を記録します。`data/aquap2_vs_python_aquagram.csv` と `aquap2_comparison.json` は同一行列・試料・波長でのSD定義換算後の差を示します。実測データの妥当性やaquap2全機能の互換性を示す指標ではありません。詳細は[実行環境](docs/AQUAP2_RUNTIME.md)と[比較定義・履歴](docs/AQUAP2_COMPARISON.md)を参照してください。

## 公開とアクセス認証（v1.1）

公開URL: https://aquaphotomics-workbench.tkymgch.chatgpt.site/

共有パスワードで利用できます。ChatGPTへのログインは不要です。認証はサーバー側で行い、ReactのJS、Python、Excel用wheelを含む全アプリ資源の取得前に署名付きCookieを検証します。CookieはSecure / HttpOnly / SameSite=Strict、8時間で失効します。利用後は画面上部の「ログアウト」を使ってください。aquap2pyとWorkbench標準Pythonは測定データをブラウザー内で処理します。任意のR参照実行を選んだ場合だけ、前処理後の行列・実波長・試料ID・群名を同じPCの `127.0.0.1:8787` へ送ります。元ファイル・目的変数は送信せず、公開サイトへの解析データのアップロードも行いません。公開サイトの認証とローカルRへの接続認証は別です。

`pnpm build` はViteの出力を `.client-build/` に生成し、全資源を認証Workerに内包した `dist/server/index.js` と `dist/.openai/hosting.json` を作ります。**distや.client-buildを静的ホストとして公開しないでください。** 本番はWorker ESMとして配置します。`.openai/hosting.json` の既存project_idを使用し、static設定は追加しません。

Sitesの本番シークレットは `SITE_PASSWORD_HASH` と `SESSION_SIGNING_KEY` の2点です。前者の書式は `pbkdf2:100000:<16-byte saltのhex>:<PBKDF2-HMAC-SHA256 32-byte digestのhex>`、後者は暗号学的乱数32-byteのhexです。平文パスワードやこれらの値をソース・.env・成果物へ保存しません。変更時は安全な入力経路で新しい値を生成し、Sitesのsecret環境変数を更新して保存済み版を再デプロイします。ハッシュまたは署名鍵を変更すると既存Cookieも失効します。環境変数がない復元直後は503でアクセスを拒否します。秘密値はアーカイブに含めないため、別環境では管理者が再設定してください。

ログインPOSTは同一Originのみ受け付け、本文サイズを制限します。誤入力は実行インスタンス内で15回/10分を上限に抑制します。この回数制限はサーバー全体で永続共有するものではありません。

## 使い方

1. 「人工データで試す」またはCSV・XLSX・XLSを読み込みます。Excelはシートを選択できます。1行が1試料、列見出しに波長（例 `1440`、`1440nm`、`wl_1440`）を含む横長形式を使います。
2. 試料ID、群、解析に使う波長列と範囲を確認します。
3. 既定のaquap2py、Workbench標準Python、任意R参照からエンジンを選び、前処理順・SNV/MSC・SG平滑化や微分を設定します。aquap2pyはR接続不要です。未対応条件があると理由を示して停止します。
4. 解析を実行し、元スペクトルと処理後、PCA、Aquagramを比較します。PCA点とスペクトルの選択は連動します。
5. 結果ZIPを保存します。CSV、解析条件、方式の説明、グラフPNGを含みます。設定変更後は再解析が必要です。保存には結果に実際に適用した設定を使います。

## PLS・条件間比較・設定の再利用（v1.2）

ここで説明するPLSはWorkbench標準Pythonの外側nested CVです。aquap2pyの専用PLSR設定とは区別します。「PLS回帰を実行する」を有効にし、数値目的変数列、成分数上限、外側CV分割数、乱数シードを指定します。人工サンプルには操作確認用の連続値`synthetic_target`があります。PLS-DAや未知試料の予測UIは含みません。

成分数は各外側foldの学習データ内で内側CVにより選び、外側の未学習試料への予測を集めたOOF値からRMSECV・MAE・R²・バイアスを計算します。学習平均だけを予測する基準モデルのRMSEも表示します。欠損補完の中央値、MSCの平均スペクトル、中心化・標準化は各学習foldから計算し、評価側へ適用します。反復測定ではGroupKFoldと個体・試料を識別するCV群列を選びます。表示上の群分けとは独立しています。時系列予測用の時間順分割は含みません。PLSは8試料以上、500試料・2000波長・10万行列要素以下、さらに推定計算量の上限内で実行します。分割や学習区画の変動が不足する場合は理由を示して停止します。

全データで作る最終モデルの成分選択曲線と校正値は、外側OOFの性能評価と区別しています。異なる前処理条件を比較してモデルを選び直す場合、その選び直しを含む独立性能評価は別途必要です。R²は負の値にもなります。人工データの指標は実測データへの予測性能を示しません。

「条件間比較」で完了した解析に名前を付けて追加します。同じデータの最大4条件を保持し、前処理、PCA寄与率、PLS指標と条件別の図を並べられます。異なる前処理のPCA寄与率は分散の基準が異なるため、モデル性能の順位にはなりません。PLSの指標は目的変数・分割・評価試料が一致する条件で参考比較します。比較結果ZIPは一覧CSV、各条件の適用設定・出力・図を含みます。保持はブラウザーのメモリー内だけで、データ再読込やページ更新で消えます。保持量の上限は96 MiBです。

「設定を保存」で現在の設定だけをJSONへ保存し、「設定を読み込む」で読込済みデータに適用します。データ値は含みません。列構成・波長・型・数値範囲を検証し、適用後は再解析が必要です。旧版の結果ZIP内`settings.json`も読めます。結果ZIPの`analysis-settings.json`はその結果に使った要求設定、`settings.json`は実際の適用設定とprovenanceです。比較した条件の「設定を復元」も再解析するまで表示結果を変えません。解析結果や比較セッション全体の再読込は含みません。

結果ZIPの`r/`にはbase Rで前処理済みCSVを通常のlist・行列へ読み込むスクリプトと[Rデータ引継ぎ手順](docs/R_AQUAP2.md)を含みます。このオフライン補助と、v1.4のローカルaquap2実行サービスは別の経路です。温度校正や追加の実験設計は自動構成しません。

## 旧Python版との調整・解析方式の確認（v1.3）

Workbench標準PythonとR参照実行では、解析設定で標準方式／旧Python互換を選べます。標準方式は従来どおり欠損処理→散乱補正→SG、旧Python互換は欠損処理→SG→散乱補正です。欠損処理は停止・中央値・平均値から明示選択し、旧版の補完に合わせる場合は平均値を選びます。旧Python互換の不等間隔SGは補間せず代表波長間隔を使います。これは旧版の近似であり、標準方式の等間隔補間とは異なります。

Aquagramの「基準差・標準化なし」は前処理後の群平均を表示します。結果の「数値表」ではページ単位で値を閲覧し、その表を個別CSVへ保存できます。設定・比較CSV・結果ZIPへ実際の処理方式を記録します。旧1.2の設定も読込可能で、方式未指定は標準方式として扱います。

互換対象は有効な同一入力・同一波長・同一前処理条件での旧Python計算です。旧版の不正値の自動修正、全欠損列の0補完、波長の無制限な代替、カテゴリ値のPLS数値化は移植していません。PLSは旧版の学習内予測ではなく、引き続き学習区画内の前処理とネストした交差検証を行います。PCAの標準化・成分数も明示して比較してください。

「解析方式」で現行標準・旧Python・旧R・aquap2の違いと検証範囲を確認できます。[aquap2比較の根拠と実行範囲](docs/AQUAP2_COMPARISON.md)を参照してください。v1.3で行った公式ソースの確認・限定source harnessと、v1.4のインストール済みパッケージ本体による実行・比較を区別して記録します。

## 計算と範囲

- Workbench標準Pythonの標準方式は欠損処理 → SNV/MSC → SG平滑化/微分。非等間隔の波長はSGの前に等間隔へ補間します。旧Python互換は上記の順序・波長処理を使用し、適用条件に残します。
- aquap2pyのSNVは標本SD（ddof=1）、SGは列位置の間隔1を使い、不等間隔波長も補間しません。MSCは対象行列の平均スペクトルを参照します。前処理順の選択は、R本体の全解析手順の再現を意味しません。
- PCAは平均中心化します。Workbench標準Pythonでは波長ごとの単位分散化を選択できます。aquap2pyとR参照実行は `scale=false` のみで、標準化を有効にすると実行を止めます。主成分の符号は実行環境で反転しても同じ解です。
- Workbench標準Pythonの基準ありAquagramは **（各群の処理後平均 − 全体平均または対照群平均）÷全試料の母標準偏差（ddof=0）**、基準なしは前処理後の群平均です。classic／classic-diffはaquap2pyとR参照実行で標本SD（ddof=1）を使います。温度AQのAUC系にはSD除算がなく、sfcは校正中心からの測定RMS（分母n−1）を使います。モードごとの実波長/帯・基準・定義・単位・エンジンを表示・保存します。
- 人工データは操作確認用で、水の状態・分子種や実験の有意差を示すものではありません。微分やAquagramだけで水分子種を自動判定しません。
- PLS-DA、ブラウザー内R実行、未観測温度LOESS、bootstrap/観測数補正、利用者の任意R解析手順、aquap2の全PLSR methodには対応しません。
- 入力ファイルは50 MiB以下、波長列は1万列以下。解析行列は200万要素以下。速度と実際の利用可能量は端末に依存します。

## 構成

- `src/`: React UI、Plotly、Python Worker・ローカルaquap2クライアント
- `bridge/serve.py`: Origin・短期セッション認証付きloopbackサービス
- `scripts/start-aquap2.ps1`: 隔離R環境を使う前景サービス起動
- `scripts/aquap2_engine.R`: 固定aquap2本体の取込・gdmm実行
- `scripts/compare_aquap2.py`: 同一前処理済み行列による本体比較
- `python/workbench.py`: UIから独立した既存解析・エンジン統合
- `python/aquap2py/`: 通常Pythonとブラウザーで使う部分移植、静的対応レポート
- `tests/`: 解析・入出力の検証
- `samples/`: 人工データのCSV/Excel
- `legacy/`: 元のStreamlit版の参照用コピー（新アプリの実行には不要）

通常Pythonでの検証は `python -m pytest tests/test_workbench.py -q`（numpy, pandas, scipy, scikit-learn, openpyxl, xlrd, pytestが必要。XLS生成テストにはxlwtも使用）。Workerクライアント検証は `node tests/client-lifecycle.mjs`。型検査・ビルドは `pnpm build`。

## ライセンスと再配布

aquap2pyは非公式の部分移植で、同梱の `LICENSE`・`NOTICE` と上流の著作権表示を確認してください。aquap2py部分のライセンスはGPL-2.0-or-laterです。Web配布・wheel・ソースアーカイブにも必要な表示・ライセンス文書を含め、公開・再配布のライセンス確認を省略しません。実装・数値検証の完了だけで配布条件の確認まで完了したとは扱いません。

## 保存先

Dropbox唯一の保存先：`/Yamaguchi Takehiko/private/Codex/プロジェクト/アクアフォトミクス関連プロジェクト`。共通保存ルール1.0を適用。今回の制作ソース、配布ビルド、検証結果を版付きアーカイブへ保存し、ルートの引継ぎ・移行記録に結果を記録します。認証情報やnode_modulesは含めません。

元コード: https://github.com/tk-ymgch/aquaphotomicsTool （mainの初期実装）。基盤参考: https://github.com/tk-ymgch/vkcvisualizer2/tree/codex/user-registration 。
