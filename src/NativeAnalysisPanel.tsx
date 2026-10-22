import { useId, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ChevronRight, CircleHelp, FileSpreadsheet, ScatterChart, Thermometer, Upload } from 'lucide-react';
import type { CalibrationSummary, DatasetSummary, NativeAquagramConfig, NativePLSRConfig, NativePLSRResult, TemperatureAquagramMode } from './types';
import Plot from './Plot';
import type { Figure } from './Plot';
import './native-analysis.css';

const AQ_MODES: { value: TemperatureAquagramMode; label: string; description: string }[] = [
  { value: 'sfc', label: 'sfc · 校正を用いた標準化', description: '校正スペクトルを基準とする標準化を行います。' },
  { value: 'sfc-diff', label: 'sfc-diff · 標準化・対照群差', description: '校正を用いた標準化値から、指定対照群を差し引きます。' },
  { value: 'aucs', label: 'aucs · 校正面積比', description: '帯域の面積比を、指定した温度校正範囲に基づく尺度へ正規化します。' },
  { value: 'aucs-diff', label: 'aucs-diff · 校正面積比・対照群差', description: '温度校正に基づく面積比の値から、指定対照群を差し引きます。' },
  { value: 'aucs.tn', label: 'aucs.tn · 測定温度で補正', description: '測定温度に対応する校正値を差し引きます。' },
  { value: 'aucs.tn-diff', label: 'aucs.tn-diff · 温度補正・対照群差', description: '測定温度による補正を行い、指定対照群を差し引きます。' },
  { value: 'aucs.dce', label: 'aucs.dce · 温度校正スケールへ換算', description: '校正面積比を、指定した校正温度範囲に基づくDCEへ換算します。' },
  { value: 'aucs.dce-diff', label: 'aucs.dce-diff · DCE・対照群差', description: 'DCEへ換算した値から、指定対照群を差し引きます。' },
  { value: 'aucs.tn.dce', label: 'aucs.tn.dce · 温度補正後にDCE換算', description: '測定温度による補正と、校正温度スケールへの換算を行います。' },
  { value: 'aucs.tn.dce-diff', label: 'aucs.tn.dce-diff · 温度補正・DCE・対照群差', description: '温度補正とDCE換算を行い、指定対照群を差し引きます。' },
];
const number = (value: number | undefined, digits = 5) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('ja-JP', { maximumSignificantDigits: digits }) : '—';
const inputValue = (value: number) => Number.isFinite(value) ? value : '';
const fromInput = (value: string) => value === '' ? NaN : Number(value);
const hasTemperature = (values: number[], value: number) => Number.isFinite(value) && values.includes(value);
const BAND_NAMES = { 'ot1.12': ['C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09', 'C10', 'C11', 'C12'], 'ot1.15': ['C01', 'C02', 'C03', 'C04', 'C05a', 'C05b', 'C05c', 'C05d', 'C06', 'C07', 'C08', 'C09', 'C10', 'C11', 'C12'] };

function NativeField({ label, hint, children, wide = false }: { label: string; hint?: string; children: ReactNode; wide?: boolean }) {
  return <label className={`native-field ${wide ? 'native-field-wide' : ''}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}
function NativeNote({ title, children }: { title: string; children: ReactNode }) {
  return <div className="native-method-note"><CircleHelp size={15} /><div><strong>{title}</strong><p>{children}</p></div></div>;
}

export function NativeAquagramSettings({ value, onChange, disabled, calibration, onCalibrationFile, onCalibrationSheet, groups }: {
  value: NativeAquagramConfig; onChange: (value: NativeAquagramConfig) => void; disabled: boolean;
  calibration: CalibrationSummary | null; onCalibrationFile: (file: File) => void; onCalibrationSheet: (sheet: string) => void; groups: string[];
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const id = useId();
  const update = <K extends keyof NativeAquagramConfig>(key: K, next: NativeAquagramConfig[K]) => onChange({ ...value, [key]: next });
  const observed = useMemo(() => [...new Set(calibration?.temperatureColumns.find(column => column.column === value.temperatureColumn)?.observedTemperatures ?? [])].filter(Number.isFinite).sort((a, b) => a - b), [calibration, value.temperatureColumn]);
  const mode = AQ_MODES.find(option => option.value === value.mode);
  const diff = value.mode.endsWith('-diff');
  const issues: string[] = [];
  if (value.enabled) {
    if (!calibration) issues.push('校正ファイルを読み込んでください。設定に保存したファイル名・SHAだけでは校正データを復元できません。');
    else if (!value.temperatureColumn || !observed.length) issues.push('校正データの温度列を選択してください。');
    if (observed.length) {
      if (!hasTemperature(observed, value.tCalib[0])) issues.push('TCalibの下端は、校正データに観測された温度を指定してください。');
      if (!hasTemperature(observed, value.tCalib[1])) issues.push('TCalibの上端は、校正データに観測された温度を指定してください。');
      if (!hasTemperature(observed, value.tExp)) issues.push('Texpは、校正データに観測された温度を指定してください。未観測温度のloess補間は未対応です。');
    }
    if (!Number.isFinite(value.tCalib[0]) || !Number.isFinite(value.tCalib[1]) || value.tCalib[0] >= value.tCalib[1]) issues.push('TCalibは、下端より上端が大きい有限の温度範囲にしてください。');
    if (!Number.isFinite(value.tExp)) issues.push('Texpには有限の測定温度を指定してください。');
    if (!Number.isInteger(value.calibrationSmoothN) || value.calibrationSmoothN < 3 || value.calibrationSmoothN % 2 !== 1) issues.push('校正モデル用SGの窓幅は、3以上の奇数にしてください。');
    if (calibration && value.calibrationSmoothN > calibration.wavelengthColumns.length) issues.push('校正モデル用SGの窓幅が、校正データの波長数を超えています。');
    if (!Number.isInteger(value.smoothN) || value.smoothN < 3 || value.smoothN % 2 !== 1) issues.push('測定Aquagram用SGの窓幅は、3以上の奇数にしてください。');
    if (diff && !value.referenceGroup) issues.push('差分モードの対照群名を指定してください。');
  }
  return <section className="glass-panel native-settings-panel native-aquagram-settings">
    <div className="native-section-heading"><Thermometer size={19} strokeWidth={1.4} /><div><h2>温度校正Aquagram</h2><p>別の校正データを使い、sfc・AUC系の座標を計算します。</p></div><span className="native-optional">aquap2py · 任意</span></div>
    <fieldset disabled={disabled}>
      <label className="native-enable"><input type="checkbox" checked={value.enabled} onChange={event => update('enabled', event.target.checked)} /><span><strong>温度校正Aquagramを有効にする</strong><small>R不要・ブラウザー内で計算。校正データは測定データと分けて読み込みます。</small></span></label>
      {value.enabled && <div className="native-settings-body">
        <div className="native-form-grid">
          <NativeField label="Aquagramモード" hint={mode?.description} wide><select value={value.mode} onChange={event => update('mode', event.target.value as TemperatureAquagramMode)}>{AQ_MODES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></NativeField>
          <NativeField label="校正モデルの帯域座標系" hint={value.mode.startsWith('sfc') ? 'sfcの出力座標には、共通のAquagram波長設定を使います。' : undefined}><select value={value.coordinateSystem} onChange={event => update('coordinateSystem', event.target.value as NativeAquagramConfig['coordinateSystem'])}><option value="ot1.12">ot1.12 · 12帯域</option><option value="ot1.15">ot1.15 · 15帯域（C05を4帯に分割）</option></select></NativeField>
          {diff && <NativeField label="対照群名" hint="測定データのグループ名。完全一致で指定します。"><input list={`${id}-groups`} value={value.referenceGroup ?? ''} onChange={event => update('referenceGroup', event.target.value || null)} placeholder="対照群名を入力" /><datalist id={`${id}-groups`}>{groups.map(group => <option key={group} value={group} />)}</datalist></NativeField>}
        </div>
        <div className="native-coordinate-note"><span>{BAND_NAMES[value.coordinateSystem].map(name => <i key={name}>{name}</i>)}</span><p>{value.mode.startsWith('sfc') ? 'sfcは指定した単一波長の値を校正平均を中心に標準化します。初版では測定波長と校正の1300–1600 nm内の波長格子が完全一致する必要があります。' : 'AUC系は、この波長帯の多角形面積比を使います。classic・sfcの単一波長値とは別の量で、DCEは実温度の推定を意味しません。'}</p></div>
        <div className="native-calibration-upload"><div><FileSpreadsheet size={19} strokeWidth={1.4} /><div><strong>{calibration?.name ?? value.calibrationSource?.name ?? '校正ファイルが読み込まれていません'}</strong><p>{calibration ? `${calibration.rowCount.toLocaleString()} 行 · ${calibration.wavelengthColumns.length.toLocaleString()} 波長${calibration.sheet ? ` · ${calibration.sheet}` : ''}` : value.calibrationSource ? '設定に記録された識別情報です。元の校正ファイルを再読込してください。' : 'CSV・XLSX・XLS。温度列と波長列を含む表を用意してください。'}</p>{calibration?.artificial && <small>人工校正データ · 実測値ではありません</small>}</div></div><button className="button outline" type="button" onClick={() => fileInput.current?.click()}><Upload size={14} />{calibration ? '校正ファイルを変更' : '校正ファイルを選択'}</button><input ref={fileInput} className="visually-hidden" type="file" accept=".csv,.xlsx,.xls" aria-label="温度校正ファイル" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) onCalibrationFile(file); }} /></div>
        <div className="native-form-grid">
          {calibration && calibration.sheets.length > 0 && <NativeField label="校正Excelのシート"><select value={calibration.sheet ?? ''} onChange={event => onCalibrationSheet(event.target.value)}>{calibration.sheets.map(sheet => <option key={sheet} value={sheet}>{sheet}</option>)}</select></NativeField>}
          <NativeField label="校正データの温度列" hint="非波長の数値列から選択します。値の単位は°Cとして扱います。"><select disabled={!calibration} value={value.temperatureColumn ?? ''} onChange={event => update('temperatureColumn', event.target.value || null)}><option value="">温度列を選択</option>{calibration?.temperatureColumns.map(column => <option key={column.column} value={column.column}>{column.column}</option>)}{value.temperatureColumn && !calibration?.temperatureColumns.some(column => column.column === value.temperatureColumn) && <option value={value.temperatureColumn} disabled>{value.temperatureColumn}（再確認が必要）</option>}</select></NativeField>
          <NativeField label="校正モデル用SG窓幅" hint="校正データを処理する窓幅。測定Aquagram用とは別です。"><input type="number" min={3} step={2} value={inputValue(value.calibrationSmoothN)} onChange={event => update('calibrationSmoothN', fromInput(event.target.value))} /></NativeField>
        </div>
        <div className="native-observed-temperatures"><div><strong>校正モデルで使える観測温度</strong><span>{observed.length} 水準</span></div>{observed.length ? <p>{observed.slice(0, 40).map(temperature => `${number(temperature, 8)}°C`).join(' / ')}{observed.length > 40 && <small>先頭40水準を表示。残りは校正ファイルで確認できます。</small>}</p> : <p>校正ファイルと温度列を指定すると、観測された温度を表示します。</p>}<datalist id={`${id}-temperatures`}>{observed.slice(0, 500).map(temperature => <option key={temperature} value={temperature} />)}</datalist></div>
        <div className="native-form-grid native-grid-three">
          <NativeField label="TCalib 下端 / °C"><input type="number" step="any" list={`${id}-temperatures`} value={inputValue(value.tCalib[0])} aria-invalid={!!observed.length && !hasTemperature(observed, value.tCalib[0])} onChange={event => update('tCalib', [fromInput(event.target.value), value.tCalib[1]])} /></NativeField>
          <NativeField label="TCalib 上端 / °C"><input type="number" step="any" list={`${id}-temperatures`} value={inputValue(value.tCalib[1])} aria-invalid={!!observed.length && !hasTemperature(observed, value.tCalib[1])} onChange={event => update('tCalib', [value.tCalib[0], fromInput(event.target.value)])} /></NativeField>
          <NativeField label="Texp 測定温度 / °C" hint="全ての非classicモードで観測温度を指定します。"><input type="number" step="any" list={`${id}-temperatures`} value={inputValue(value.tExp)} aria-invalid={!!observed.length && !hasTemperature(observed, value.tExp)} onChange={event => update('tExp', fromInput(event.target.value))} /></NativeField>
        </div>
        <div className="native-form-grid native-aq-measurement"><NativeField label="測定Aquagram用SG窓幅" hint="測定スペクトルに適用するAquagram内の平滑化。奇数で指定します。"><input type="number" min={3} step={2} value={inputValue(value.smoothN)} onChange={event => update('smoothN', fromInput(event.target.value))} /></NativeField><label className="native-check"><input type="checkbox" checked={value.msc} onChange={event => update('msc', event.target.checked)} /><span>Aquagram内のMSC設定<small>{value.mode.startsWith('sfc') ? 'sfcに適用します。共通前処理のMSC設定とは独立です。' : 'AUC系では、この設定の値にかかわらず内部MSCを適用しません。共通前処理は別に適用されます。'}</small></span></label></div>
        {issues.length > 0 && <div className="native-validation-note" role="status"><strong>実行前に確認してください</strong><ul>{issues.map(issue => <li key={issue}>{issue}</li>)}</ul></div>}
        {calibration && <p className="native-source-record">校正ファイルのSHA-256 <code title={calibration.sourceSha256}>{calibration.sourceSha256}</code></p>}
      </div>}
      <NativeNote title="観測された温度だけを使います">TCalibの両端とTexpには校正データの観測温度を指定してください。未観測温度のloess補間は初版では未対応で、解析時に停止します。設定JSONへ記録するのは校正ファイルの名前・シート・SHA等の設定と識別情報で、測定値そのものは混ぜません。</NativeNote>
    </fieldset>
  </section>;
}

export function NativePLSRSettings({ value, onChange, disabled, summary }: { value: NativePLSRConfig; onChange: (value: NativePLSRConfig) => void; disabled: boolean; summary: DatasetSummary }) {
  const waveColumns = new Set(summary.wavelengthColumns.map(column => column.column));
  const otherColumns = summary.columns.filter(column => !waveColumns.has(column));
  const numericColumns = otherColumns.filter(column => {
    if (column === summary.suggestedId || column === value.cvGroupColumn) return false;
    const index = summary.columns.indexOf(column), observed = summary.preview.map(row => row[index]).filter(item => item !== null && item !== undefined && item !== '');
    return observed.length > 0 && observed.every(item => Number.isFinite(Number(item)));
  });
  const update = <K extends keyof NativePLSRConfig>(key: K, next: NativePLSRConfig[K]) => onChange({ ...value, [key]: next });
  const maxComponents = Math.max(1, Math.min(30, summary.rowCount - 1, summary.wavelengthColumns.length));
  return <section className="glass-panel native-settings-panel">
    <div className="native-section-heading"><ScatterChart size={19} strokeWidth={1.4} /><div><h2>native PLSR</h2><p>aquap2pyの成分選択とCV計算を使う回帰です。</p></div><span className="native-optional">aquap2py · 任意</span></div>
    <fieldset disabled={disabled}><label className="native-enable"><input type="checkbox" checked={value.enabled} onChange={event => update('enabled', event.target.checked)} /><span><strong>native PLSRを有効にする</strong><small>数値の目的変数を指定。Workbenchの外側nested CVとは異なる評価です。</small></span></label>
      {value.enabled && <div className="native-settings-body"><div className="native-form-grid native-grid-three">
        <NativeField label="目的変数の列" hint="波長列・推奨ID・CV群列を除くプレビュー上の数値列。全行は解析時に検証します。"><select value={value.targetColumn ?? ''} onChange={event => update('targetColumn', event.target.value || null)}><option value="">数値列を選択</option>{numericColumns.map(column => <option key={column} value={column}>{column}</option>)}{value.targetColumn && !numericColumns.includes(value.targetColumn) && <option value={value.targetColumn} disabled>{value.targetColumn}（列の設定を確認）</option>}</select></NativeField>
        <NativeField label="成分数の指定"><select value={value.components === null ? 'auto' : 'fixed'} onChange={event => update('components', event.target.value === 'auto' ? null : Math.min(2, maxComponents))}><option value="auto">自動 · 調整CV誤差で選択</option><option value="fixed">固定成分数</option></select></NativeField>
        <NativeField label="固定する成分数" hint={`1–${maxComponents}成分。実際の上限は学習区画の大きさにも依存します。`}><input type="number" min={1} max={maxComponents} step={1} disabled={value.components === null} value={value.components === null ? '' : inputValue(value.components)} placeholder="自動" onChange={event => update('components', fromInput(event.target.value))} /></NativeField>
        <NativeField label="交差検証の分割"><select value={value.validation} onChange={event => update('validation', event.target.value as NativePLSRConfig['validation'])}><option value="LOO">LOO · 1試料ずつ除外</option><option value="group">群単位 · 同じCV群をまとめて除外</option></select></NativeField>
        <NativeField label="CV群の列" hint="反復測定は同一個体・同一試料を示す列でまとめます。"><select disabled={value.validation !== 'group'} value={value.cvGroupColumn ?? ''} onChange={event => update('cvGroupColumn', event.target.value || null)}><option value="">個体ID・試料IDなどを選択</option>{otherColumns.filter(column => column !== value.targetColumn).map(column => <option key={column} value={column}>{column}</option>)}</select></NativeField>
      </div><p className="native-field-note">自動選択はnativeの反復調整CV手順を使います。LOOの分割は決定的です。表示用のグループと、検証時にまとめるCV群は別に設定します。</p></div>}
      <NativeNote title="外側nested CVによる独立評価ではありません">成分数選択とCV誤差を確認するためのnative経路です。自動選択に用いたCV誤差を、そのモデルを独立に評価した性能として扱わないでください。外側nested CVの評価にはWorkbench標準PythonのPLSを使用します。</NativeNote>
    </fieldset>
  </section>;
}

function chartLayout(title: string, x: string, y: string): Record<string, any> {
  return { title: { text: title, x: .035, xanchor: 'left', font: { size: 12, color: '#777' } }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(255,255,255,0)', font: { family: 'Arial, "Noto Sans JP", sans-serif', size: 11, color: '#555' }, margin: { l: 77, r: 30, t: 72, b: 66 }, xaxis: { title: { text: x, standoff: 18 }, gridcolor: '#ebebeb', linecolor: '#d8d8d8', zerolinecolor: '#ccc', showline: true }, yaxis: { title: { text: y, standoff: 17 }, gridcolor: '#ebebeb', zerolinecolor: '#ccc' }, legend: { orientation: 'h', x: 0, y: 1.03, font: { size: 10 } }, hovermode: 'closest', hoverlabel: { bgcolor: '#fff', bordercolor: '#ddd', font: { color: '#222', size: 11 } }, uirevision: title };
}

/** Shared by the result panel and PNG export so the saved figures match. */
export function nativePlsrFigures(result: NativePLSRResult, wavelengths: number[]): Record<string, Figure> {
  let min = Infinity, max = -Infinity;
  for (const values of [result.observed, result.predictedCV]) for (const value of values) if (Number.isFinite(value)) { min = Math.min(min, value); max = Math.max(max, value); }
  if (!Number.isFinite(min)) { min = 0; max = 1; }
  const padding = Math.max((max - min) * .07, Math.abs(max) * .01, .001), range = [min - padding, max + padding];
  const colors = ['#222', '#777', '#aaa', '#444', '#bfbfbf'], symbols = ['circle', 'square', 'diamond', 'triangle-up', 'cross'];
  const predictions: Figure = { data: [{ type: 'scatter', mode: 'lines', x: range, y: range, name: '観測値 = 予測値', line: { color: '#bbb', width: 1, dash: 'dash' }, hoverinfo: 'skip', showlegend: false }, ...[...new Set(result.groups)].map((group, groupIndex) => {
    const indices = result.ids.map((_, index) => index).filter(index => result.groups[index] === group);
    return { type: 'scatter', mode: 'markers', name: group || '全試料', x: indices.map(index => result.observed[index]), y: indices.map(index => result.predictedCV[index]), customdata: indices.map(index => result.ids[index]), text: indices.map(index => `CV区画 ${result.fold[index]}`), marker: { color: colors[groupIndex % colors.length], symbol: symbols[groupIndex % symbols.length], size: 8, opacity: .83, line: { color: '#fff', width: 1 } }, hovertemplate: '%{customdata}<br>観測値 %{x:.5g}<br>CV予測値 %{y:.5g}<br>%{text}<extra></extra>' };
  })], layout: { ...chartLayout('NATIVE PLSR · CV PREDICTIONS', `${result.targetColumn} · 観測値`, `${result.targetColumn} · CV予測値`), xaxis: { ...chartLayout('', '', '').xaxis, title: `${result.targetColumn} · 観測値`, range }, yaxis: { ...chartLayout('', '', '').yaxis, title: `${result.targetColumn} · CV予測値`, range, scaleanchor: 'x', scaleratio: 1 } } };
  const curves: Figure = { data: [{ key: 'rmseCV', name: 'CV', color: '#333', dash: 'solid' }, { key: 'rmseAdjCV', name: '調整CV', color: '#777', dash: 'dash' }, { key: 'rmseCalibration', name: '校正（学習内）', color: '#b0b0b0', dash: 'dot' }].map(series => ({ type: 'scatter', mode: 'lines+markers', x: result.curve.map(row => row.components), y: result.curve.map(row => row[series.key as 'rmseCV' | 'rmseAdjCV' | 'rmseCalibration']), name: series.name, line: { color: series.color, width: 1.8, dash: series.dash }, marker: { size: result.curve.map(row => row.components === result.selectedComponents ? 9 : 5) }, hovertemplate: '%{x} 成分<br>RMSE %{y:.5g}<extra>' + series.name + '</extra>' })), layout: { ...chartLayout('NATIVE PLSR · COMPONENTS & CV ERROR', 'PLSR成分数', 'RMSE'), xaxis: { ...chartLayout('', '', '').xaxis, title: 'PLSR成分数', dtick: 1 }, shapes: [{ type: 'line', x0: result.selectedComponents, x1: result.selectedComponents, yref: 'paper', y0: 0, y1: 1, line: { color: '#999', width: 1, dash: 'dot' } }] } };
  const aligned = wavelengths.length === result.coefficients.values.length;
  const coefficients: Figure = { data: aligned ? [{ type: 'scatter', mode: 'lines', x: wavelengths, y: result.coefficients.values, name: '回帰係数', line: { color: '#333', width: 1.8 }, hovertemplate: '%{x:.3f} nm<br>回帰係数 %{y:.6g}<extra>全試料の校正モデル</extra>' }] : [], layout: { ...chartLayout('NATIVE PLSR · REGRESSION COEFFICIENTS', '波長 / nm', '回帰係数'), showlegend: false, ...(!aligned ? { annotations: [{ text: '係数と波長の数が一致しません。出力を確認してください。', showarrow: false, xref: 'paper', yref: 'paper', x: .5, y: .5 }] } : {}) } };
  return { native_plsr_predictions: predictions, native_plsr_components: curves, native_plsr_coefficients: coefficients };
}

export function NativePLSRResults({ result, wavelengths }: { result: NativePLSRResult; wavelengths: number[] }) {
  const [active, setActive] = useState<'predictions' | 'components' | 'coefficients' | 'table'>('predictions');
  const [page, setPage] = useState(0);
  const figures = useMemo(() => nativePlsrFigures(result, wavelengths), [result, wavelengths]);
  const pages = Math.max(1, Math.ceil(result.ids.length / 50)), currentPage = Math.min(page, pages - 1), start = currentPage * 50;
  const validation = result.settings.validation === 'LOO' ? 'LOO' : result.settings.validation === 'group' ? '群単位CV' : 'CV';
  const selection = result.selection.mode === 'fixed' ? '固定成分数' : /auto|adj|repeat/i.test(result.selection.mode) ? '自動成分選択' : result.selection.mode;
  const tabs = [{ key: 'predictions', label: 'CV予測', title: 'CVの観測値と予測値', caption: '選択した成分数でのCV予測です。破線は観測値と予測値が等しい位置です。' }, { key: 'components', label: '成分数・CV誤差', title: '成分数とCV誤差', caption: 'CV・調整CV・校正誤差を分けて表示します。成分数選択に使った誤差は、独立評価とは区別します。' }, { key: 'coefficients', label: '回帰係数', title: '全試料で校正したモデルの係数', caption: '前処理後の説明変数に対する回帰係数です。係数の大きさは前処理と変数の尺度に依存します。' }, { key: 'table', label: '予測表', title: '試料ごとの観測値・予測値', caption: 'CV予測と、全試料で校正したモデルの学習内予測を別の列に示します。' }] as const;
  const current = tabs.find(tab => tab.key === active)!;
  const cards = [{ label: 'CV RMSE', value: number(result.metrics.rmseCV), note: '選択成分数のCV' }, { label: '調整CV RMSE', value: number(result.metrics.rmseAdjCV), note: '調整したCV誤差' }, { label: 'CV R²', value: number(result.metrics.r2CV), note: '負の値も取り得ます' }, { label: '基準モデルのRMSE', value: number(result.metrics.baselineRmseCV), note: '基準値との比較' }, { label: '選択成分数', value: String(result.selectedComponents), note: selection || '選択方法の記録を確認' }];
  return <div className="native-plsr-results">
    <div className="native-result-context"><span><strong>目的変数</strong>{result.targetColumn}</span><span>{result.algorithm} · {validation} · {result.ids.length} 試料 · {selection}</span></div>
    <NativeNote title="外側nested CVではありません">自動成分選択と表示CV誤差が同じ検証手順に依存する場合、その誤差を独立の予測性能として扱わないでください。校正値は全試料を使った学習内の値です。</NativeNote>
    <div className="native-metric-grid">{cards.map(card => <section className="glass-panel native-metric" key={card.label}><h2>{card.label}</h2><strong>{card.value}</strong><p>{card.note}</p></section>)}</div>
    {result.warnings.length > 0 && <details className="native-result-warnings"><summary>native PLSRの確認事項 <span>{result.warnings.length}</span><ChevronRight size={14} /></summary><ul>{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
    <section className="glass-panel native-results-panel"><div className="native-chart-toolbar"><div className="segmented" aria-label="native PLSRの結果表示">{tabs.map(tab => <button key={tab.key} type="button" aria-pressed={active === tab.key} onClick={() => setActive(tab.key)}>{tab.label}</button>)}</div><span>{validation} · 外側nested評価なし</span></div><div className="native-chart-caption"><h2>{current.title}</h2><p>{current.caption}</p></div>
      {active === 'table' ? <><div className="native-prediction-scroll"><table><thead><tr>{['試料ID', '群', '観測値', 'CV予測値', '校正予測値', '残差（観測−CV）', 'CV区画'].map(title => <th scope="col" key={title}>{title}</th>)}</tr></thead><tbody>{result.ids.slice(start, start + 50).map((id, offset) => { const index = start + offset; return <tr key={`${id}:${index}`}><th scope="row">{id}</th><td>{result.groups[index]}</td><td>{number(result.observed[index], 8)}</td><td>{number(result.predictedCV[index], 8)}</td><td>{number(result.predictedCalibration[index], 8)}</td><td>{number(result.residuals[index], 8)}</td><td>{result.fold[index]}</td></tr>; })}</tbody></table></div><div className="native-table-pagination"><span>{result.ids.length ? start + 1 : 0}–{Math.min(start + 50, result.ids.length)} / {result.ids.length} 試料</span><div><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>前へ</button><span>{currentPage + 1} / {pages}</span><button type="button" disabled={currentPage >= pages - 1} onClick={() => setPage(currentPage + 1)}>次へ</button></div></div></> : <Plot figure={figures[`native_plsr_${active}`]} label={current.title} className="native-result-plot" />}
      <div className="native-chart-footnote">{active === 'coefficients' ? <>切片 {number(result.coefficients.intercept, 7)}<span>全試料で校正した最終モデル</span></> : active === 'components' ? <>選択成分数 {result.selectedComponents}<span>CV曲線は成分選択の記録です</span></> : <>CV予測のバイアス {number(result.metrics.biasCV)}<span>MAE {number(result.metrics.maeCV)}</span></>}</div>
    </section>
    <section className="glass-panel native-definition-panel"><div><span className="panel-caption">CALIBRATION · TRAINING DATA</span><h2>校正値をCV評価と分けて確認</h2></div><div className="native-calibration-metrics"><span>校正RMSE<strong>{number(result.metrics.rmseCalibration)}</strong></span><span>校正R²<strong>{number(result.metrics.r2Calibration)}</strong></span></div><details><summary>計算定義と評価の範囲<ChevronRight size={14} /></summary><p>{result.definition}</p></details></section>
  </div>;
}
