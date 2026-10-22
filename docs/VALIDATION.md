# 検証記録

## v1.6：aquap2py 0.2.0の温度校正・AUC・PLSR

対象は非公式のPython部分移植aquap2py 0.2.0、参照はインストール済みaquap2 **0.4.5 / commit `d31c1231bf71f0e73f1a630a32934602782be488`** です。全API互換を示す `completeCompatibility` はfalseを維持します。この節の数値は通常Pythonと開発用の実R公開API oracleの確認であり、利用者入力を毎回Rで照合した記録ではありません。以下の旧版各節は当時の確認範囲として読み分けます。

通常Pythonの全テストは **253 passed**。温度校正モデル、10モードの変換・対照群差・単位、未対応条件の明示拒否、PLS1/CV/adjCV・選択・処理済X予測と、既存解析・入出力の回帰を含みます。Node 9本、設定24チェック、型検査・本番ビルドも成功しました。隔離wheelの通常Python検証は成功し、確定コミットからの再構築記録はQAへ保存します。ローカルブラウザーで校正CSV、設定JSONの保存・再読込、温度AUCと固定成分PLSRの同時実行・結果ZIP保存を確認しました。ブラウザー出力の数値再計算・公開環境の証拠は、日付付きQAレポートで別に記録します。

| 現版の正本 | 条件と比較件数 | 結果・最大絶対差 |
| --- | --- | --- |
| `qa/v1.6-classic-verification.json` | 人工24×61、不均等3群、12条件・60数値チェック | PASS。前処理1.0436e-14、PCA符号整列後scores1.2088e-14/loadings1.0957e-13、寄与率7.7716e-16、classic AQ2.7089e-13 |
| `qa/v1.6-temperature-verification.json` | 人工測定12×301、校正63×301、26条件・1,026 scalar値 | PASS。全体2.5206e-8、等間隔24条件9.0564e-10 |
| `qa/v1.6-plsr-verification.json` | 人工PLS1、13条件・420数値チェック | PASS。4.9977e-10。420は配列・指標の比較チェック件数 |

classic/温度AQは事前の絶対許容 `1e-8`・相対許容 `1e-7`、PLSRは絶対・相対とも `1e-8` で判定しました。3正本とも `sourceHarnessUsed=false` で、インストール済み固定R packageの公開APIを実行しています。各reportの数値source SHAと全人工入出力SHAを実ファイルへ照合しました。旧 `qa/v1.5-aquap2py-verification.json` は0.1.0 snapshotの履歴で、その古い全file SHAを現版全体の検証結果へ読み替えません。

### 基礎数値の現版再照合

PythonとRへ同じ生matrixを渡し、R側も公開 `gdmm` の `dpt.pre` でSG/SNV/MSCを実行しました。SGはp2/n21/m0、p2/n11/m0・1・2の端点/ts=1、SGとSNV/MSCの両順序、不等間隔の無補間を含みます。平均中心化・非標準化PCAの先頭5成分は符号整列し、寄与率も比較しています。classic/classic-diffはAQ内部SG3・MSCなし・標本SDのままで、母SDとの換算を使いません。予約名global、日本語・引用符・改行labels、行順・ID・群・波長の往復、定数SNVと同一スペクトルの2退化条件の双方拒否を確認しました。入力/出力は `qa/v1.6-classic-oracle-verified/` にあります。

### 温度校正・AUC/sfc

公開 `ttap→saveAQdata→gdmm→getcm` により校正R-dataを作り、全10非classic modeを12/15座標で比較しました。校正SG17、測定AQ内部SG21、sfc内部MSC off/on、TCalib全範囲/対称指定、不等間隔と名目band端点が測定格子にない条件を含みます。校正はSG後に1300〜1600 nmへcutして温度別平均、測定は行別の固定帯polygon面積/全入力幅polygon面積を群平均します。%の校正min/maxは指定2端点から求め、範囲内の全温度からは求めません。

tnはTexpの校正%を減算し、dceは校正幅で℃相当へ換算、diffは対照群を減算します。DCEは推定試料温度ではありません。sfcは未平滑化校正平均を中心とする測定RMS（分母n−1）を使い、校正SDを分母にしません。AUCにはSD除算がなく、軸のnmは固定帯中央です。0〜100%範囲外をclipせず、分母・実band範囲・単位・処理順を保存します。

初版の対応は観測済みTCalib両端とTexpへ限定しています。未観測温度のrobust quadratic LOESS、bootstrap、観測数random補正は明示拒否する4条件を確認しました。sfcは測定格子と校正cut格子の一致が必要です。outlier検出は行わず、R oracleでも強制除外を明示的に解除した人工校正を使います。小さい校正endpoint差により丸め誤差が増幅した初期狭帯profileは別記録へ残し、良好な校正と混同しません。正本の入力/出力は `qa/v1.6-temperature-oracle-final-verified/`、詳細は `qa/v1.6-temperature-contract.md` です。

### aquap2方式PLSR

公開 `gdmm` と `plot_pls_indepPred` を用い、PLS1/kernelpls、平均中心化・非スケーリング、固定/自動成分、LOO/leave-one-group-outを比較しました。native前処理、model/modelPlusの係数・intercept・fit/residual、CV/adjCV・PRESS・誤差曲線、ラベルなしを含む処理済み未知Xの予測を確認しています。結果は `qa/v1.6-plsr-oracle-final-verified/` にあります。

全Xへ前処理してからCVし、反復adjCVの成分選択を行うaquap2経路です。学習区画内で前処理し、内側で成分選択するWorkbench標準Pythonの外側nested CVとは異なり、選択に使ったCV誤差を独立な外側性能と解釈しません。乱数CVの固定成分1条件はR由来の具体的segmentsを再生して照合しました。Rと同じseed系列、乱数CVの自動選択履歴、PLSR固有outlier除外、多応答/他PLS method、未知raw Xへの自動前処理は対象外です。

### 再実行と未確認範囲

通常Python回帰は `python -m pytest tests -q` で実行します。実R oracleは固定版を導入した開発環境でのみ使い、`scripts/compare_aquap2py.py`、`scripts/compare_temperature.py`、`scripts/compare_plsr.py` に既存結果を上書きしない新しい `--output` と `--report` を指定します。R library・home・settingsは隔離し、通常Web解析のR依存にはしません。

実測データの科学的妥当性、全装置IO・metadata/S4・実験設計・描画、LOESS/boot/NR、R RNG、全PLSR method、上限近傍の端末別性能は確認結果へ含めません。公開・ブラウザーの最終確認はリリースQA記録を参照してください。[対応範囲と根拠](AQUAP2PY_COVERAGE.md)に機能別の条件を記録しています。

## v1.4：インストール済みaquap2本体の統合

共通のPython前処理済み行列を隔離R環境へ送り、インストール済みaquap2 0.4.5の公開`gdmm`で平均中心化・標準化なしのPCAとclassic/classic-diffを実行する経路を追加しました。比較計画は、同一行列・試料順・実波長でPCA成分の符号を整列し、Aquagramはddof0→ddof1の換算を明示して照合するものです。必須の恒等SG3/p2/m0とその丸め差も各実行に記録します。

`qa/v1.4-aquap2-verification.json`（標準方式）と `qa/v1.4-aquap2-legacy-verification.json`（旧Python互換）は、通常Python対本体APIの条件限定比較です。人工36×61、群サイズ9/12/15、12実波長で、散乱補正なし・SNV＋SG・MSC＋SG × 全体基準・指定対照群の各6条件/24数値チェック、合計12条件/48チェックが成功しました。PCAの符号整列後最大絶対差は標準4.36e-15・旧互換3.98e-15、AQのSD換算後は標準1.21e-13・旧互換1.51e-13です。換算前の参考最大差は両方式0.02230、恒等SGの最大丸め効果は6.66e-16でした。絶対許容1e-7・相対許容1e-6で判定し、sourceHarnessUsed=false、installedPackage=true、packageApiExecuted=trueを記録しています。

通常Pythonの全回帰は145 passed / 1 skippedでした。Nodeの全テスト、型検査、本番ビルドも成功しています。ローカルブラウザーでは人工45×61のaquap2実行とZIP保存後の再計算を確認し、`qa/v1.4-browser-export-verification.json` が成功しました。保存出力の前処理最大差2.00e-15、PCAスコア4.62e-15・負荷量3.97e-14・寄与率4.44e-16、AQのSD換算後8.06e-14で、本体実行provenanceと6図PNGも確認しています。PCA標準化・Aquagram基準なし・PLSの非対応条件がUIで実行を止めること、両エンジンの結果を保持した比較ZIPの保存も確認しました。これらはローカルブラウザーの確認であり、公開サイトと利用者端末のR接続の確認とは区別します。

v1.3の限定source harnessの数値を本体/APIの検証値へ流用しません。起動スクリプトはPowerShell構文・ヘルプと、既存隔離環境での `-CheckOnly`（aquap2 0.4.5/R 4.6.1）を確認しました。Windowsの継承POSIX localeは子プロセス起動時だけ解除し、終了時に呼出元環境を戻します。この起動スクリプト確認ではパッケージの再導入やサービスの常駐起動は行っていません。R 4.6.1を含むruntime ZIPの別復元先での実行確認は現在作業中で、完了とは扱っていません。

実行範囲・再現方法は[AQUAP2_COMPARISON.md](AQUAP2_COMPARISON.md)、[R環境](AQUAP2_RUNTIME.md)を参照してください。実測データ、温度校正/AUC/sfc、旧R互換、PLSのR実行は今回の対象外です。上記の条件限定比較から、両エンジンの任意の前処理・データでの一般的な互換性は主張しません。

## v1.3の履歴：旧Python互換・方式説明・数値表

通常Pythonで既存68件と新規63件、計131テストが成功しました。旧Streamlitの関数をASTから独立に読み出し、人工データの54条件（等間隔/不等間隔、SG微分0/1/2次、散乱補正なし/SNV/MSC、Aquagram none/global/control）を比較しました。前処理の最大絶対差3.67e-14、PCA符号整列後スコア2.77e-14、Aquagram4.00e-14でした。平均値補完、標準方式の既定維持、PLS各学習区画内の平均補完・SG後MSC参照も検証しています。確認範囲と除外は `qa/v1.3-legacy-verification.json` に記録しています。

設定JSONは15チェック（旧1.2読込、新1.3方式/mean/none、不等間隔時の実波長検証を含む）、結果表CSVは先頭ゼロID・日本語・引用符・改行・数値文字列の保持と比較CSVの処理方式記録を確認しました。既存Workerクライアント/XLSX準備、認証19チェック、型検査・本番ビルドも成功しました。

ローカルブラウザーでは人工45×61に旧Python互換・平均値補完・SNV/SG・Aquagram基準なし・PLS nested5/3を適用しました。方式の表示・結果表・個別CSV保存・28ファイル/10PNGのZIP保存を確認し、保存出力から通常Pythonで再計算した145項目が一致しました。最大絶対差は1.47e-13です。個別PCAスコアCSVはZIP内の同CSVと一致し、比較説明文と実際の方式・補完・基準・aquap2未実行の記録も確認しました。これはブラウザーと通常Pythonの比較であり、旧関数との54条件照合とは別の検証です。

aquap2は0.4.5/latestPublicの固定commitと、0.5.1/masterの固定commitの公式ソースを調査しました。classicの標本SDとWorkbenchの母SDの差、波長選択・既定座標、温度校正系の別定義を説明しています。インストール済みパッケージ/APIは実行していません。限定公式関数と明示したbase R adapterによる人工9×12のsource harnessでclassic/classic-diffの計72値を照合し、換算後の最大差4.44e-15でした。詳細・根拠・再実行方法は[AQUAP2_COMPARISON.md](AQUAP2_COMPARISON.md)と `qa/v1.3-aquap2-comparison.json` を参照してください。

実測研究データ、旧版すべての救済挙動、旧Rとの出力一致、aquap2本体/API、温度校正/AUC、容量上限近傍の性能は今回の確認範囲外です。公開後の確認・保存結果は引継ぎのv1.3追補へ記録します。

## v1.2：交差検証付きPLS・条件間比較・設定再読込

通常Pythonの既存40件＋PLS28件、合計68件が成功しました。PLSは独立したscikit-learn二重CVループとの一致、学習区画だけから推定した中央値・MSC参照・中心化・尺度、内側/外側の群分離、評価側の目的値を変えても当該foldの学習と予測が変わらないこと、係数からの校正予測の再現、候補数制限・不正入力・計算量制限を確認しました。

設定JSONはNode13チェック、比較CSVは引用符・改行・PLS未実行・PCA1成分の場合を確認しています。既存Workerクライアント・Excel準備・認証19チェックと配布Worker検証、型検査・本番ビルドも成功しています。

ローカルブラウザーの実Pyodideで人工45×61のSNV/SG＋PLSを実行し、通常Pythonによる再計算と145項目を照合しました。成分数と内外CV分割は完全一致し、予測・残差・曲線・係数の最大差は約9.95e-14、RMSE差4.55e-15、R²差7.77e-16でした。PNG10枚を含む27ファイルの結果ZIPを確認しています。検証環境はブラウザーNumPy2.4.6/pandas3.0.2/SciPy1.18.0、通常Pythonは1.26.4/2.2.2/1.13.1、scikit-learnはいずれも1.8.0です。これは確認した環境間の一致であり、任意版間の互換性を保証するものではありません。

画面では設定JSON保存→変更→再読込、SNV/MSCの2条件比較、比較ZIP保存、比較条件の設定復元と未適用表示を確認しました。GroupKFoldは3群を指定し、外側3/内側最小2分割への制限を含め実行できました。データや図はすべて人工データです。

Rscript4.6.1では前処理済み45×61CSVを通常のRDSへ読み込み、全数値、波長、ID、日本語群名の往復一致を確認しました。UTF-8 BOM、先頭ゼロ・引用符・カンマを含むIDも保持します。既存出力の上書き拒否と、コードのような非数値セルの拒否も確認しました。aquap2本体の取込・解析・温度校正は未実行です。

実測研究データ、上限近傍の速度、時系列分割、PLS-DA・未知試料予測は今回の確認範囲に含みません。公開環境での最終操作確認と保存の照合結果はプロジェクト引継ぎのv1.2追補へ記録します。

## v1.1：見出しと公開認証の変更

研究用の機能名を中心とした見出しへ変更し、サーバー側の共有パスワード認証とログアウトを追加しました。独立した `tests/site-auth.mjs` で、認証フォーム、未認証の資源拒否、Origin、本文サイズ、Cookie属性、改ざん拒否、8時間の失効、鍵変更、ログアウト、HEAD、404、no-storeを確認します。`tests/site-build.mjs` は配布WorkerのESM形式、static設定の不在、全資源が認証対象であることを確認します。パスワードや本番のハッシュ・署名鍵はテストにも成果物にも含めません。

`pnpm build`、認証19チェック、配布Worker検証、既存のWorkerクライアント・Excel準備テストが成功しました。本番ではChatGPTログインなしのパスワード入口、指定パスワードでの入室、誤入力拒否、ログアウト、未認証9資源の拒否、認証後の資源配信を確認しました。SitesはHTMLへ配信用の内容を付加するため、HTMLはアプリのrootと認証フォーム不在を確認し、JS・Python・wheel等9ファイルは元バイトとのSHA-256一致を確認しました。

本番ブラウザーで人工45試料×61波長を読込み、SNV・SG平滑化、PCA、Aquagram、6図PNGを含む結果ZIP保存が成功しました。新しいCSP下でPyodide・Plotlyが動作しています。XLSX/XLSや実測データの本番での再検証は行っていません。以下の数値計算に関する記録は初版で確認した内容です。

確認日: 2026-10-21。対象はReact・Vite・TypeScriptとPyodide Web Workerによる初版です。

通常Pythonの解析・入出力テスト、Nodeの通信制御テスト、ローカルブラウザーの操作確認をそれぞれ実施しました。**40件のpytestは通常Pythonでの結果**です。ブラウザーでは下記の操作経路と保存結果を確認しています。

## 実施結果

| 検証環境・対象 | 結果 | 確認した内容 |
| --- | --- | --- |
| 通常Python / `tests/test_workbench.py` | 40 passed、skipなし | 数値計算、CSV・Excel読込、入力検証、出力・適用設定 |
| Node / `tests/client-lifecycle.mjs` | PASS | 同時実行防止、設定のスナップショット、ファイル検証、転送、中止、5分タイムアウト、Worker障害 |
| Node / `tests/worker-xlsx.mjs` | PASS | 同一オリジンの固定Excel wheel URL、依存再解決の抑止、初回失敗後の再試行、一時値の後始末、成功時の再利用 |
| ローカルブラウザー / 実際のPyodide | 成功 | 人工データ、XLSX読込・シート切替、2次微分、対照群指定、PCA・Aquagram、ZIP保存 |
| 保存ZIPと通常Pythonの数値比較 | 一致 | 前処理済みスペクトル、PCA寄与率、Aquagramの数値 |

Nodeの2テストは通信・環境準備を制御して検証するもので、Excelファイルをブラウザーで実際に解析した記録は次節に分けて記載しています。

### 通常Pythonの数値・入出力検証

- 人工データ45試料×61波長の再現性と、CSV・XLSX・XLSの再読込時にも保持される人工データ表示。
- UTF-8 BOM付き・CP932 CSV、日本語の列値、波長列の検出。XLSXの2シート選択とXLS実読込。
- 既知の加算・乗算差を持つスペクトルによるSNVとMSCの照合。
- 既知の2次多項式によるSGの1次・2次微分。nm単位の波長間隔と端点を含めた数値の照合。
- 不等間隔波長の等間隔への線形補間、適用格子・補間記録の保存。
- 既知のrank 1データによるPCAの再構成、単位分散化後の固有値との照合、試料数・変数数に応じた成分数制限。
- 全体平均・対照群平均との差を用いるAquagramの手計算との照合。`group:`指定により`global`・`全体平均`などと同名の群も区別。
- 欠損・非数値の中央値補完、全欠損列・波長重複・重複ID・不正なSG条件・Aquagram許容誤差・範囲外波長のエラー。
- 読込時・解析時の1万波長上限、解析行列200万要素上限の明示的な拒否。
- 入力表・設定を破壊しないこと、CSVと解析結果の一致、適用設定と要求設定の記録、NaNを含まないJSON。
- ファイル確認・人工データ生成の段階でSciPy・scikit-learnを必要としないこと。

上限のテストは、上限超過を安全に拒否することを確認したものです。上限近傍における実ブラウザーの速度・メモリー使用量は未計測です。

通常Pythonの確認環境はPython 3.12.4、NumPy 1.26.4、pandas 2.2.2、SciPy 1.13.1、scikit-learn 1.8.0、openpyxl 3.1.2、pytest 7.4.4、xlrd 2.0.2です。XLSサンプルの生成にはxlwt 1.3.0を使用しました。実行時にはopenpyxl内部の`datetime.utcnow()`に関する非推奨警告が10件あり、テストの失敗はありませんでした。

### ローカルブラウザーで確認した操作

1. 「人工データで試す」から45試料×61波長を読み込み、解析画面を確認。
2. `samples/synthetic_spectra.xlsx`をファイル選択から実際に読み込み。
3. Excelの「説明」シートへ切り替え、波長列のないデータに対する理由付きのエラーを確認。
4. 「人工スペクトル」シートへ戻り、再び解析可能になることを確認。
5. 2次微分を指定し、Aquagramの対照群に「人工群 B」を指定して再解析。
6. PCA・Aquagramを表示し、適用された条件と人工データ表示を確認。
7. 結果ZIPを保存し、元のXLSX、CSV、設定、説明、PNGを取得。

グラフ確認画像: [PCA](../qa/pca.jpg)、[Aquagram](../qa/aquagram.jpg)、[狭い画面のAquagram](../qa/mobile-aquagram.jpg)。

## 保存結果と数値の照合

機械可読の根拠は[qa/browser-export-verification.json](../qa/browser-export-verification.json)です。ブラウザーで保存したZIPを展開し、保存された入力・条件から通常Pythonで再計算した結果と比較しています。

- 保存ZIP: `aquaphotomics_synthetic_spectra_2026-10-21T12-37-37.zip`
- SHA-256: `4df8120b7dc2f96d03b649b1ca2e2454e9e68fc8a193c1e16314d79b3dd1b20d`
- 45試料、61波長、2次微分、Aquagram基準`group:人工群 B`、人工データフラグ`true`。
- 全16ファイル。元のXLSX 1件、データCSV 6件、JSON 2件、README 1件、PNG 6件。
- PNGは`raw`、`processed`、`scores`、`loadings`、`variance`、`aquagram`の6図で、すべて空でないファイルを確認。

| 比較したファイル | 数値部分の形状 | 最大絶対差 |
| --- | --- | --- |
| `data/preprocessed.csv` | 45×61 | 1.0018×10⁻¹⁶ |
| `data/pca_variance.csv` | 5×2 | 6.6613×10⁻¹⁶ |
| `data/aquagram.csv` | 36×3 | 2.0012×10⁻¹⁴ |

これは浮動小数点計算の精度内での一致です。主成分の符号は実行環境によって反転する場合があるため、ここではPCAの寄与率を数値比較しています。

## 再実行手順

プロジェクトのルートで実行します。Node.js 22.18以上、pnpm 11.25.0と、上記のPython解析ライブラリが必要です。`xlrd`がない環境ではXLSのpytestがskipされるため、40件すべてを再実行するときは先に用意します。`xlwt`は既存XLSサンプルを読むテストには不要です。

```powershell
python -m pytest tests/test_workbench.py -q
node tests/client-lifecycle.mjs
node tests/worker-xlsx.mjs
pnpm build
```

この作業PCの一時検証依存を利用する場合は、pytestの前に次を実行します。別環境では通常のPython環境に`xlrd`をインストールしてください。

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath 'qa/python-test-deps').Path
python -m pytest tests/test_workbench.py -q
```

ブラウザー確認は`pnpm dev`で表示されたURLを開き、「ローカルブラウザーで確認した操作」の順に実行します。初回のPyodide・解析ライブラリ取得にはネット接続が必要です。ZIP内の`settings.json`には、実際の適用設定と`_provenance.requestedConfig`が入ります。

保存ZIPの数値をもう一度照合する場合は、下の例のZIPパスを置き換えて実行します。ZIPの`data/input.csv`を再読込し、保存された要求設定を使って再計算します。

```powershell
@'
import importlib.util
import io
import json
import zipfile
import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location('workbench', 'python/workbench.py')
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)
archive = 'ここを保存したZIPのパスへ変更.zip'

with zipfile.ZipFile(archive) as z:
    settings = json.loads(z.read('settings.json'))
    df, _ = wb.inspect_bytes(z.read('data/input.csv'), 'input.csv')
    result = wb.analyze(df, settings['_provenance']['requestedConfig'])
    for path in ['data/preprocessed.csv', 'data/pca_variance.csv', 'data/aquagram.csv']:
        saved = pd.read_csv(io.BytesIO(z.read(path))).select_dtypes(include='number').to_numpy()
        replay = pd.read_csv(io.StringIO(result['exports'][path])).select_dtypes(include='number').to_numpy()
        assert saved.shape == replay.shape, path
        difference = float(np.max(np.abs(saved - replay)))
        print(path, saved.shape, 'max_abs_difference=', difference)
        assert np.allclose(saved, replay, rtol=1e-10, atol=1e-10), path
'@ | python -
```

## 未確認の範囲

- 利用者の実測データ、研究室独自の入力形式や科学的解釈の妥当性。
- ファイルサイズ・波長数・行列要素数の上限近傍での端末別速度とメモリー量。
- 公開サーバー上の実動作。この記録作成時点ではローカルブラウザーで確認しています。
- ブラウザーUIからのXLSファイルの実読込。XLSの読込・解析は通常Pythonで確認済みです。

人工データによる一致は解析経路と入出力の確認です。分子種の同定、実験群間の有意差、未知試料への予測性能の検証には相当しません。
