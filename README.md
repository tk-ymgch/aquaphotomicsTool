# Aquaphotomics Workbench

CSV・Excelのスペクトルを読み込み、前処理、PCA、Aquagram、結果保存まで行う研究用Webアプリの初版。React・Vite・TypeScript、Pyodide Web Workerを用い、VKC Visualizer 2のWeb版と技術構成を揃えています。

黒・白・グレー、透明なパネルと大きなインタラクティブグラフによる日本語UIです。入力データと解析結果はブラウザーのメモリー内で処理します。サーバーへの解析データのアップロード、解析データの永続保存は行いません。初回のPython実行環境・ライブラリ取得にはネット接続が必要です。

## 起動

Node.js >=22.18、pnpm 11.25.0。

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

表示されたローカルURLを開きます。`pnpm dev` と `pnpm preview` はローカルでUIを確認するためのコマンドで、パスワード認証を実行しません。解析プログラムは開発・ビルド前に `python/workbench.py` から `public/python/workbench.py` へ同期されます。

## 公開とアクセス認証（v1.1）

公開URL: https://aquaphotomics-workbench.tkymgch.chatgpt.site/

共有パスワードで利用できます。ChatGPTへのログインは不要です。認証はサーバー側で行い、ReactのJS、Python、Excel用wheelを含む全アプリ資源の取得前に署名付きCookieを検証します。CookieはSecure / HttpOnly / SameSite=Strict、8時間で失効します。利用後は画面上部の「ログアウト」を使ってください。データ処理は引き続きブラウザー内で行います。

`pnpm build` はViteの出力を `.client-build/` に生成し、全資源を認証Workerに内包した `dist/server/index.js` と `dist/.openai/hosting.json` を作ります。**distや.client-buildを静的ホストとして公開しないでください。** 本番はWorker ESMとして配置します。`.openai/hosting.json` の既存project_idを使用し、static設定は追加しません。

Sitesの本番シークレットは `SITE_PASSWORD_HASH` と `SESSION_SIGNING_KEY` の2点です。前者の書式は `pbkdf2:100000:<16-byte saltのhex>:<PBKDF2-HMAC-SHA256 32-byte digestのhex>`、後者は暗号学的乱数32-byteのhexです。平文パスワードやこれらの値をソース・.env・成果物へ保存しません。変更時は安全な入力経路で新しい値を生成し、Sitesのsecret環境変数を更新して保存済み版を再デプロイします。ハッシュまたは署名鍵を変更すると既存Cookieも失効します。環境変数がない復元直後は503でアクセスを拒否します。秘密値はアーカイブに含めないため、別環境では管理者が再設定してください。

ログインPOSTは同一Originのみ受け付け、本文サイズを制限します。誤入力は実行インスタンス内で15回/10分を上限に抑制します。この回数制限はサーバー全体で永続共有するものではありません。

## 使い方

1. 「人工データで試す」またはCSV・XLSX・XLSを読み込みます。Excelはシートを選択できます。1行が1試料、列見出しに波長（例 `1440`、`1440nm`、`wl_1440`）を含む横長形式を使います。
2. 試料ID、群、解析に使う波長列と範囲を確認します。
3. 欠損値の扱い、SNV/MSC、Savitzky–Golay平滑化・1次/2次微分を設定します。
4. 解析を実行し、元スペクトルと処理後、PCA、Aquagramを比較します。PCA点とスペクトルの選択は連動します。
5. 結果ZIPを保存します。CSV、解析条件、方式の説明、グラフPNGを含みます。設定変更後は再解析が必要です。保存には結果に実際に適用した設定を使います。

## 計算と範囲

- 前処理順序は欠損処理 → SNV/MSC → SG平滑化/微分。非等間隔の波長はSGの前に等間隔へ補間し、警告と適用条件に残します。
- PCAは中心化し、オプションで波長ごとの単位分散化を行います。主成分の符号は実行環境で反転しても同じ解です。
- Aquagramは **（各群の処理後平均 − 全体平均または対照群平均）÷全試料の標準偏差** の方式です。使用波長と基準を表示・保存します。指定波長と実波長の差が許容値を超える場合や範囲外の場合はエラーにします。aquap2の計算を実行した結果ではありません。
- 人工データは操作確認用で、水の状態・分子種や実験の有意差を示すものではありません。微分やAquagramだけで水分子種を自動判定しません。
- 初版はPLS・PLS-DA・R実行・aquap2専用形式に対応しません。
- 入力ファイルは50 MiB以下、波長列は1万列以下。解析行列は200万要素以下。速度と実際の利用可能量は端末に依存します。

## 構成

- `src/`: React UI、Plotly、Workerクライアント
- `python/workbench.py`: UIから独立した解析コア
- `tests/`: 解析・入出力の検証
- `samples/`: 人工データのCSV/Excel
- `legacy/`: 元のStreamlit版の参照用コピー（新アプリの実行には不要）

通常Pythonでの検証は `python -m pytest tests/test_workbench.py -q`（numpy, pandas, scipy, scikit-learn, openpyxl, xlrd, pytestが必要。XLS生成テストにはxlwtも使用）。Workerクライアント検証は `node tests/client-lifecycle.mjs`。型検査・ビルドは `pnpm build`。

## 保存先

Dropbox唯一の保存先：`/Yamaguchi Takehiko/private/Codex/プロジェクト/アクアフォトミクス関連プロジェクト`。共通保存ルール1.0を適用。今回の制作ソース、配布ビルド、検証結果を版付きアーカイブへ保存し、ルートの引継ぎ・移行記録に結果を記録します。認証情報やnode_modulesは含めません。

元コード: https://github.com/tk-ymgch/aquaphotomicsTool （mainの初期実装）。基盤参考: https://github.com/tk-ymgch/vkcvisualizer2/tree/codex/user-registration 。
