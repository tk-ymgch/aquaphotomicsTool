# 検証記録

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
