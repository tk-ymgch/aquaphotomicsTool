# aquap2pyの対応範囲と完全互換の判定基準

`aquap2py 0.2.0` は **aquap2の非公式Python互換実装**です。対象はRパッケージ **aquap2 0.4.5 / commit `d31c1231bf71f0e73f1a630a32934602782be488`**。温度校正とPLS1の限定実装を追加しましたが、全機能の移植完了を意味しません。機械可読の正本は [coverage.json](../python/aquap2py/coverage.json) で、`completeCompatibility:false` を維持します。

## 棚卸しの母数

固定ソースをRでparseし、導入済みの同版namespaceとも照合しました。

| 対象 | 数 | 意味 |
| --- | ---: | --- |
| `export(...)` | 46 | 明示export関数。gfd/esl等の別名も各入口として含む |
| `exportMethods(...)` | 18 | 名前付きgeneric 13と演算子5。関数exportと合わせ64宣言入口 |
| 実namespaceの可視名 | 59 | 46関数＋13名前付きgeneric |
| 実namespaceのdispatch内部表 | 20 | `.__T__...`。利用者向けAPI数には加算しない |
| トップレベル関数定義 | 490 | 内部helperを含む。64入口の実装だけで全分岐を満たすわけではない |
| `setMethod`等の定義 | 68 | showや追加演算子も含む。宣言入口とは別に振舞いを検証する |
| S4 class / class union | 9 / 6 | dataset、metadata、analysis、cube/set、AQ、merge-label等の構造 |

根拠: [NAMESPACE](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/NAMESPACE)、[class/method定義](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/cl_classDefs.r)。再実行可能な棚卸しと全関数の元位置・formal argumentsは `qa/aquap2py-audit/inventory.R` / `r-inventory.json` にあります。

64入口はcoverage.jsonの `apiEntries` に欠落なく列挙しています。`status` は `not-implemented` / `partial` / `implemented`。API名があるだけ、あるいは非対応エラーを返すだけではimplementedに数えません。`features` は現在46のbehavior群を管理し、実装状態とR本体照合状態を別の軸にしています。

Python bindingは `ttap/gdmm/getcm`、およびRの `do_snv/do_msc/do_sgolay/do_dptSeq` に対応する `snv/msc/sgolay/preprocess` です。0.2.0では `temperature_calibration/temperature_aquagram/plsr/predict_plsr` を追加しました。`predict_plsr` は `plot_pls_indepPred` の数値予測部分だけに対応し、R描画APIを置換しません。異なる関数名・matrix/構造化引数による部分対応を、各entryの `pythonBinding` とnotesに記録します。

## 主要機能のマトリクス

| 分野 | 元の機能 | 0.2.0の対応/不足 |
| --- | --- | --- |
| dataモデル | aquap_data/aquap_md/aquap_ap/aquap_set/aquap_cube等、S4 slot・版・header/colRep | 簡略matrix/ID/群/波長、単一setのみ。全S4/metadata互換ではない |
| pipeline | gdmm/getap/getmd、class/波長分割、連続走査平均、noise、outlier、dpt.pre/post | sgol/snv/msc、PCA、AQ、PLS1の単一set限定経路。全cube組合せなし |
| 前処理 | SG/SNV/MSC/EMSC/gapDer/detrend/resample/平均 | 初版はSG(ts=1)、SNV標本SD、MSCを対象。外部modelやmetadata保持を含む全契約なし |
| 波長選択 | selectWls、siWl、siWlg、区間平均 | Python側の全API互換は未実装 |
| dataset編集 | ssc、merge、変数の計算/結合、代入/減算/除算 | header/波長不一致policy、任意R式、演算子全挙動は未実装 |
| 実験計画 | 時間点/階層class/反復/連続走査/対照、sample list、noise/温度実験生成 | 未実装 |
| raw IO | Vision NSAS、tab-delimited、Pirouette、xlsx、custom importer、header/TRH照合 | 現WorkbenchのCSV/Excel読込は正式readSpectra/getFullData互換を意味しない |
| 保存 | R-dataのsave/load、版/metadata/解析手順の往復 | 未実装。既存のbase R引継ぎ用RDSとは別 |
| PCA | 平均中心化SVD、scores/loadings/var/totalvar | mean-centered/unscaledの数値部分を対象。符号・縮退部分空間は別途判定 |
| AQ classic | 標準化後群平均、classic-diff | 標本SD(ddof=1)、AQ内のidentity SG3を含む限定経路を対象 |
| AQ校正系 | sfc/aucs/tn/dceと各diff、温度校正/loess/座標、bootstrap/CI | 10モード・12/15帯・観測済端点/Texp。LOESS、bootstrap/観測数補正、outlier検出は未対応 |
| PLSR | CV/LOO/class分割、反復adjCV成分選択、outlier、独立予測 | PLS1/kernelpls、中心化・非スケーリング、固定/自動成分、LOO/群単位CV、処理済X予測。outlier除外、全method、R RNG互換なし。Workbench nested PLSは別方式 |
| SIMCA/分類 | classic/robust SIMCA、lda/qda/fda/mclustda/RF/SVM/nnet、CV/holdout/独立予測 | 未実装 |
| 描画 | PCA/AQ/PLS/SIMCA/分類の図表、polar/linear、CI、PDF/XLS | Workbenchの図を出すことはR描画API全互換ではない |
| 維持helper | folder/settings/サンプル導入/更新、標準列名 | Pythonでの対応方針・全動作は未実装 |

元のモード・列挙値は [gen_possibleValues.r](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/gen_possibleValues.r)、入出力は [getFullData](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/prep_importData.r#L617)、モデル計算は [cube_makeModels](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/cube_makeModels.r) を根拠にしています。

AQの12モードは `classic`, `classic-diff`, `sfc`, `sfc-diff`, `aucs`, `aucs-diff`, `aucs.tn`, `aucs.tn-diff`, `aucs.tn.dce`, `aucs.tn.dce-diff`, `aucs.dce`, `aucs.dce-diff`。各モードを別featureとして記録します。AUCは基線で閉じた多角形面積比と校正範囲を使い、`siWlg(avg=TRUE)` の区間内算術平均とは別です。[AQ本体](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r)、[siWlg](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/gen_general.r#L1154)。

上流のdpt名には `osc` がありますが、0.4.5本体も「no osc yet」のplaceholderです。実OSCが上流で実装済みであるかのように移植率へ数えません。[該当箇所](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/cube_generateDatasets.r#L1109-L1112)。また、説明と実動作が違うケース（AQのsmoothN=NULL拒否など）は既知差分として固定し、意図した修正と互換動作を区別します。

他にも上流 `do_blowup(cst=...)` は連続走査を同時に保つ処理が未実装で引数を無視し、分類独立予測のXLS出力は `toxls=FALSE` に固定されています。宣言・説明・実動作を分け、これらも「上流にある完成機能」として数えません。[cstの説明](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/gen_coreDataManip.r#L696-L697)、[分類予測のXLS分岐](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/plot_classif_gen.r#L424-L431)。

## 完全対応をtrueにできる条件

1. **固定した母数**: 64宣言入口、68 method定義、46 behavior群の全分岐に対応する。alias/default/type/shape/順序/label/属性のR→Python対応を明記する。0.5.1の追加機能を混ぜて0.4.5を実装済みと数えない。
2. **正式APIをoracleにする**: 同一の人工fixtureと設定から、インストール済み固定R packageを公開APIで実行する。切り出したR関数や独立式の確認は補助証跡に分ける。前処理そのものもRと比較し、同一前処理済Xの比較だけで全pipelineをverifiedにしない。
3. **数値と構造**: SDの自由度・中心・計算順、SGの端点/ts/微分、MSC参照、波長の完全一致と区間、PCAの寄与率/再構成/符号・縮退部分空間、PLSRの成分選択/CV/独立予測まで検証する。数値許容誤差を事前に定める。
4. **異常系・確率系**: 欠損/Inf/定数列/全0行、少数試料・群、重複ID/波長、非等間隔、予約語/日本語、metadata不整合を含める。sampling/bootstrap/CVはR乱数との同一性を約束する範囲と統計的同等性を分け、seedを揃えただけで一致とみなさない。
5. **IO/metadata/描画**: 各raw format・sample-list/TRH・R-dataの実fixture、metadata/解析手順の往復、merge/演算の属性保持、全modelの図表/保存内容を確認する。R式をPython evalへ無条件で渡すような代替を互換実装とはしない。
6. **R非依存の実行**: native実行経路にRscript/rpy2/ローカルR service呼出しを必要としない。Rは開発時oracleとして分離する。library互換、ブラウザー実行、UIでの操作可能範囲を別に記録する。
7. **再現記録と配布条件**: 全実装featureにreportId/条件/版/データSHA/誤差/除外を紐付ける。ライセンス本文・原著作者・参照/移植箇所・変更日・依存の条件を保存する。未検証または未実装が残ればglobal flagをfalseにする。

`oracleValidation.status:"verified"` は、そのfeatureの `scope` に書いた条件だけを意味します。`implemented:true` は科学的有効性や全入力の検証済みを意味しません。R接続版の既存6runや旧Python互換54条件を、native aquap2pyの検証へ転用して表示しません。

## 0.2.0の基礎数値の実R照合

現版0.2.0のnative移植を、インストール済みの固定aquap2 0.4.5の公開 `gdmm` APIと再比較しました。両方へ同じ**生の人工matrix（24試料×61波長、不均等3群）**を渡し、R側も `dpt.pre` で前処理しました。限定source harnessやSD換算は使っていません。12条件・60数値checkが事前の許容差 `atol=1e-8 / rtol=1e-7` 内です。正本は `qa/v1.6-classic-verification.json`、入力/出力とSHAは `qa/v1.6-classic-oracle-verified/` にあります。

照合した前処理は、SGのp2/n21/m0とp2/n11/m0・1・2（端点・ts=1を含む）、SNV、全試料平均参照MSC、SGとSNV/MSCの両順序です。不等間隔は補間せず列位置で計算しました。PCAは平均中心化・非標準化の先頭5成分を符号整列し、寄与率も比較しました。AQはclassic/classic-diff、12実波長、内部SG3・内部MSCなしの明示profileです。最大絶対差は前処理 `1.0436e-14`、PCA scores `1.2088e-14` / loadings `1.0957e-13` / 寄与率 `7.7716e-16`、AQ `2.7089e-13` でした。

試料ID・群・波長の往復/行順、予約名global・日本語・引用符・改行labelsを確認し、定数SNVと同一スペクトルの2退化条件は双方の拒否を確認しました。この確認はRの全S4/metadata/error契約の互換を意味しません。未照合のSG次数/窓、MSC外部参照/model、近接・縮退PCA、実測データは対象外です。0.2.0は下記を含む21機能を条件限定でverified、64入口中8をpartial、56を未実装としています。全体の完全互換flagはfalseです。

通常のPython/ブラウザー解析はRを呼びません。開発時のoracle結果があることと、今回読み込んだ入力をRへ送って照合したことは別で、実行記録の `currentRunComparedWithR` はfalseです。各現版reportが記録した数値sourceと人工入出力のSHAを確認しています。旧 `qa/v1.5-aquap2py-verification.json` と `qa/aquap2py-audit/apply-oracle-validation.py` は0.1.0 snapshot専用の履歴で、その古い全source SHAを現版の全コード一致や再検証とは扱いません。

## 温度校正・AUC/sfcの照合

`qa/v1.6-temperature-verification.json` は0.2.0、26条件・1,026 scalar値、事前の `atol=1e-8/rtol=1e-7` でPASSです。R公開 `ttap→saveAQdata→gdmm→getcm` による人工測定12×301、校正63×301を使い、10モード×12/15座標、sfc内部MSC、TCalibの全範囲/対称指定、不等間隔・名目band端点欠落を含みます。最大絶対差 `2.5206e-8`、等間隔24条件では `9.0564e-10`。source harnessやR関数patchは使っていません。

校正はSG17→1300〜1600nm cut→温度別平均→面積比。測定はSG21→行別帯面積/全幅面積→群平均→校正2端点min/maxで%化です。範囲内の全温度からmin/maxを探す方式ではありません。帯境界を補間せず、R実装の名目境界yと内側実波長xによる閉多角形を再現します。tnはTexp校正%を減算、dceは温度幅で℃相当へ換算、diffは指定群差です。AUCにはSD除算がなく、sfcは未平滑化校正平均を中心とする測定二乗和/(n−1)の平方根を使います。[固定AQソース](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L57-L197)、[sfcのscale](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/gen_coreDataManip.r#L310-L317)。

TCalib両端・Texpは観測済温度に完全一致する初版profileです。Rのrobust quadratic LOESSをnp.interpやLOWESSで代用しません。LOESS、bootstrap/観測数補正、outlier検出は未実装。sfcは測定格子と校正cut格子の一致が必要です。DCEは実温度の推定ではなく、校正面積比の尺度です。0〜100%範囲外をclipしません。分母が小さい校正の丸め誤差増幅も区別し、初期狭帯profileの大きな絶対差を良好な校正と読み替えません。

## aquap2方式PLSRの照合

`qa/v1.6-plsr-verification.json` は13条件・420数値チェックが `atol=1e-8/rtol=1e-8` 内、最大絶対差 `4.9977e-10` です。420は配列・指標のチェック件数で、420 scalar値という意味ではありません。公開 `gdmm` と `plot_pls_indepPred` を実行し、native前処理、model/modelPlusの係数・intercept・fit/residual・CV/adjCV予測・PRESS・誤差曲線、処理済未知Xの予測、固定/自動成分を比較しました。

PLS1/kernelpls、中心化・非スケーリング、LOO/leave-one-group-outを対象とし、前処理は全Xへ適用してからCVします。反復adjCV最小成分の最頻値で自動選択するaquap2経路で、学習区画内前処理と外側nested CVの独立性能評価ではありません。乱数CVの固定成分1条件は、Rが書き出した具体的segmentsを再生して比較しています。同じR seedの系列互換、乱数CVでの全自動選択履歴、PLSR固有outlier除外、多応答/他method、未知raw Xへの自動前処理は未対応です。[固定PLSRソース](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_plsr.r)。

## 0.5.1との区別

参考版0.5.1は commit `57ee096fbecf28a321eed5884784e01b0bca036b`。53関数＋18 method宣言で、0.4.5に対して関数9追加・2削除です。追加は `ap2_settings_setup`, `ap2dme`, `aquap2_handover_to_uniset`, `export_ap2_ToXlsx`, `export_header_toXls`, `getstn`, `importExport_raw_toXls`, `sampleList_multiplyRows`, `testUniset`。削除は `instAquap2Examples`, `updateAquap2`。[0.5.1 NAMESPACE](https://github.com/bpollner/aquap2/blob/57ee096fbecf28a321eed5884784e01b0bca036b/NAMESPACE)。

0.5.1にはunisetによるsettings、sample-list xlsx化、metadata/IOの改修、新raw formatなどが記載されています。GitHub比較はdiverged（0.5.1側ahead49/behind15）で、latestPublicとmasterを単純な一直線の版と扱いません。classic/classic-diff/do_scaleの関数式が同一であることは、他のAPI/IOまで同じである根拠にはなりません。[0.5.1 NEWS](https://github.com/bpollner/aquap2/blob/57ee096fbecf28a321eed5884784e01b0bca036b/NEWS.md)、[固定commit間比較](https://github.com/bpollner/aquap2/compare/d31c1231bf71f0e73f1a630a32934602782be488...57ee096fbecf28a321eed5884784e01b0bca036b)。0.5.1実装コードは今回の0.4.5-based portへ組み込んでいません。

## LICENSE/NOTICE

新実装は **GPL-2.0-or-later** とし、[LICENSE](../python/aquap2py/LICENSE) にR標準配布物のGPL-2原文をそのまま保存しました。[NOTICE](../python/aquap2py/NOTICE.md) に非公式移植、原著作者Bernhard Pollner/Zoltan Kovacs、固定ソース、参照した関数、変更日、未実装範囲を記録します。原本0.4.5のDESCRIPTIONは `GPL (>=2)`、参考0.5.1は `GPL (>=3)` です。[0.4.5 DESCRIPTION](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/DESCRIPTION)、[0.5.1 DESCRIPTION](https://github.com/bpollner/aquap2/blob/57ee096fbecf28a321eed5884784e01b0bca036b/DESCRIPTION)。

signal1.8-1/pls2.9-0は `GPL-2`、MASS7.3-65は `GPL-2 | GPL-3`、oracleのgeometry0.5.2は `GPL (>=3)` と原記載どおり区別します。新polygon計算はNumPyで数学的shoelace式を独立に表現し、geometryコードの逐語コピー・同梱・実行は行いません。LOESSコードも実装へ取り込んでいません。数式参照と元コードのコピー/翻訳・再配布を同一視せず、個別notice保持・変更日・license本文・対応sourceを配布時に確認します。無条件のライセンス互換や法的適合を保証する記録ではありません。[GPL-2原文](https://www.r-project.org/Licenses/GPL-2)。旧基礎監査のDESCRIPTION SHAは `qa/aquap2py-audit/license-evidence.json`、新参照箇所はNOTICEにあります。
