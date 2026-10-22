# aquap2py 0.2.0：使い方と対応範囲

aquap2pyは、aquap2の計算をPythonで扱うための非公式の部分移植です。名称の`py`はPythonを表し、公式Python版や全機能互換を意味しません。Workbench v1.6の既定エンジンで、R不要の温度校正AQとaquap2方式PLSRを条件限定で追加しました。

参照先はaquap2 **0.4.5**、固定commit `d31c1231bf71f0e73f1a630a32934602782be488` です。aquap2pyの版0.2.0、アプリの版1.6、参照Rパッケージの版0.4.5は別々に記録します。

## Webアプリで使う

1. CSV・Excelまたは人工データを読み込みます。以前の設定を読み込んだ場合は、保存されたエンジンの選択を維持します。
2. 「aquap2py」を選び、試料ID・群・波長と前処理順を確認します。Rの導入・サービス起動・接続確認は不要です。
3. 前処理、PCA、Aquagramを実行します。未対応の設定があれば理由を表示して止まり、黙って別設定へ変更しません。
4. 結果の実装名・版・参照版・SD定義と、互換レポートを確認して保存します。

計算はブラウザー内で行い、測定データをRや公開サイトへ送信しません。初回のPython実行環境・ライブラリの取得にはネット接続が必要です。ブラウザーを使う通常解析でR本体APIを実行しないことと、開発時にRを参照して機能を検証することを区別します。

## 0.2.0で使える範囲

| 処理 | 現在の範囲・定義 |
| --- | --- |
| SNV | 試料内の標本SD（ddof=1）を使用 |
| MSC | 対象行列の平均スペクトルを参照 |
| SG平滑化・微分 | 列位置の間隔1で計算。不等間隔波長も補間しない |
| PCA | 平均中心化、波長ごとの標準化なし、最大10成分 |
| Aquagram | 標本SDのclassic、対照群差のclassic-diff。最大24実波長 |
| 温度校正AQ | sfc/diff、AUC系8モード、固定12/15帯。校正端点/Texpは観測済み温度のみ |
| aquap2方式PLSR | PLS1/kernelpls、中心化・非スケーリング、固定/自動成分、LOO/群単位CV |

散乱補正→SG、SG→散乱補正の順序を選べます。これは移植した処理の順序設定であり、R本体の任意の解析手順・実験設計や旧版アプリ全体を再現するモードではありません。

欠損値は停止だけに対応し、平均値・中央値による補完は行いません。PCAの波長標準化、Aquagramの基準なしも実行を止めます。未観測温度LOESS、bootstrap/観測数補正、PLSR固有outlier除外・多応答/他method、分類、装置固有I/O、全ての取込・実験設計・描画は未移植です。詳しい機能別・API別一覧は、アプリの「解析方式」と [対応範囲](AQUAP2PY_COVERAGE.md)、`python/aquap2py/coverage.json` を参照してください。

## 温度校正Aquagram

測定データとは別に校正CSV/Excelを読み込み、温度列を指定します。TCalib下端・上端・Texpは校正で観測した温度へ完全一致させます。未観測温度のR LOESSを別の補間で代用しません。校正用SGは既定17点、測定AQ内部SGは既定21点です。sfcには測定格子と校正の1300〜1600 nm内格子の一致が必要です。

AUC系は固定帯の多角形面積÷全スペクトル多角形面積を群平均し、校正2端点の面積比のmin/maxを0/100%へ換算します。tnはTexp校正%を減算、dceは校正温度幅による℃相当への換算、diffは対照群を減算します。DCEは試料温度の推定ではありません。0〜100%を外れてもclipせず通知します。sfcは未平滑化校正平均を中心とする測定RMSで標準化し、校正SDは使いません。

設定JSONには校正ファイル名・シート・SHA-256と条件だけを保存します。再開時は校正ファイルを再読込します。結果ZIPは `data/calibration_input.csv`、`temperature_calibration.json`、`temperature_aquagram.json` を含みます。AUC座標のnm値は描画用の帯中央で、単一点吸光度ではありません。

## aquap2方式PLSR

Webの専用設定で数値目的変数、固定/自動成分、LOOまたは群単位CVを選びます。単一応答kernelpls、平均中心化・非スケーリング、反復adjCV最小成分の最頻値による自動選択を対象にしています。全Xの前処理後にCVを行い、成分選択とCVを同じデータで行うため、Workbenchの外側nested CVによる性能評価とは異なります。

通常Pythonの `plsr` / `predict_plsr` では、予測に同じ前処理済み変数空間のXを渡します。未知試料の前処理をモデルが自動再生するものではなく、Webの未知予測UIも含みません。整数分割数による乱数CVはNumPy PCG64を使い、Rの同じseedとは分割が一致しません。R由来の具体的segmentsを明示再生した数値比較と、R乱数系列互換を区別します。結果ZIPの `native_plsr_model.json` と `data/native_plsr_*.csv` に成分選択・分割・CV/校正値・係数を保存します。

## 他のエンジンとの使い分け

**Workbench標準Python**は既存の解析経路です。欠損補完、任意のPCA標準化、母SD（ddof=0）のAquagram、基準なしの群平均、nested CVのPLSを使用できます。aquap2pyと定義の異なる計算を、同じ名称だけで数値互換とは扱いません。

**aquap2本体：R参照実行**は任意の補助経路です。同じPCの `127.0.0.1:8787` へ明示接続し、Workbench標準／旧Python互換の前処理後の行列・実波長・ID・群を送って、本体のPCA・classic/classic-diffを実行します。aquap2py固有の前処理とR本体の正式な数値照合は別の検証処理です。元ファイル・目的変数は送らず、短期接続トークンと接続先を設定・ZIPへ保存しません。[R実行環境](AQUAP2_RUNTIME.md)も参照してください。

## 通常Pythonへローカル導入する

Python 3.10以降、NumPy 1.26以降、SciPy 1.11以降を使用します。`pyproject.toml`はこのアプリのリポジトリ直下にあり、Pythonソースは `python/` 配下です。PyPIには公開していません。ソースを取得したリポジトリ直下から導入します。

```powershell
python -m venv qa/aquap2py-venv
./qa/aquap2py-venv/Scripts/python.exe -m pip install .
./qa/aquap2py-venv/Scripts/python.exe -m pip show aquap2py
```

通常Pythonのaquap2py利用にもRは不要です。上の環境はWebアプリ内のPython環境とは別です。依存パッケージが未取得ならpipによる取得にネット接続が必要です。ローカルwheel作成と別環境への導入確認は、それぞれの検証記録で確認してください。

## 互換レポートの読み方

`completeCompatibility=false` は「全体の完全互換を主張しない」という明示値です。計算結果の失敗フラグでも、実装率の数値でもありません。次の項目を分けて確認します。

- `features[].implemented`・`status`：Pythonで実装した処理と、その限定範囲。
- `oracleValidation.status`・`scope`：固定したR本体との数値照合の状態と条件。未照合を検証済みへ読み替えません。
- `apiEntries`：公開API入口の対応一覧。部分実装は、そのAPI全体の再現を意味しません。
- `verifiedScope`・`limitations`：確認範囲と未対応事項。
- `currentRunComparedWithR`・実行記録：その解析結果をRで個別比較したか。本体API未実行の通常解析と、機能開発時の検証は別です。

0.2.0の温度AQは `qa/v1.6-temperature-verification.json` で26条件・1,026 scalar値、PLSRは `qa/v1.6-plsr-verification.json` で13条件・420数値チェックを確認しました。最大絶対差はそれぞれ `2.52e-8`、`5.00e-10` で、各reportの事前の絶対・相対許容差内です。インストール済みaquap2の公開APIを使用し、source harnessは使っていません。

前処理/PCA/classicは0.2.0で再実行し、`qa/v1.6-classic-verification.json` の12条件・60数値チェックを確認しました。`qa/v1.5-aquap2py-verification.json` は0.1.0の履歴で、古い全file SHAが現版全体にも一致するという意味ではありません。v1.3の限定source harnessやv1.4のWorkbench前処理後R比較も別記録です。人工データの一致は実測研究データや全条件の科学的妥当性を示しません。

## ライセンスと配布

aquap2py部分はGPL-2.0-or-laterで、非公式実装です。同梱の `LICENSE`・`NOTICE` と上流の著作権表示を保ち、Web配布・wheel・ソースアーカイブにも必要な文書を含めます。公開・再配布に関するライセンス確認は、実装や数値検証とは別の確認事項として維持します。既存の認証・秘密情報管理・公開手順は[README](../README.md)に従ってください。
