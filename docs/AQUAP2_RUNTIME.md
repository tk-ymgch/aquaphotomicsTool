# インストール済みaquap2のローカル実行

2026-10-22、Windows x64 / R 4.6.1で、公式aquap2 **0.4.5 / commit `d31c1231bf71f0e73f1a630a32934602782be488`** を依存込みで隔離導入し、実パッケージの公開APIによるPCAとclassic/classic-diffを実行しました。以前の限定source harnessとは別の検証です。温度校正・AUC・PLSはこのRエンジンの対象外です。

## 導入と隔離

導入先はプロジェクト内 `qa/aquap2-runtime-v1.4/library`。既存R libraryやシステム設定を変更せず、aquap2を含む147パッケージを配置しました。依存のWindows用バイナリは公式CRAN、aquap2は公式GitHubの固定コミットから取得しています。Rtools45も既存環境で検出しましたが、今回の依存はバイナリ、aquap2は純Rソースとして導入しました。[固定版のDESCRIPTION](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/DESCRIPTION)、[公式インストール案内](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/README.md)。

```powershell
$runtime = Join-Path (Get-Location) 'qa/aquap2-runtime-v1.4'
New-Item -ItemType Directory -Force -Path (Join-Path $runtime 'home') | Out-Null
$env:R_HOME = 'C:/Program Files/R/R-4.6.1'
$env:R_USER = Join-Path $runtime 'home'
$env:AQUAP2_RUNTIME_ROOT = $runtime
$env:AQUAP2_LIBRARY = Join-Path $runtime 'library'
# Windows Rが受理しないC.UTF-8のlocale指定を、この起動シェル内だけ解除
Get-ChildItem Env: | Where-Object { $_.Name -match '^(LC_|LANG$|LANGUAGE$)' } |
  ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
& 'C:/Program Files/R/R-4.6.1/bin/x64/Rscript.exe' --vanilla scripts/setup_aquap2.R
& 'C:/Program Files/R/R-4.6.1/bin/x64/Rscript.exe' --vanilla scripts/aquap2_engine.R --health
```

初回導入には公式CRAN/GitHubへのネット接続が必要です。このPCではsandbox内のDNSが失敗したため、許可された昇格実行で取得しました。通常の解析時にpackage installやダウンロードは行いません。固定ソースZIPのSHA-256は `22e6582a7205a723f0f70e3e3c91db272f3eefcb4eabb29023a9229091df0130`。`installation.json` に版・commit・導入済みDESCRIPTION/NAMESPACE/RDB/RDXのSHA-256を記録し、engine起動時に整合性を確認します。

`R_USER` はR起動前に隔離homeへ指定します。aquap2の `updateSettings` はHOME内の `.Renviron` を作成し得るため、engineは隔離home以外での解析を拒否します。環境変数を変更するのは子プロセスまたは起動シェル内のみです。API応答のruntimeにローカルパスは含めません。

## JSON契約

実行は `Rscript --vanilla scripts/aquap2_engine.R input.json output.json`。healthは `--health` のstdoutへJSONだけを返します。解析結果はoutput.jsonへUTF-8で保存し、ライブラリのログはstderrへ流します。エラー時は終了コード1、`ok:false,error:{code,message}` を返します。

```json
{
  "schemaVersion": 1,
  "matrix": [[0.1,0.2,0.3],[0.2,0.3,0.4],[0.3,0.4,0.5]],
  "wavelengths": [1342,1364,1374],
  "ids": ["001","002","003"],
  "groups": ["A","B","B"],
  "aquagram": {"wavelengths":[1342,1364,1374],"reference":"global"},
  "pca": {"components":2,"scale":false}
}
```

`matrix` はPython側で適用済みの**同一前処理済み行列**です。Rは補完や散乱補正を追加しません。IDを一意、波長を正の昇順・重複なし、全値を有限にし、AQの実波長を列に完全一致させます。上限は200万要素、10000波長、行列の短辺1000。PCA成分数は1～10かつ `min(試料数−1,波長数)` 以下です。R本体が全波長0の試料を削除する経路を避けるため、そのような行は明示的に拒否します。

- `reference:"global"` → `classic`。`reference:"group:対照群名"` → `classic-diff`。
- `none`、AUC/温度校正、PCA scale=true、PLS入力は非対応エラー。条件を自動変更しません。
- 応答は `schemaVersion,ok,pca,aquagram,runtime,warnings`。PCAはscores（試料×成分）、loadings（波長×成分）、explainedVariance（寄与率）、ids/groups。AQは実波長、元の群名・values・n、基準・定義・mode・ddof=1。
- runtimeには実パッケージ導入、版/commit、`packageApiExecuted:true`、`api:"aquap2::gdmm"`、公開getter、実際の設定、identity SGの丸め差を含めます。healthでは計算未実行なので `packageApiExecuted:false` です。

## 正式APIとidentity SGの制約

公式metadata/analysis procedureのテンプレートを要求ごとの隔離実験フォルダーへ置き、公開 `getmd`・`ttap` で正式 `aquap_data`、`getap` で正式 `aquap_ap` を作り、`gdmm` で `aquap_cube` を得ます。追加dpt、連続走査平均、noise、outlier除外、観測数補正、MSC、bootstrapはOFFです。PCAは `getcm(cube,1,"pca")$model`、AQは `getcm(cube,1,"aquagr")[[1]]@avg` から取得します。[gdmm](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/cube_generateDatasets.r#L1566-L1652)、[公開getcm](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/gen_general.r#L971-L988)。

**0.4.5では、説明書が示す `aqg.smoothN=NULL` をgdmmの入力検証が拒否します。** 関数の書換えや検証バイパスをせず、`aqg.smoothN=3` を使用します。classic内部のSGはp=2,m=0なので、3点2次の恒等変換ですが、実際にSG関数を呼ぶため浮動小数点の丸め差があります。各要求で `signal::sgolayfilt(p=2,n=3,m=0)` の効果を測定し、`runtime.identitySG` と `runtime.preprocessing` へ記録します。完全なSG OFFとは呼びません。[入力検証](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/cube_generateDatasets.r#L355-L357)、[classic内部](https://github.com/bpollner/aquap2/blob/d31c1231bf71f0e73f1a630a32934602782be488/R/calc_aqg.r#L35-L55)。

PCAは元の前処理済み行列を平均中心化してSVDします。寄与率はモデルの `var/totalvar`。classicのSDはddof=1で、Workbenchのddof=0との比較には `sqrt((n−1)/n)` の換算が必要です。詳しい定義は [AQUAP2_COMPARISON.md](AQUAP2_COMPARISON.md)。

## 検証済みの範囲

正式パッケージ/APIで、人工36×61（群9/12/15）のraw、SNV+SG、MSC+SGを、全体/対照群基準と組み合わせた6runが成功しました。PCAの符号整列後最大差 `4.36e-15`、AQのddof換算後最大差 `1.21e-13`、identity SG効果最大 `6.66e-16`。これは同じ前処理済み行列を渡した比較であり、aquap2独自の前処理全体をWorkbenchへ置き換えた検証ではありません。証跡は `qa/v1.4-aquap2-verification.json`。

実runtimeの独立smokeは次で明示実行します。

```powershell
python scripts/test_actual_aquap2.py --run
```

health、global/controlの正式API、ID/日本語群名/小数波長の保持、PCA再構成、SDの手計算、none/scale/不一致波長/PLSの拒否、通常要求のjobs残存0を確認します。7要求が成功し、AQ手計算との差 `6.66e-15`、PCA再構成差 `5.55e-16`。証跡は `qa/v1.4-runtime-smoke.json`。

通常要求のmatrix/cubeは永続保存しません。要求終了時に、検証したjobs配下の一時フォルダーを削除します。人工比較でmetadata/settings/dataset/cubeのRDS証跡が必要な場合だけ、**実行者が環境変数 `AQUAP2_KEEP_EVIDENCE=1` を指定**します。HTTPの測定値からこの設定を変更する仕組みはありません。

温度校正/AUC、PLS、実測研究データ、容量上限近傍、別OS/R版は未検証です。旧source harnessは歴史的な限定確認のまま保持し、この本体実行へ遡及して読み替えません。

## 保存と復元

依存の最新版取得だけでは後日の同一環境を保証できないため、固定版ソースZIP・導入receipt・依存版一覧と、導入済みlibrary全体のZIPを保存対象にします。Windows x64/R 4.6.1向けのlibraryであり、別OSへそのまま流用しません。`qa/aquap2-runtime-v1.4/` のアーカイブ・容量・全ファイルSHA-256は `runtime-archive-manifest.json` を参照してください。

復元時は空のruntimeへlibrary ZIPを展開し、receiptと必要スクリプトも戻し、同じR版で `--health` とopt-in smokeを実行します。archive内の全ファイルSHA一致と、復元先でのR実行確認は別の検査です。既存のRlibraryへ上書きせず、検証済みの元ランタイムは保持してください。
