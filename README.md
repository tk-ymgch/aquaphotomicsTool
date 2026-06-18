# Aquaphotomics Workbench

Streamlit Cloudで動かすことを前提にした、スペクトルデータ解析用の小型ワークベンチです。
CSV / Excelをアップロードし、前処理、PCA、PLSプレビュー、Aquagram表示、結果のダウンロードまでを画面から操作できます。

## できること

- CSV / XLSX / XLSのアップロード
- サンプルID列、群・クラス列、目的変数列の選択
- 波長列の自動検出
- 波長範囲の絞り込み
- SNV、MSC、Savitzky-Golay平滑化、1次/2次微分
- スペクトル表示
- PCA score / loading表示
- PLSプレビュー
- Aquagram表示
- processed spectra、PCA scores、Aquagram、図のZIP出力
- Rscript接続チェック
- aquap2セットアップ補助

## 入力データの形式

1行を1サンプルにしてください。
波長列は、列名に数値波長が入っていれば自動検出されます。

例:

```csv
sample_id,group,temperature_c,wl_1300,wl_1305,wl_1310,...
S001,Control,25.1,0.71,0.72,0.73,...
S002,Treatment,25.0,0.70,0.71,0.72,...
```

対応しやすい波長列名:

- `wl_1450`
- `1450`
- `nm_1450`
- `wavelength_1450`

## ローカル実行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

R backendを使う場合は、別途RとRscriptが必要です。

## Streamlit Community Cloudへの配置

このフォルダをGitHubリポジトリに置き、Streamlit Community Cloudで `app.py` を指定してデプロイします。

必要ファイル:

```text
app.py
requirements.txt
packages.txt
r_backend/
sample_data/
.streamlit/config.toml
```

`requirements.txt` はPythonパッケージ用です。
`packages.txt` はRなどのLinuxパッケージ用です。

## R / aquap2 backend

画面の「R環境」タブで以下を確認できます。

1. `Rscript` が見つかるか
2. Rのバージョン
3. aquap2が利用可能か
4. aquap2の初回セットアップ

初回セットアップは数分かかる場合があります。
Streamlit Cloudの環境やRパッケージ依存関係によっては、aquap2のインストールに失敗することがあります。
その場合でも、Python previewエンジンで基本解析は継続できます。

## aquap2専用データへの接続

現在のR backendは、汎用CSVを受け取り、R側で前処理・PCA・Aquagram用テーブルを作る構成です。
aquap2の専用データ構造や研究室独自フォーマットに合わせる場合は、`r_backend/run_analysis.R` の入力変換部分を差し替えてください。

## 配色

UIは以下の色だけを使う方針にしています。

- White: `#ffffff`
- Gray: `#f4f5f7`, `#e5e7eb`, `#b8beca`, `#6b7280`, `#374151`
- Navy: `#1f2f54`
- Black: `#000000`
