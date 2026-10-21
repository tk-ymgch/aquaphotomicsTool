import { useMemo, useState } from 'react';
import { ArrowUpRight, ChevronRight, CircleHelp, FlaskConical, Layers2, RotateCcw, SlidersHorizontal, Trash2 } from 'lucide-react';
import type { AnalysisConfig, AnalysisResult, ComparisonRun, DatasetSummary, PLSConfig, PLSResult } from './types';
import Plot from './Plot';
import type { Figure } from './Plot';
import './advanced.css';

const COLORS = ['#222222', '#747474', '#a5a5a5', '#484848', '#c1c1c1', '#898989'];
const DASHES = ['solid', 'dash', 'dot', 'dashdot', 'longdash', 'longdashdot'];
const SYMBOLS = ['circle', 'square', 'diamond', 'triangle-up', 'cross', 'triangle-down'];
const number = (value: number | undefined, precision = 4) => typeof value === 'number' && Number.isFinite(value) ? Number(value.toPrecision(precision)).toLocaleString('ja-JP', { maximumSignificantDigits: precision }) : '—';
const percent = (value: number) => Number.isFinite(value) ? `${(100 * value).toFixed(1)}%` : '—';
const time = (value: string) => Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : value;

function chartLayout(title: string, x = '', y = ''): Record<string, any> {
  return { title: { text: title, x: .035, xanchor: 'left', font: { size: 12, color: '#777' } }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(255,255,255,0)', font: { family: 'Arial, "Noto Sans JP", sans-serif', size: 11, color: '#555' }, margin: { l: 75, r: 30, t: 65, b: 65 }, xaxis: { title: { text: x, standoff: 18 }, gridcolor: '#ebebeb', linecolor: '#d8d8d8', zerolinecolor: '#bcbcbc', showline: true }, yaxis: { title: { text: y, standoff: 16 }, gridcolor: '#ebebeb', zerolinecolor: '#bcbcbc' }, legend: { orientation: 'h', x: 0, y: 1.1, font: { size: 10 } }, hovermode: 'closest', hoverlabel: { bgcolor: '#fff', bordercolor: '#ddd', font: { color: '#222', size: 11 } }, uirevision: title };
}

function oofFigure(result: PLSResult): Figure {
  let min = Infinity, max = -Infinity;
  for (const values of [result.observed, result.predictedCV]) for (const value of values) if (Number.isFinite(value)) { min = Math.min(min, value); max = Math.max(max, value); }
  if (!Number.isFinite(min)) { min = 0; max = 1; }
  const pad = Math.max((max - min) * .07, Math.abs(max) * .01, .001), range = [min - pad, max + pad];
  const groups = [...new Set(result.groups)];
  return { data: [{ type: 'scatter', mode: 'lines', x: range, y: range, name: '観測値 = 予測値', line: { color: '#b9b9b9', width: 1, dash: 'dash' }, hoverinfo: 'skip', showlegend: false }, ...groups.map((group, gi) => {
    const indices = result.ids.map((_, i) => i).filter(i => result.groups[i] === group);
    return { type: 'scatter', mode: 'markers', name: group || '全試料', x: indices.map(i => result.observed[i]), y: indices.map(i => result.predictedCV[i]), customdata: indices.map(i => result.ids[i]), text: indices.map(i => `外側fold ${result.fold[i]}`), marker: { color: COLORS[gi % COLORS.length], size: 8, symbol: SYMBOLS[gi % SYMBOLS.length], opacity: .82, line: { color: '#fff', width: 1 } }, hovertemplate: '%{customdata}<br>観測値 %{x:.5g}<br>OOF予測値 %{y:.5g}<br>%{text}<extra></extra>' };
  })], layout: { ...chartLayout('OUT-OF-FOLD PREDICTIONS', `${result.targetColumn} · 観測値`, `${result.targetColumn} · 外側OOF予測値`), xaxis: { ...chartLayout('').xaxis, title: { text: `${result.targetColumn} · 観測値`, standoff: 18 }, range }, yaxis: { ...chartLayout('').yaxis, title: { text: `${result.targetColumn} · 外側OOF予測値`, standoff: 16 }, range, scaleanchor: 'x', scaleratio: 1 } } };
}

/** These exact figures are shared by the display and the parent's PNG exporter. */
export function plsFigures(result: PLSResult): Record<string, Figure> {
  const residuals: Figure = { data: [...new Set(result.groups)].map((group, gi) => {
    const indices = result.ids.map((_, i) => i).filter(i => result.groups[i] === group);
    return { type: 'scatter', mode: 'markers', name: group || '全試料', x: indices.map(i => result.predictedCV[i]), y: indices.map(i => result.residuals[i]), customdata: indices.map(i => result.ids[i]), text: indices.map(i => `外側fold ${result.fold[i]}`), marker: { color: COLORS[gi % COLORS.length], size: 8, symbol: SYMBOLS[gi % SYMBOLS.length], opacity: .8, line: { color: '#fff', width: 1 } }, hovertemplate: '%{customdata}<br>OOF予測値 %{x:.5g}<br>残差 %{y:.5g}<br>%{text}<extra></extra>' };
  }), layout: { ...chartLayout('OUT-OF-FOLD RESIDUALS', `${result.targetColumn} · 外側OOF予測値`, '残差 · 観測値 − OOF予測値'), shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: '#aaa', width: 1, dash: 'dash' } }] } };
  const curve: Figure = { data: [{ type: 'scatter', mode: 'lines+markers', name: '最終モデルの内側CV', x: result.curve.map(row => row.components), y: result.curve.map(row => row.rmseCV), line: { color: '#4c4c4c', width: 1.8 }, marker: { color: result.curve.map(row => row.components === result.selectedComponents ? '#111' : '#999'), size: result.curve.map(row => row.components === result.selectedComponents ? 10 : 6) }, hovertemplate: '%{x} 成分<br>内側RMSECV %{y:.5g}<extra>性能評価のOOF値とは別です</extra>' }], layout: { ...chartLayout('FINAL MODEL · INNER CROSS-VALIDATION', 'PLS成分数', '内側CVのRMSE'), xaxis: { ...chartLayout('').xaxis, title: 'PLS成分数', dtick: 1 }, shapes: [{ type: 'line', x0: result.selectedComponents, x1: result.selectedComponents, yref: 'paper', y0: 0, y1: 1, line: { color: '#aaa', width: 1, dash: 'dot' } }], showlegend: false } };
  const coefficients: Figure = { data: [{ type: 'scatter', mode: 'lines', x: result.coefficients.wavelengths, y: result.coefficients.values, name: '回帰係数', line: { color: '#353535', width: 1.7 }, hovertemplate: '%{x:.2f} nm<br>回帰係数 %{y:.6g}<extra>最終モデル</extra>' }], layout: { ...chartLayout('FINAL MODEL · REGRESSION COEFFICIENTS', '波長 / nm', '回帰係数'), showlegend: false } };
  return { pls_oof: oofFigure(result), pls_residuals: residuals, pls_components: curve, pls_coefficients: coefficients };
}

export function PLSSettings({ summary, config, onChange, disabled }: { summary: DatasetSummary; config: AnalysisConfig; onChange: (value: PLSConfig) => void; disabled: boolean }) {
  const value: PLSConfig = config.pls ?? { enabled: false, targetColumn: summary.columns.includes('synthetic_target') ? 'synthetic_target' : summary.columns.includes('target') ? 'target' : null, maxComponents: 5, folds: 5, split: 'kfold', cvGroupColumn: null, seed: 20261021, scale: true };
  const waveColumns = new Set(summary.wavelengthColumns.map(column => column.column));
  const otherColumns = summary.columns.filter(column => !waveColumns.has(column));
  const isNumeric = (column: string) => {
    const index = summary.columns.indexOf(column);
    const available = summary.preview.map(row => row[index]).filter(item => item !== null && item !== undefined && item !== '');
    return available.length > 0 && available.every(item => (typeof item === 'number' || typeof item === 'string') && Number.isFinite(Number(item)));
  };
  const numericColumns = otherColumns.filter(column => column !== config.idColumn && column !== value.cvGroupColumn && isNumeric(column));
  const update = <K extends keyof PLSConfig>(key: K, next: PLSConfig[K]) => onChange({ ...value, [key]: next });
  return <section className="glass-panel adv-settings-panel">
    <div className="adv-section-heading"><span className="step-index">04</span><div><h2>PLS回帰</h2><p>数値の目的変数を、前処理後のスペクトルから予測します。</p></div><span className="adv-optional">任意</span></div>
    <fieldset disabled={disabled}>
      <label className="adv-enable"><input type="checkbox" checked={value.enabled} onChange={event => update('enabled', event.target.checked)} /><span><strong>PLS回帰を実行する</strong><small>ネストした交差検証で成分数選択と性能評価を分離</small></span></label>
      <fieldset className="adv-pls-fields" disabled={disabled || !value.enabled}>
        <div className="adv-form-grid adv-grid-three">
          <label className="adv-field adv-target"><span>目的変数の列</span><select value={value.targetColumn ?? ''} onChange={event => update('targetColumn', event.target.value || null)}><option value="">数値列を選択</option>{numericColumns.map(column => <option key={column} value={column}>{column}</option>)}{value.targetColumn && !numericColumns.includes(value.targetColumn) && <option value={value.targetColumn} disabled>{value.targetColumn}（列の設定を確認）</option>}</select><small>試料ID・CV群・波長列を除く、プレビュー上の数値列を表示。全行は解析時に検証します。</small></label>
          <label className="adv-field"><span>成分数の上限</span><input type="number" min={1} max={10} step={1} value={value.maxComponents} onChange={event => update('maxComponents', Number(event.target.value))} /><small>1–10成分。内側CVで選択します。</small></label>
          <label className="adv-field"><span>外側CVの分割数</span><input type="number" min={2} max={10} step={1} value={value.folds} onChange={event => update('folds', Number(event.target.value))} /><small>2–10分割。未学習試料を評価します。</small></label>
          <label className="adv-field"><span>分割方法</span><select value={value.split} onChange={event => onChange({ ...value, split: event.target.value as PLSConfig['split'], cvGroupColumn: event.target.value === 'group' ? value.cvGroupColumn : null })}><option value="kfold">KFold · 行単位</option><option value="group">GroupKFold · 個体・試料単位</option></select></label>
          <label className="adv-field"><span>CV群の列</span><select disabled={value.split !== 'group'} value={value.cvGroupColumn ?? ''} onChange={event => update('cvGroupColumn', event.target.value || null)}><option value="">個体ID・試料IDなどを選択</option>{otherColumns.filter(column => column !== value.targetColumn).map(column => <option key={column} value={column}>{column}</option>)}</select><small>同じ値の行は、学習側と評価側に分かれません。</small></label>
          <label className="adv-field"><span>乱数シード</span><input type="number" min={0} max={2147483647} step={1} value={value.seed} onChange={event => update('seed', Number(event.target.value))} /><small>同じ条件での分割の再現に使用</small></label>
        </div>
        <label className="adv-check"><input type="checkbox" checked={value.scale} onChange={event => update('scale', event.target.checked)} /><span>PLS内で波長ごとに標準化する<small>平均中心化は常に適用。PCAの標準化設定とは独立です。</small></span></label>
      </fieldset>
      <div className="adv-method-note"><CircleHelp size={15} /><p><strong>成分数の選択と予測性能の評価</strong>外側foldの学習データ内で成分数を選択し、そのモデルで外側の未学習試料を予測します。性能指標には外側OOF予測を使用し、全データで作る最終モデルの校正値とは区別します。</p></div>
      <p className="adv-repeated-note">反復測定がある場合はGroupKFoldを選び、同一個体・同一試料を識別する列をCV群に指定してください。表示上のグラフの群分けとは別の設定です。</p>
    </fieldset>
  </section>;
}

const PLS_VIEWS = [
  { key: 'pls_oof', label: 'OOF予測', title: '外側交差検証の予測値', caption: '各試料を学習に使わなかった外側モデルの予測です。破線は観測値と予測値が等しい位置を示します。' },
  { key: 'pls_residuals', label: '残差', title: '外側OOF予測の残差', caption: '残差は観測値 − OOF予測値です。ゼロ付近の偏りと予測値に依存する傾向を確認します。' },
  { key: 'pls_components', label: '成分数の選択', title: '最終モデルの成分数選択', caption: '全データで最終モデルを作る際の内側CV曲線です。この曲線の最小値を外側OOFの予測性能として扱いません。' },
  { key: 'pls_coefficients', label: '回帰係数', title: '最終モデルの回帰係数', caption: '前処理後の説明変数に対する係数です。値の大きさは前処理とPLSの標準化条件に依存します。' },
] as const;

export function PLSResults({ result, onSelect }: { result: PLSResult; onSelect?: (id: string) => void }) {
  const [active, setActive] = useState<(typeof PLS_VIEWS)[number]['key']>('pls_oof');
  const figures = useMemo(() => plsFigures(result), [result]);
  const current = PLS_VIEWS.find(item => item.key === active)!;
  const cards = [
    { title: 'RMSECV', value: number(result.metrics.rmseCV), note: '外側OOF予測' },
    { title: 'MAE', value: number(result.metrics.maeCV), note: '外側OOF予測' },
    { title: 'R²', value: number(result.metrics.r2CV), note: '外側OOF予測' },
    { title: '基準モデルのRMSE', value: number(result.metrics.baselineRmseCV), note: '外側学習データの目的変数平均' },
    { title: '最終モデルの成分数', value: String(result.selectedComponents), note: '全データの内側CVで選択' },
  ];
  return <div className="adv-pls-results">
    <div className="adv-result-context"><span><strong>目的変数</strong> {result.targetColumn}</span><span>{result.method === 'nested-group-kfold' ? 'Nested GroupKFold' : 'Nested KFold'}<i />外側 {result.folds} 分割<i />内側 最小 {result.innerFolds} 分割<i />n = {result.ids.length}</span></div>
    <div className="adv-metric-grid">{cards.map(card => <section className="glass-panel adv-metric" key={card.title}><h2>{card.title}</h2><strong>{card.value}</strong><p>{card.note}</p></section>)}</div>
    {result.warnings.length > 0 && <details className="warnings"><summary>PLS解析時の確認事項 <span>{result.warnings.length}</span><ChevronRight size={13} /></summary><ul>{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
    <section className="glass-panel adv-pls-chart"><div className="adv-chart-toolbar"><div className="segmented" aria-label="PLSグラフの切り替え">{PLS_VIEWS.map(item => <button key={item.key} aria-pressed={active === item.key} onClick={() => setActive(item.key)}>{item.label}</button>)}</div><span>目的変数：{result.targetColumn}</span></div><div className="adv-chart-caption"><h2>{current.title}</h2><p>{current.caption}</p></div><Plot figure={figures[active]} label={current.title} onSelect={active === 'pls_oof' || active === 'pls_residuals' ? onSelect : undefined} /><div className="adv-chart-footnote">{active === 'pls_coefficients' ? <>切片：{number(result.coefficients.intercept, 6)} <span>最終モデルは全試料で再学習しています。</span></> : active === 'pls_components' ? <>選択成分数：{result.selectedComponents}<span>この図はモデル選択の記録で、独立の性能評価ではありません。</span></> : <>線・点のクリックで試料IDを選択<span>予測偏り（OOF予測 − 観測の平均）：{number(result.metrics.biasCV)}</span></>}</div></section>
    <div className="adv-pls-bottom"><section className="glass-panel adv-fold-panel"><div className="adv-panel-heading"><div className="panel-caption">OUTER FOLD MODELS</div><h2>外側foldごとのモデル</h2></div><div className="adv-table-scroll"><table><thead><tr><th>外側fold</th><th>学習試料</th><th>評価試料</th><th>選択成分数</th></tr></thead><tbody>{result.foldModels.map((fold, index) => <tr key={`${fold.fold}-${index}`}><th scope="row">{fold.fold}</th><td>{fold.train}</td><td>{fold.test}</td><td>{fold.components}</td></tr>)}</tbody></table></div><p>成分数は各foldの学習データ内で選択するため、fold間で異なる場合があります。</p></section><section className="glass-panel adv-definition-panel"><div className="panel-caption">VALIDATION DEFINITION</div><h2>交差検証と最終モデル</h2><p>{result.definition}</p><p className="adv-scale-record">PLS内の波長ごとの標準化：{result.scale ? 'あり' : 'なし'}<br />乱数シード：{result.seed}</p><details><summary>最終モデルの校正値 <ChevronRight size={13} /></summary><div className="adv-calibration"><div><span>校正RMSE</span><strong>{number(result.metrics.rmseCalibration)}</strong></div><div><span>校正R²</span><strong>{number(result.metrics.r2Calibration)}</strong></div></div><p>全学習データへの適合値です。未学習試料への性能を示す外側OOFの値とは分離して記録します。</p></details></section></div>
  </div>;
}

function preprocessing(result: AnalysisResult) {
  const settings = result.metadata.settings;
  const scatter = settings.scatter === 'none' ? '散乱補正なし' : settings.scatter.toUpperCase();
  const sg = [settings.smooth ? `SG ${settings.window}点・${settings.polyorder}次` : '平滑化なし', settings.derivative ? `${settings.derivative}次微分` : '微分なし'].join(' / ');
  return (settings.pipelineMode === 'legacy-python' ? [sg, scatter] : [scatter, sg]).join(' → ');
}

function meanSpectrumFigure(result: AnalysisResult): Figure {
  const { wavelengths, processed, groups } = result.spectra;
  const groupNames = [...new Set(groups)];
  return { data: groupNames.map((group, index) => {
    const indices = groups.map((_, i) => i).filter(i => groups[i] === group), mean = new Array<number>(wavelengths.length).fill(0);
    for (const row of indices) for (let j = 0; j < mean.length; j++) mean[j] += processed[row][j] / indices.length;
    return { type: 'scatter', mode: 'lines', name: `${group} (n=${indices.length})`, x: wavelengths, y: mean, line: { color: COLORS[index % COLORS.length], width: 1.8, dash: DASHES[index % DASHES.length] }, hovertemplate: '%{x:.2f} nm<br>群平均 %{y:.5g}<extra></extra>' };
  }), layout: { ...chartLayout('GROUP MEAN SPECTRA', '波長 / nm', result.metadata.settings.derivative ? `${result.metadata.settings.derivative}次微分後の群平均` : '前処理後の群平均信号'), margin: { l: 65, r: 22, t: 65, b: 55 } } };
}

function comparisonAquagram(result: AnalysisResult): Figure {
  const aq = result.aquagram;
  const unscaled = result.metadata.settings.aquagramReference === 'none';
  let limit = 1;
  for (const group of aq.groups) for (const value of group.values) limit = Math.max(limit, Math.ceil(Math.abs(value) * 1.15 * 2) / 2);
  const theta = [...aq.labels, aq.labels[0]];
  return { data: [{ type: 'scatterpolar', mode: 'lines', theta, r: theta.map(() => 0), name: unscaled ? '信号 0' : '基準 0', showlegend: false, hoverinfo: 'skip', line: { color: '#bbb', width: 1, dash: 'dot' } }, ...aq.groups.map((group, index) => ({ type: 'scatterpolar', mode: 'lines+markers', name: `${group.name} (n=${group.n})`, theta, r: [...group.values, group.values[0]], line: { color: COLORS[index % COLORS.length], width: 1.8, dash: DASHES[index % DASHES.length] }, marker: { size: 4, symbol: SYMBOLS[index % SYMBOLS.length] }, hovertemplate: '%{theta}<br>' + (unscaled ? '群平均 ' : '標準化差 ') + '%{r:.4g}<extra></extra>' }))], layout: { ...chartLayout('AQUAGRAM'), margin: { l: 58, r: 58, t: 65, b: 55 }, legend: { orientation: 'h', x: 0, y: -.1, font: { size: 9 } }, polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { range: [-limit, limit], gridcolor: '#e2e2e2', linecolor: '#ddd', tickfont: { size: 9, color: '#999' } }, angularaxis: { direction: 'clockwise', rotation: 90, gridcolor: '#e4e4e4', linecolor: '#ddd', tickfont: { size: 9 } } } } };
}

/** The comparison viewer and ZIP export use the same group-level figures. */
export function comparisonFigures(result: AnalysisResult): Record<string, Figure> {
  return { group_mean_spectra: meanSpectrumFigure(result), aquagram: comparisonAquagram(result), ...(result.pls ? plsFigures(result.pls) : {}) };
}

function comparisonKey(run: ComparisonRun) {
  const pls = run.result.pls;
  if (!pls) return null;
  const settings = run.result.metadata.settings.pls;
  return JSON.stringify({ target: pls.targetColumn, method: pls.method, folds: pls.folds, seed: pls.seed, cvGroupColumn: settings?.split === 'group' ? settings.cvGroupColumn : null, evaluation: pls.ids.map((id, index) => [id, pls.fold[index], pls.observed[index]]) });
}

export function ComparisonPanel({ runs, onRemove, onClear, onRestore, disabled }: { runs: ComparisonRun[]; onRemove: (id: string) => void; onClear: () => void; onRestore: (id: string) => void; disabled: boolean }) {
  const [view, setView] = useState<'spectra' | 'aquagram' | 'pls'>('spectra');
  const displayed = runs.slice(0, 4);
  const figures = useMemo(() => displayed.map(run => ({ id: run.id, figure: view === 'spectra' ? meanSpectrumFigure(run.result) : view === 'aquagram' ? comparisonAquagram(run.result) : run.result.pls ? oofFigure(run.result.pls) : null })), [runs, view]);
  const plsRuns = displayed.filter(run => run.result.pls), keys = plsRuns.map(comparisonKey);
  const compatible = plsRuns.length > 1 && keys.every(key => key === keys[0]);
  const rows: { name: string; value: (run: ComparisonRun) => string }[] = [
    { name: 'PCA・Aquagramの計算元', value: run => run.result.metadata.execution?.engine === 'aquap2' ? `aquap2 ${run.result.metadata.execution.aquap2Version} / ${run.result.metadata.execution.rVersion}` : 'Python · ブラウザー内' },
    { name: 'AquagramのSD', value: run => run.result.metadata.settings.aquagramReference === 'none' ? '標準化なし' : run.result.metadata.execution?.engine === 'aquap2' ? '標本SD（n−1）' : '母SD（n）' },
    { name: '前処理方式', value: run => run.result.metadata.settings.pipelineMode === 'legacy-python' ? '旧Python互換' : '標準方式' },
    { name: '前処理', value: run => preprocessing(run.result) },
    { name: '波長範囲', value: run => `${run.result.metadata.range[0]}–${run.result.metadata.range[1]} nm` },
    { name: '試料数 × 波長数', value: run => `${run.result.metadata.samples} × ${run.result.metadata.variables}` },
    { name: '欠損値の処理', value: run => run.result.metadata.settings.missing === 'median' ? '波長列ごとの中央値で補完' : run.result.metadata.settings.missing === 'mean' ? '波長列ごとの平均値で補完' : '欠損があれば停止' },
    { name: 'PCAの波長ごとの標準化', value: run => run.result.metadata.settings.pcaScale ? 'あり' : 'なし' },
    { name: 'PC1 寄与率', value: run => percent(run.result.pca.explainedVariance[0] ?? NaN) },
    { name: 'PC1 + PC2 累積寄与率', value: run => run.result.pca.explainedVariance.length >= 2 ? percent(run.result.pca.explainedVariance.slice(0, 2).reduce((sum, n) => sum + n, 0)) : '第2成分なし' },
    { name: 'Aquagramの基準', value: run => run.result.aquagram.reference },
    { name: 'PLS目的変数', value: run => run.result.pls?.targetColumn ?? 'PLSなし' },
    { name: 'PLS分割条件', value: run => run.result.pls ? `${run.result.pls.method === 'nested-group-kfold' ? 'GroupKFold' : 'KFold'} / ${run.result.pls.folds}分割 / seed ${run.result.pls.seed}${run.result.metadata.settings.pls?.split === 'group' ? ` / 群列 ${run.result.metadata.settings.pls.cvGroupColumn}` : ''}` : '—' },
    { name: '外側OOF RMSECV', value: run => run.result.pls ? number(run.result.pls.metrics.rmseCV) : '—' },
    { name: '外側OOF MAE', value: run => run.result.pls ? number(run.result.pls.metrics.maeCV) : '—' },
    { name: '外側OOF R²', value: run => run.result.pls ? number(run.result.pls.metrics.r2CV) : '—' },
    { name: '基準モデル RMSECV', value: run => run.result.pls ? number(run.result.pls.metrics.baselineRmseCV) : '—' },
    { name: 'PLS最終成分数', value: run => run.result.pls ? String(run.result.pls.selectedComponents) : '—' },
  ];
  if (!displayed.length) return <section className="glass-panel adv-comparison-empty"><Layers2 size={31} strokeWidth={1.2} /><div className="eyebrow">ANALYSIS COMPARISON</div><h2>比較する解析条件がありません</h2><p>同一データの解析結果を条件名とともに保存すると、最大4条件を一覧と図で比較できます。前処理・PCA・Aquagram・PLSの設定を変更して再解析し、比較対象に追加してください。</p><div><SlidersHorizontal size={15} /> 解析結果の表示中に、比較用の条件を保存できます。</div></section>;
  return <div className="adv-comparison-panel"><div className="adv-comparison-header"><div><h2>保存した解析条件 <span>{displayed.length} / 4</span></h2><p>同一データに対する解析条件を並べて確認します。図は条件ごとに独立して表示します。</p></div><button className="button outline" disabled={disabled} onClick={onClear}><Trash2 size={13} /> すべて解除</button></div><div className="glass-panel adv-comparison-table"><div className="adv-table-scroll"><table><thead><tr><th scope="col">比較項目</th>{displayed.map((run, index) => <th scope="col" key={run.id}><div className="adv-run-heading"><span className="adv-run-index">{String(index + 1).padStart(2, '0')}</span><div><strong title={run.name}>{run.name}</strong><small>{time(run.createdAt)}</small></div><button className="icon-button" disabled={disabled} aria-label={`${run.name}を比較から解除`} onClick={() => onRemove(run.id)}><Trash2 size={13} /></button></div><button className="adv-restore" disabled={disabled} onClick={() => onRestore(run.id)}><RotateCcw size={11} /> 設定を復元<ArrowUpRight size={11} /></button></th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.name}><th scope="row">{row.name}</th>{displayed.map(run => <td key={run.id}>{row.value(run)}</td>)}</tr>)}</tbody></table></div></div><div className={`adv-comparability ${compatible ? 'adv-comparable' : ''}`}><CircleHelp size={15} /><p>{plsRuns.length < 2 ? 'PLS性能の比較には、PLS回帰を含む条件が2件以上必要です。' : compatible ? 'PLSの目的変数・分割条件・評価試料が一致しています。外側OOF性能を参考比較できます。ここでの条件比較は、別の独立評価を代替するものではありません。' : 'PLSの目的変数・分割条件・評価試料のいずれかが異なります。表示された性能指標を条件間で直接比較しないでください。'}</p></div><section className="adv-small-multiples"><div className="adv-comparison-chart-header"><div className="segmented" aria-label="条件別グラフの切り替え"><button aria-pressed={view === 'spectra'} onClick={() => setView('spectra')}>群平均スペクトル</button><button aria-pressed={view === 'aquagram'} onClick={() => setView('aquagram')}>Aquagram</button><button aria-pressed={view === 'pls'} onClick={() => setView('pls')}>PLS OOF予測</button></div><span>軸の範囲は各図で個別に設定</span></div><p className="adv-comparison-chart-note">{view === 'spectra' ? '各条件で前処理した群平均スペクトルです。異なる前処理による信号値の大きさを、そのまま優劣として解釈しないでください。' : view === 'aquagram' ? '各条件で計算したAquagramです。比較基準・実際の波長・前処理が異なる場合、群平均または標準化差の定義も確認してください。' : '外側OOFの観測値と予測値を、条件ごとに表示します。目的変数・分割条件・評価試料が一致する結果を参考比較してください。'}</p><div className="adv-multiple-grid">{displayed.map((run, index) => <article className="glass-panel adv-multiple" key={run.id}><div className="adv-multiple-heading"><span className="adv-run-index">{String(index + 1).padStart(2, '0')}</span><div><h3 title={run.name}>{run.name}</h3><p>{view === 'aquagram' ? `基準：${run.result.aquagram.reference}` : view === 'pls' ? `目的変数：${run.result.pls?.targetColumn ?? '未設定'}` : preprocessing(run.result)}</p></div></div>{figures[index]?.figure ? <Plot figure={figures[index].figure!} label={`${run.name}の${view === 'spectra' ? '群平均スペクトル' : view === 'aquagram' ? 'Aquagram' : 'PLS OOF予測'}`} className="adv-small-plot" /> : <div className="adv-missing-pls"><FlaskConical size={23} strokeWidth={1.3} /><p>この条件にはPLS解析結果がありません。</p></div>}</article>)}</div></section></div>;
}


