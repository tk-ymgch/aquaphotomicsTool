# aquap2との比較定義・実行範囲・検証履歴（v1.4）

更新日: 2026-10-22。v1.4は、共通のPython前処理後の行列をインストール済みaquap2本体の公開API `aquap2::gdmm` へ渡す実行経路を追加しました。この文書では計算定義、現在の実行範囲、v1.3の限定source harnessを区別します。標準・旧Python互換の各6条件、合計12条件を本体APIと比較した数値を下記へ記録しています。実測データ、温度校正、AUCモードの数値一致を確認したものではありません。

比較の主基準は、旧セットアップと公式READMEが指定する `latestPublic` の **aquap2 0.4.5 / commit `d31c1231bf71f0e73f1a630a32934602782be488`** です。2026-10-21調査時の `master` は **0.5.1 / commit `57ee096fbecf28a321eed5884784e01b0bca036b`**。ブランチ名だけでは版が動くため、以下は固定コミットへリンクします。[0.4.5の版情報](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/DESCRIPTION)、[公式インストール案内](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/README.md)、[0.5.1の版情報](https://github.com/bpollner/aquap2/blob/57ee096fbecf28a321eed5884784e01b0bca036b/DESCRIPTION)。

## classic とWorkbenchの対応

| 項目 | aquap2 0.4.5 classic | Workbench Pythonの標準化Aquagram |
| --- | --- | --- |
| 前処理 | Aquagram内部で任意SG（p=2,m=0）→任意MSC | modern設定では散乱補正→必要なら等間隔補間→SG/微分 |
| 波長選択 | `which(wls %in% selWls)` の一致列 | 希望波長に最も近い列を許容誤差内で選択。実際の波長を保存 |
| 標準化 | 選択各波長で全試料を中心化しsample SD（ddof=1）で除算→群平均 | （群平均−全体平均または対照群平均）÷全試料population SD（ddof=0） |
| 対照群 | `classic-diff` がclassic値から指定群の値を差し引く | 対照群を基準に選択 |
| 基準なし | classicは中心化・標準化あり | 前処理後の群平均をそのまま表示。classicとは定義が違う |
| 既定座標の一部 | 1476 nm | 1478 nm。設定により変更可能 |

実装根拠は [classic / classic-diff の計算順](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L25-L55)、[do_scale](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/gen_coreDataManip.r#L302-L308)、[実際の波長選択と試料数補正](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L796-L832)、[aquap2既定座標](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/inst/settings.r#L206-L233) です。

`som::normalize(x, byrow=FALSE)` は `apply(x, 2, scale)` を呼びます。Rの `scale` は平均中心化後の平方和を `n−1` で割った平方根を使用するため、classicのSDは **ddof=1** です。コメント中の「scaleと違う」という記載だけからSD定義を判断していません。[som 0.3-5.2の固定ソース](https://github.com/cran/som/blob/a56214b9583cea8e4f2856d28d9461072ec3d20c/R/som.R#L285-L293)、[R公式scale仕様](https://search.r-project.org/R/refmans/base/html/scale.html)。

同じ前処理済み行列、同じ試料、同じ波長、欠損なし、定数列なしなら、全体基準のWorkbench Python値を `W` とするとclassicは `W × sqrt((n−1)/n)` になります。classic-diffも同じ係数で対照群との差に対応します。標準化→群平均と、群平均差→同じSDで除算は線形演算なので、**順序だけでは別の差を生みません**。これは条件をそろえた場合の式の対応であり、既定設定のアプリ同士や全前処理の互換性を示しません。0.5.1でもclassic・classic-diff・do_scaleの関数式はRでparseしたASTが0.4.5と同一でした。

## 温度校正を使うモード

aquap2既定モードは `aucs.dce` でありclassicではありません。`sfc` は校正スペクトルの平均を中心とする標準化、`aucs` 系は温度校正から得た面積比の最小・最大に対する百分率を使います。Workbenchはこれらの校正計算を実装していません。[モードの公式説明](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/man/calc_aqg_modes.Rd)、[既定値](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/inst/settings.r#L223-L234)。

- `sfc`: SG→任意MSC→座標抽出→校正平均を中心に `scale(...,center=avg,scale=TRUE)`→群平均。分母はその校正中心からの二乗偏差和を `n−1` で割った平方根で、試料自身の平均周りのSDと一般には同じではありません。[sfc](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L78-L99)、[校正平均を中心とする標準化](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/gen_coreDataManip.r#L310-L317)。
- `aucs`: 各試料で、座標の波長帯と両端の直線基線で閉じた多角形面積を全スペクトルの閉じた多角形面積で割る→群平均→校正最小・最大を用いて `(面積比−最小)×100/(最大−最小)`。**波長帯の単純な吸光度平均ではありません**。座標境界、第一倍音の範囲、校正用設定も必要です。[面積比](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L435-L480)、[百分率](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L500-L510)、[群平均の順](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L57-L64)。
- `aucs.tn` は測定温度に相当する校正百分率を差し引く。`aucs.dce` は百分率を校正温度範囲へ写像し、`aucs.tn.dce` は差を温度範囲の幅で換算する。`-diff` はさらに指定群差を取ります。[温度正規化とDCEの式](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L101-L158)。

温度校正データ、測定温度、校正範囲、前処理、aquap2固有のmetadata/settingsが必要です。欠損した校正温度ではloess補間を使う経路もあります。今回の人工データには実測の温度校正を付けておらず、この系統の数値比較は未実施です。[校正データと補間](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L529-L599)、[校正と前処理の注意](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/man/calc_aqg_args.Rd#L110-L115)。

## 公開APIとRへの接続地点

確認した両版の公開APIは `gdmm(dataset, ap=getap(), noiseFile="def", tempFile="def")` です。入力は `aquap_data`、解析手順は `aquap_ap`、出力は `aquap_cube`。`getcube` や `aquagram` という名前のexportは確認できません。[gdmmの正式引数](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/man/gdmm.Rd#L5-L34)、[公開名](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/NAMESPACE)。

Workbenchの `r_import.R` が保存するRDSは標準list/matrixで、aquap2のdatasetとは異なります。v1.4の `scripts/aquap2_engine.R` は別の実行経路です。前処理済み行列とID・群を `ttap` で `aquap_data` へ変換し、専用metadata・解析手順を作って `gdmm` を呼びます。`C_` / `Y_` ヘッダーと波長prefixを明示し、試料順を検証します。測定計画・温度校正を一般的に自動生成する変換ではありません。[公式変換ttap](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/man/ttap.Rd)、[R出力ガイド](R_AQUAP2.md)。実行ヘルパーが使うAPI設定の抜粋です。完全な取込・検証・結果抽出は `scripts/aquap2_engine.R` を参照してください。

```r
# fd は正式なaquap_data、metadata/analysis procedureの準備済み環境が前提
cube <- aquap2::gdmm(fd, ap = aquap2::getap(
  do.pca = TRUE, do.pls = FALSE,
  do.aqg = TRUE, aqg.vars = "C_Group", aqg.mod = "classic",
  aqg.smoothN = 3, aqg.msc = FALSE, aqg.nrCorr = FALSE,
  aqg.bootCI = FALSE,
  aqg.selWls = c(1342,1364,1374,1384,1412,1426,1440,1452,1462,1476,1488,1512)))
```

## v1.4の実行と比較範囲

Web UIではPythonまたはaquap2を選択します。aquap2は同じPCの `http://127.0.0.1:8787` で起動したRサービスへ明示接続します。送るのはPython前処理後の有限値行列、実波長、試料ID、群名、PCA/Aquagram条件です。元ファイル・目的変数は送りません。接続先や短期Bearerは設定・ZIPへ保存しません。起動・導入は[README](../README.md)と[実行環境](AQUAP2_RUNTIME.md)を参照してください。

- 共通前処理は標準／旧Python互換のPython計算です。aquap2自身のSG/MSCとの一般的な互換性を検証する経路ではありません。
- PCAはaquap2の平均中心化・分散スケーリングなしの実出力です。比較時は成分の符号を整列します。重複固有値の成分では回転等も起こり得るため、単純な点ごとの差だけで一般的互換性を判断しません。
- Aquagramは `classic`（全体）と `classic-diff`（指定対照群）です。Python側のddof=0からddof=1への換算を明示して比較し、実行時の比較CSVと `aquap2_comparison.json` に残します。
- PCA標準化、Aquagram基準なし、PLSは現在の接続経路で実行せず、UI/クライアントで止めます。温度校正・AUC/sfc/aucs.dce、bootstrap・試料数補正・外れ値除外も対象外です。

固定0.4.5は `aqg.smoothN=NULL` を公開APIの検証段階で拒否します。このため `smoothN=3` の3点・2次・微分0の恒等SGをAquagram内部で呼びます。数学上の恒等変換でも浮動小数点の丸め差はあり、各要求の最大差・許容内かどうかを `aquap2_runtime.json` の `identitySG` へ記録します。追加MSC、追加のデータ前処理、連続scan平均、ノイズ、試料数補正などは無効です。「R側で一切演算を追加しない」とは扱いません。

`metadata.execution` と `settings.json` のprovenanceは、前処理/PCA/Aquagramの実エンジン、aquap2/Rの版、公開API、実行済みフラグを記録します。接続確認はパッケージの版と利用可否の確認であり、解析成功の代わりにはなりません。

本体比較スクリプトは人工データだけを生成して `scripts/aquap2_engine.R` を実行し、source harnessへフォールバックしません。通常Pythonの解析依存と隔離R環境を準備し、毎回新しい出力先で実行します。

```powershell
python scripts/compare_aquap2.py --rscript 'C:/Program Files/R/R-4.6.1/bin/Rscript.exe' --r-runtime qa/aquap2-runtime-v1.4 --r-library qa/aquap2-runtime-v1.4/library --pipeline-mode modern --output qa/aquap2-package-new-modern
python scripts/compare_aquap2.py --rscript 'C:/Program Files/R/R-4.6.1/bin/Rscript.exe' --r-runtime qa/aquap2-runtime-v1.4 --r-library qa/aquap2-runtime-v1.4/library --pipeline-mode legacy-python --output qa/aquap2-package-new-legacy
```

各出力の `report.json` に入力・出力SHA-256、実行エンジン、API、比較範囲・除外・数値差を保存します。具体的なv1.4比較結果は確定したレポートと[検証記録](VALIDATION.md)を参照してください。v1.3で得た以下のharness誤差を本体/APIの検証値へ流用しません。

### v1.4本体比較の確認結果

`qa/v1.4-aquap2-verification.json`（標準方式）と `qa/v1.4-aquap2-legacy-verification.json`（旧Python互換）は、インストール済みaquap2 0.4.5、R 4.6.1、`aquap2::gdmm` を使った比較で、`sourceHarnessUsed=false` です。どちらも人工36試料×61波長、群サイズ9/12/15、正確に存在する12波長に限定しています。散乱補正なし・SNV＋SG・MSC＋SGと、全体基準・指定対照群の各6条件/24数値チェック、合計12条件/48チェックが許容内で通りました。旧Python互換ではその方式のSG→散乱補正順で作った同一行列を比較しています。

| 確認項目 | 標準方式6条件の最大絶対差 | 旧Python互換6条件の最大絶対差 |
| --- | ---: | ---: |
| PCA（対応成分の符号整列後、スコア・負荷量・寄与率） | 4.36×10⁻¹⁵ | 3.98×10⁻¹⁵ |
| Aquagram（母SD→標本SDを明示換算後） | 1.21×10⁻¹³ | 1.51×10⁻¹³ |
| Aquagram（SD換算なし、参考値） | 0.02230 | 0.02230 |
| Aquagram内部の恒等SGによる丸め効果 | 6.66×10⁻¹⁶ | 6.66×10⁻¹⁶ |

比較判定は絶対許容1×10⁻⁷、相対許容1×10⁻⁶を使います。換算なしの差を隠して同一値と扱っていません。これは通常Pythonと本体APIの条件限定比較で、実測試料、aquap2独自前処理、温度校正やAUCの一般的な互換性を検証した記録ではありません。

別途、ローカルブラウザーの人工45×61によるaquap2実行・結果ZIPを再計算し、`qa/v1.4-browser-export-verification.json` が成功しています。前処理最大差2.00×10⁻¹⁵、符号整列後PCAの最大差3.97×10⁻¹⁴、AQのSD換算後8.06×10⁻¹⁴で、6図PNGと本体実行provenanceを確認しました。非対応設定の実行停止と、両エンジンの条件比較ZIP保存もUIで確認しています。公開サイトとローカルRの接続確認は、このローカルブラウザー確認とは区別します。R 4.6.1 runtime ZIPの別復元先での確認は作業中で、完了扱いにしていません。

## v1.3の履歴：限定source harness

以下は2026-10-21の旧検証記録で、v1.4本体/API比較とは別です。当時R 4.6.1は起動しましたがaquap2と主要依存は未導入でした。ワークスペース内の隔離libraryへのsom/plyr導入を試したところ、CRAN indexのDNS解決に失敗しました。既存R libraryは変更していません。`scripts/aquap2_reference.R` は、この状況で式を調べるための**限定source harness**です。インストール済みaquap2本体・gdmm API比較としては扱いません。

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

出力はclassic/classic-diffのCSVと、実行範囲・誤差・入力MD5を記録したRDS/TXTです。このsource harnessは前処理済みCSVに限定した関数式だけを適用し、SG/MSCを実行しません。v1.4の公開APIによる恒等SGとは異なる経路です。人工fixture、入力値・Workbench設定、固定ソースのGit blob SHA/SHA-256、結果の具体的証跡は `qa/v1.3-aquap2-comparison.json` に記録しました。この限定結果から実測データや温度校正Aquagramの互換性を推論しないでください。
