# aquap2 公式ソースとの比較

調査日: 2026-10-21。これは研究用Workbenchの計算定義を説明するための比較です。**インストール済みaquap2本体・公開APIでの実行比較は未実施**です。実測データ、温度校正、AUCモードでの数値一致を確認したものではありません。

比較の主基準は、旧セットアップと公式READMEが指定する `latestPublic` の **aquap2 0.4.5 / commit `d31c1231bf71f0e73f1a630a32934602782be488`** です。調査日の `master` は **0.5.1 / commit `57ee096fbecf28a321eed5884784e01b0bca036b`**。ブランチ名だけでは版が動くため、以下は固定コミットへリンクします。[0.4.5の版情報](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/DESCRIPTION)、[公式インストール案内](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/README.md)、[0.5.1の版情報](https://github.com/bpollner/aquap2/blob/57ee096fbecf28a321eed5884784e01b0bca036b/DESCRIPTION)。

## classic とWorkbenchの対応

| 項目 | aquap2 0.4.5 classic | Workbenchの標準化Aquagram |
| --- | --- | --- |
| 前処理 | Aquagram内部で任意SG（p=2,m=0）→任意MSC | modern設定では散乱補正→必要なら等間隔補間→SG/微分 |
| 波長選択 | `which(wls %in% selWls)` の一致列 | 希望波長に最も近い列を許容誤差内で選択。実際の波長を保存 |
| 標準化 | 選択各波長で全試料を中心化しsample SD（ddof=1）で除算→群平均 | （群平均−全体平均または対照群平均）÷全試料population SD（ddof=0） |
| 対照群 | `classic-diff` がclassic値から指定群の値を差し引く | 対照群を基準に選択 |
| 基準なし | classicは中心化・標準化あり | 前処理後の群平均をそのまま表示。classicとは定義が違う |
| 既定座標の一部 | 1476 nm | 1478 nm。設定により変更可能 |

実装根拠は [classic / classic-diff の計算順](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L25-L55)、[do_scale](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/gen_coreDataManip.r#L302-L308)、[実際の波長選択と試料数補正](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L796-L832)、[aquap2既定座標](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/inst/settings.r#L206-L233) です。

`som::normalize(x, byrow=FALSE)` は `apply(x, 2, scale)` を呼びます。Rの `scale` は平均中心化後の平方和を `n−1` で割った平方根を使用するため、classicのSDは **ddof=1** です。コメント中の「scaleと違う」という記載だけからSD定義を判断していません。[som 0.3-5.2の固定ソース](https://github.com/cran/som/blob/a56214b9583cea8e4f2856d28d9461072ec3d20c/R/som.R#L285-L293)、[R公式scale仕様](https://search.r-project.org/R/refmans/base/html/scale.html)。

同じ前処理済み行列、同じ試料、同じ波長、欠損なし、定数列なしなら、全体基準のWorkbench値を `W` とするとclassicは `W × sqrt((n−1)/n)` になります。classic-diffも同じ係数で対照群との差に対応します。標準化→群平均と、群平均差→同じSDで除算は線形演算なので、**順序だけでは別の差を生みません**。これは条件をそろえた場合の式の対応であり、既定設定のアプリ同士や全前処理の互換性を示しません。0.5.1でもclassic・classic-diff・do_scaleの関数式はRでparseしたASTが0.4.5と同一でした。

## 温度校正を使うモード

aquap2既定モードは `aucs.dce` でありclassicではありません。`sfc` は校正スペクトルの平均を中心とする標準化、`aucs` 系は温度校正から得た面積比の最小・最大に対する百分率を使います。Workbenchはこれらの校正計算を実装していません。[モードの公式説明](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/man/calc_aqg_modes.Rd)、[既定値](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/inst/settings.r#L223-L234)。

- `sfc`: SG→任意MSC→座標抽出→校正平均を中心に `scale(...,center=avg,scale=TRUE)`→群平均。分母はその校正中心からの二乗偏差和を `n−1` で割った平方根で、試料自身の平均周りのSDと一般には同じではありません。[sfc](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L78-L99)、[校正平均を中心とする標準化](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/gen_coreDataManip.r#L310-L317)。
- `aucs`: 各試料で、座標の波長帯と両端の直線基線で閉じた多角形面積を全スペクトルの閉じた多角形面積で割る→群平均→校正最小・最大を用いて `(面積比−最小)×100/(最大−最小)`。**波長帯の単純な吸光度平均ではありません**。座標境界、第一倍音の範囲、校正用設定も必要です。[面積比](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L435-L480)、[百分率](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L500-L510)、[群平均の順](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L57-L64)。
- `aucs.tn` は測定温度に相当する校正百分率を差し引く。`aucs.dce` は百分率を校正温度範囲へ写像し、`aucs.tn.dce` は差を温度範囲の幅で換算する。`-diff` はさらに指定群差を取ります。[温度正規化とDCEの式](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L101-L158)。

温度校正データ、測定温度、校正範囲、前処理、aquap2固有のmetadata/settingsが必要です。欠損した校正温度ではloess補間を使う経路もあります。今回の人工データには実測の温度校正を付けておらず、この系統の数値比較は未実施です。[校正データと補間](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L529-L599)、[校正と前処理の注意](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/man/calc_aqg_args.Rd#L110-L115)。

## 公開APIとRへの接続地点

確認した両版の公開APIは `gdmm(dataset, ap=getap(), noiseFile="def", tempFile="def")` です。入力は `aquap_data`、解析手順は `aquap_ap`、出力は `aquap_cube`。`getcube` や `aquagram` という名前のexportは確認できません。[gdmmの正式引数](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/man/gdmm.Rd#L5-L34)、[公開名](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/NAMESPACE)。

Workbenchの `r_import.R` が保存するRDSは標準list/matrixです。aquap2のdatasetとは異なります。`ttap` などの公式変換に、class列の `C_` / numeric列の `Y_`、波長prefix、metadataと実験設計、解析手順ファイル、校正データを合わせる作業が次の接続地点です。[公式変換ttap](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/man/ttap.Rd)、[R出力ガイド](R_AQUAP2.md)。公開APIを呼ぶ例の形は次の通りですが、今回この経路は実行していません。

```r
# fd は正式なaquap_data、metadata/analysis procedureの準備済み環境が前提
cube <- aquap2::gdmm(fd, ap = aquap2::getap(
  do.aqg = TRUE, aqg.vars = "C_Group", aqg.mod = "classic",
  aqg.smoothN = NULL, aqg.msc = FALSE, aqg.nrCorr = FALSE,
  aqg.bootCI = FALSE,
  aqg.selWls = c(1342,1364,1374,1384,1412,1426,1440,1452,1462,1476,1488,1512)))
```

## 検証範囲と再実行

R 4.6.1は起動しましたがaquap2と主要依存は未導入でした。ワークスペース内の隔離libraryへのsom/plyr導入を試したところ、CRAN indexのDNS解決に失敗しました。既存R libraryは変更していません。`scripts/aquap2_reference.R` は、この状況で式を調べるための**限定source harness**です。インストール済みaquap2本体・gdmm API比較としては扱いません。

harnessは固定ソースのMD5を検査して許可した関数だけをparseします。classicとclassic-diffの公式関数式を実行し、do_scaleの `som::normalize` 呼出先だけを同じ固定somの純R関数へ束縛します。`plyr::ddply` の群平均は、完全な有限値・全factor水準が出現する条件に限定したbase R adapterです。このadapterも含めた限定検証であり、plyr自体、aquap2の初期化、dataset cleaning、試料数補正、SG/MSC、温度校正、描画、bootstrapは検証しません。

再実行には、次の3ファイルをUTF-8/LFのままダウンロードして同じフォルダーに置きます。ファイル全体のsource実行や自動package installは行いません。

- [calc_aqg.r](https://raw.githubusercontent.com/bpollner/aquap2/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r)
- [gen_coreDataManip.r](https://raw.githubusercontent.com/bpollner/aquap2/d31c1231bf71f0e73f1a630a32934602782be488/R/gen_coreDataManip.r)
- [som.R](https://raw.githubusercontent.com/cran/som/a56214b9583cea8e4f2856d28d9461072ec3d20c/R/som.R)

Workbenchで**全体平均を基準**として保存した同一結果のCSVを使用します。定数列・非有限値を含むデータは本harnessの対象外です。出力先は新しいフォルダーを指定します。

```sh
Rscript scripts/aquap2_reference.R <固定ソースのフォルダー> <展開root>/data/preprocessed.csv <展開root>/data/aquagram.csv <新しい出力フォルダー>
```

人工9試料×12波長（3群）でこの限定harnessを実行しました。全体基準からsample SDへ変換したclassicと、最初の群を引いたclassic-diffの計72値を照合し、最大絶対誤差はそれぞれ `4.44×10⁻¹⁵` と `3.11×10⁻¹⁵`（許容 `10⁻¹²`）でした。インストール済みaquap2/APIでの一致確認ではありません。

出力はclassic/classic-diffのCSVと、実行範囲・誤差・入力MD5を記録したRDS/TXTです。前処理済みCSVを使い、aquap2側のSG/MSCは無効にして二重処理を避けます。人工fixture、入力値・Workbench設定、固定ソースのGit blob SHA/SHA-256、結果の具体的証跡は `qa/v1.3-aquap2-comparison.json` に記録しました。この限定結果から実測データや温度校正Aquagramの互換性を推論しないでください。
