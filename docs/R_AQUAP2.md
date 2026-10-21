# R・aquap2へのデータ引継ぎ

Workbenchの結果を、利用者が用意したR環境へ移すための手順です。ブラウザー内でRを起動せず、測定データを外部へ送信しません。結果ZIPの `r/r_import.R` はbase Rだけで動く読込補助です。生成するRDSは通常のlist・numeric matrixで、aquap2の `aquap_data` 直接互換ファイルではありません。

## 結果ZIPからRへ

1. Workbenchで解析を終え、結果ZIPを保存して展開します。
2. 展開先に `data/preprocessed.csv` と `settings.json`、`r/r_import.R` があることを確認します。
3. Rを用意した端末で、展開ZIPのルートを第1引数、新規RDSファイルを第2引数として実行します。引数に空白があれば引用符で囲みます。

```sh
Rscript r/r_import.R "/path/to/unpacked-result" "/path/to/workbench-data.rds"
```

R起動時の利用者設定を読み込まずに実行する場合は `Rscript --vanilla r/r_import.R ...` を使います。出力先の親フォルダーは先に用意してください。既存ファイルを指定すると上書きせず停止します。スクリプトはCSVをデータとして読み、設定JSON・CSV内の文字列や、ZIP内の別スクリプトを実行しません。パッケージの自動導入・通信も行いません。

```r
bundle <- readRDS("/path/to/workbench-data.rds")
dim(bundle$spectra)        # 試料 × 波長のdouble matrix
bundle$wavelengths_nm      # 数値ベクトル、単位nm
head(bundle$header)        # sample_id / group。日本語・先頭ゼロを保持
stopifnot(identical(rownames(bundle$spectra), bundle$sample_id))
```

読込対象は `data/preprocessed.csv` です。`sample_id` と `group` を分け、`wl_` 列名から波長を取り出します。空欄・重複ID、非数値・非有限値、重複・逆順の波長、予期しない列や過大な行列を検出したら停止します。入力列名は変更せずUTF-8 BOM付きCSVにも対応します。

この行列には既に欠損処理、散乱補正、必要時の等間隔補間、SG平滑化・微分が適用されています。R側で重ねて同じ処理を行わないよう、`settings.json` の適用設定と `_provenance` を確認してください。元の値からR側で解析する場合は `data/input.csv` または `source/` の原本を使い、列・単位・欠損処理を別途定義します。PLSの目的変数や分割列は元データ側の通常CSVで確認し、PLS結果CSVも通常の表として読み込みます。この補助スクリプトはモデルや予測関数を移植しません。

## aquap2と接続する地点

aquap2の公式資料では、`getFullData()` は実験metadataとスペクトル、必要に応じてsample listを結合し、`aquap_data` を作ります。独自import関数には所定の戻り値と波長接頭文字数などの情報が必要です。Workbenchの `bundle$spectra` と `bundle$header` は、利用者が別途作るimport adapterへの入力になります。直接 `getFullData()` にこのRDSを渡す方式ではありません。[公式getFullData仕様](https://github.com/bpollner/aquap2/blob/master/man/getFullData.Rd)、[公式custom_import仕様](https://github.com/bpollner/aquap2/blob/master/man/custom_import.Rd)

接続時には、少なくとも次を実験ごとに決めます。

- sample ID・群と、aquap2側の標準header、クラス変数・数値変数、測定順序・反復・連続scanの対応。
- `NIR` 行列、行名、波長列名、`info$nCharPrevWl` の対応。ここで作るRDSの行列列名は `wl_` を除いた数値文字列です。
- 実験metadata、analysis procedure、使用するsettings、実験名・rawdata・sample listの配置。利用するaquap2版に合わせて公式import仕様を確認します。
- R側で行う前処理と、既にWorkbenchで適用した処理の区別。測定値の単位や装置条件は自動推定しません。

aquap2には温度校正用の実験・スペクトルを扱う手順があり、温度列などの条件が定義されています。Workbenchの群平均差を標準化したAquagramだけから、温度校正済みの結果、aquap2の特定Aquagramモード、分子種・WAMACSの同定結果が得られたとは扱いません。温度校正を用いる解析には、必要な実測の校正データと実験情報をR側で用意します。[公式genTempCalibExp仕様](https://github.com/bpollner/aquap2/blob/master/man/genTempCalibExp.Rd)

## 実行基盤と確認範囲

R・aquap2はブラウザー版と別の実行環境です。aquap2の導入・初期設定は利用者が選んだR環境で行い、パッケージ版・依存関係・settingsを記録してください。[aquap2公式リポジトリ](https://github.com/bpollner/aquap2)、[公式案内](https://bpollner.github.io/aquap2/)

base Rの補助読込はRscript 4.6.1で、人工45試料×61波長、日本語group、UTF-8 BOM、RDS再読込と数値一致を確認しています。検証対象は通常のRDSへの引継ぎです。aquap2本体へのadapter実装・取込、固有のAquagram、温度校正、R上でのPLS再学習は実行検証していません。利用者のR環境でも読込結果・波長順序・前処理の整合を確認してください。
