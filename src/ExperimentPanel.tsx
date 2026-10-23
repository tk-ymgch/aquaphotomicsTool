import {useMemo,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {ArrowDownToLine,ArrowRight,Check,Clock3,FileSpreadsheet,Link2,Plus,RefreshCw,Upload,X} from 'lucide-react';
import {strToU8} from 'fflate';
import Plot from './Plot';
import type {Figure} from './Plot';
import type {AnalysisResult,DatasetSummary,ExperimentConfig,ExperimentFile,ExperimentFileRole,ExperimentResult,UnitySummary} from './types';
import {createExperimentSettings,detectExperimentRole,parseExperimentSettings,phaseOrder} from './experimentSettings';
import {downloadBytes} from './downloads';
import './experiment.css';

const shades=['#222222','#777777','#b1b1b1'];
const marks=['circle','square','diamond'];
const value=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)?n.toLocaleString('ja-JP',{maximumFractionDigits:4}):'—';
const percent=(n:number)=>`${(n*100).toFixed(1)}%`;
const plotLayout=(title:string,x:string,y:string):Record<string,unknown>=>({title:{text:title,font:{size:13,color:'#666'},x:.04},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{family:'Arial, "Noto Sans JP", sans-serif',size:11,color:'#666'},margin:{l:73,r:30,t:70,b:70},xaxis:{title:x,gridcolor:'#ebedef',zerolinecolor:'#d5d5d5'},yaxis:{title:y,gridcolor:'#ebedef',zerolinecolor:'#d5d5d5'},legend:{orientation:'h',y:1.06},hovermode:'closest'});

export function experimentFigures(result:ExperimentResult,analysis:AnalysisResult|null,metric='pupil_mean',spectralAxis='PC1'):Record<string,Figure>{
  const descriptor=result.metrics.find(item=>item.key===metric),label=descriptor?.label??metric,unit=descriptor?.unit??'';
  const phases=result.phaseSummaries;
  const summary:Figure={data:[{type:'bar',name:label,x:phases.map(p=>p.phase),y:phases.map(p=>p.metrics[metric]?.mean??null),error_y:{type:'data',array:phases.map(p=>p.metrics[metric]?.sd??null),visible:true},marker:{color:shades},customdata:phases.map(p=>p.metrics[metric]?.n??0),hovertemplate:'%{x}<br>%{y:.5g}<br>対応試料 n=%{customdata}<extra></extra>'}],layout:plotLayout('PHASE SUMMARY','フェーズ',`${label}${unit?' / '+unit:''}（平均 ± SD）`)};
  const timeline:Figure={data:[{type:'scatter',mode:'lines',name:'平均瞳孔径',x:result.timeline.map(row=>row.timeSeconds),y:result.timeline.map(row=>row.pupilMean),line:{color:'#3b3b3b',width:1.3},connectgaps:false},{type:'scatter',mode:'markers',name:'瞬き候補',x:result.blinkEvents.map(row=>row.midpointSeconds),y:result.blinkEvents.map(()=>null),visible:'legendonly',marker:{symbol:'line-ns',size:12,color:'#888'}}],layout:plotLayout('UNITY TIMELINE','同期後の時刻 / 秒','平均瞳孔径（元の単位）')};
  // Mark blink candidates separately along the lower border; no arbitrary pupil value.
  timeline.layout.shapes=result.blinkEvents.slice(0,1000).map(event=>({type:'rect',xref:'x',yref:'paper',x0:event.startSeconds,x1:event.endSeconds,y0:0,y1:.04,fillcolor:'#9b9b9b',line:{width:0}}));
  const correlation=result.correlations.find(c=>c.metric===metric);
  const wave:Figure={data:[{type:'scatter',mode:'lines',name:'Pearson r',x:correlation?.spectra.map(p=>p.wavelength)??[],y:correlation?.spectra.map(p=>p.r)??[],customdata:correlation?.spectra.map(p=>p.n)??[],line:{color:'#333',width:1.5},connectgaps:false,hovertemplate:'%{x:.1f} nm<br>r=%{y:.4f}<br>n=%{customdata}<extra></extra>'}],layout:{...plotLayout('SPECTRAL CORRELATION','前処理後スペクトルの波長 / nm',`${label}とのPearson r`),yaxis:{title:'Pearson r',range:[-1.05,1.05],gridcolor:'#ebedef'}}};
  const idIndex=new Map(analysis?.spectra.ids.map((id,i)=>[id,i])??[]);
  const pc=spectralAxis.startsWith('PC')?Math.max(0,Number(spectralAxis.slice(2))-1):null;
  const wavelength=pc===null?Number(spectralAxis):null;
  const wi=analysis&&wavelength!==null?analysis.spectra.wavelengths.reduce((best,w,i)=>Math.abs(w-wavelength)<Math.abs(analysis.spectra.wavelengths[best]-wavelength)?i:best,0):0;
  const scatter:Figure={data:phases.map((p,i)=>{
    const rows=result.rows.filter(row=>row.phase===p.phase&&row.valid&&row.metrics[metric]!==null&&row.metrics[metric]!==undefined&&idIndex.has(row.id));
    return {type:'scatter',mode:'markers',name:p.phase,x:rows.map(row=>{const index=idIndex.get(row.id)!;return pc===null?analysis?.spectra.processed[index]?.[wi]:analysis?.pca.scores[index]?.[pc];}),y:rows.map(row=>row.metrics[metric]),customdata:rows.map(row=>row.id),marker:{color:shades[i%3],symbol:marks[i%3],size:8,line:{color:'#fff',width:1}},hovertemplate:'%{customdata}<br>x=%{x:.5g}<br>y=%{y:.5g}<extra></extra>'};
  }),layout:plotLayout('SPECTRA / PHYSIOLOGY',pc===null?`${analysis?.spectra.wavelengths[wi]??wavelength} nm（前処理後）`:`PC${pc+1}スコア`,`${label}${unit?' / '+unit:''}`)};
  return {phase_summary:summary,unity_timeline:timeline,physiology_scatter:scatter,spectral_correlations:wave};
}

function Field({label,hint,children}:{label:string;hint?:string;children:ReactNode}){return <label className="field"><span>{label}</span>{children}{hint&&<small>{hint}</small>}</label>;}
function Units({value:unit,onChange}:{value:ExperimentConfig['unityTimeUnit'];onChange:(value:ExperimentConfig['unityTimeUnit'])=>void}){return <select value={unit} onChange={e=>onChange(e.target.value as ExperimentConfig['unityTimeUnit'])}><option value="seconds">秒</option><option value="milliseconds">ミリ秒</option><option value="datetime">日時</option></select>;}
interface Props {
  summary:DatasetSummary|null;unity:UnitySummary|null;config:ExperimentConfig|null;result:ExperimentResult|null;analysis:AnalysisResult|null;
  disabled:boolean;stale:boolean;analysisStale:boolean;
  onConfig:(value:ExperimentConfig)=>void;onLoad:(files:ExperimentFile[])=>Promise<void>;onUnity:(file:File)=>Promise<void>;
  onSync:()=>Promise<void>;onSave:(figures:Record<string,Figure>)=>Promise<void>;onConfigure:()=>void;
  onError:(message:string)=>void;onNotice:(message:string)=>void;
}
export default function ExperimentPanel(props:Props){
  const {summary,unity,config,result,analysis,disabled}=props;
  const [files,setFiles]=useState<ExperimentFile[]>([]),[manualConfirmed,setManualConfirmed]=useState(false);
  const [metric,setMetric]=useState('pupil_mean'),[spectralAxis,setSpectralAxis]=useState('PC1');
  const fileInput=useRef<HTMLInputElement>(null),unityInput=useRef<HTMLInputElement>(null),settingsInput=useRef<HTMLInputElement>(null);
  const figures=useMemo(()=>result?experimentFigures(result,analysis,metric,spectralAxis):null,[result,analysis,metric,spectralAxis]);
  const update=<K extends keyof ExperimentConfig>(key:K,newValue:ExperimentConfig[K])=>{if(config){const next={...config,[key]:newValue};if(['spectraTimeMode','spectraTimeColumn','spectraTimeUnit','unityTimeColumn','unityTimeUnit','unityStartTime','timeOffsetSeconds','manualPhases'].includes(key))delete next.anchorConfirmation;props.onConfig(next);setManualConfirmed(false);}};
  const choose=(selected:FileList|null)=>{if(!selected)return;const next=Array.from(selected).map(file=>({file,phase:detectExperimentRole(file.name)}));setFiles(next);if(fileInput.current)fileInput.current.value='';};
  const times=summary?.experiment?.timeColumns??[];
  const anchorRequired=config?.spectraTimeMode==='column'&&config.spectraTimeUnit==='datetime'&&config.unityTimeUnit!=='datetime';
  const manual=config?.spectraTimeMode==='manual';
  const syncBlocked=!config||!unity||!summary?.experiment||!!(anchorRequired&&!config.unityStartTime)||manual&&!manualConfirmed;
  async function readSettings(file?:File){if(settingsInput.current)settingsInput.current.value='';if(!file)return;try{if(file.size>1024*1024)throw new Error('同期設定は1 MiB以下にしてください。');props.onConfig(parseExperimentSettings(await file.text()));setManualConfirmed(false);props.onNotice('同期設定を読み込みました。元データと時刻対応を確認し、同期を実行してください。');}catch(error){props.onError(error instanceof Error?error.message:String(error));}}
  function taskAnchor(){
    if(!config||!summary?.experiment)return;
    const anchors=summary.experiment.phaseTimeAnchors;
    const anchor=anchors?.find(a=>a.phase==='Task'&&a.column===config.spectraTimeColumn);
    if(!anchor){props.onError('Task先頭の時刻を取得できません。確認したUnity開始日時を入力してください。');return;}
    if(config.spectraTimeUnit==='datetime')props.onConfig({...config,unityStartTime:String(anchor.value),timeOffsetSeconds:0,anchorConfirmation:'user-confirmed-task-first'});
    else props.onConfig({...config,timeOffsetSeconds:-Number(anchor.value)/(config.spectraTimeUnit==='milliseconds'?1000:1),anchorConfirmation:'user-confirmed-task-first'});
    props.onNotice('Task先頭をUnity 0秒に対応づけました。補正秒と時刻の精度を確認してください。');
  }
  return <div className="experiment-workspace">
    <div className="page-heading"><div><div className="eyebrow">EXPERIMENT / UNITY</div><h1>フェーズと生理指標の比較</h1><p>Baseline・Task・Recoveryのスペクトルをまとめ、Unityログを測定時刻に対応づけます。</p></div><button className="button outline" onClick={props.onConfigure} disabled={!summary||disabled}>スペクトルの解析設定<ArrowRight size={15}/></button></div>
    <input type="file" multiple accept=".csv,text/csv" ref={fileInput} className="visually-hidden" aria-label="実験CSVを一括選択" onChange={e=>choose(e.target.files)} disabled={disabled}/>
    <input type="file" accept=".csv,text/csv" ref={unityInput} className="visually-hidden" aria-label="UnityログCSV" onChange={e=>{const file=e.target.files?.[0];if(file)void props.onUnity(file);e.target.value='';}} disabled={disabled}/>
    <input type="file" accept=".json,application/json" ref={settingsInput} className="visually-hidden" aria-label="実験同期設定JSON" onChange={e=>void readSettings(e.target.files?.[0])} disabled={disabled||!config}/>
    <section className="glass-panel experiment-card">
      <div className="experiment-heading"><span className="step-index">01</span><div><h2>実験CSVを一括で読み込む</h2><p>3フェーズのCSVとUnityログを同時に選択できます。ファイル名からの割当を確認して読み込んでください。</p></div></div>
      <div className="experiment-actions"><button className="button outline" onClick={()=>fileInput.current?.click()} disabled={disabled}><Plus size={15}/>CSVを選択</button>{files.length>0&&<button className="button primary" onClick={()=>void props.onLoad(files)} disabled={disabled||!files.some(f=>f.phase!=='Unity')}><Upload size={15}/>選択した{files.length}ファイルを読み込む</button>}</div>
      {files.length>0&&<div className="experiment-files">{files.map((entry,i)=><div key={`${entry.file.name}-${i}`}><FileSpreadsheet size={16}/><span title={entry.file.name}>{entry.file.name}<small>{(entry.file.size/1024).toFixed(1)} KB</small></span><label><span className="visually-hidden">{entry.file.name}の割当</span><select value={entry.phase} disabled={disabled} onChange={e=>setFiles(old=>old.map((f,j)=>j===i?{...f,phase:e.target.value as ExperimentFileRole}:f))}>{[...phaseOrder,'Unity'].map(phase=><option key={phase}>{phase}</option>)}</select></label><button className="icon-button" aria-label={`${entry.file.name}を選択から除く`} disabled={disabled} onClick={()=>setFiles(old=>old.filter((_,j)=>i!==j))}><X size={14}/></button></div>)}</div>}
      {summary?.experiment&&<div className="experiment-loaded"><span><Check size={14}/>読込済み：{summary.rowCount}スペクトル / {summary.wavelengthColumns.length}波長</span><div>{summary.experiment.files.map((file,i)=><span key={`${file.name}-${i}`} title={file.name}>{file.phase}<strong>{file.rows}</strong>試料</span>)}</div><p>グループ列はexperiment_phaseです。既存のPCA・Aquagramでも3フェーズを比較できます。</p></div>}
      <div className="experiment-unity"><div><strong>{unity?unity.name:'Unityログは未読込です'}</strong><span>{unity?`${unity.rowCount.toLocaleString()}行 / ${unity.columns.length}列`:'スペクトルだけを先に読み込み、後からUnityログを追加することもできます。'}</span></div><button className="button subtle" disabled={disabled||!summary?.experiment} onClick={()=>unityInput.current?.click()}><Upload size={14}/>{unity?'Unityログを変更':'Unityログを追加'}</button></div>
      {unity&&<details className="experiment-mappings"><summary>検出した生理指標の列を確認</summary><dl>{Object.entries(unity.metricColumns).map(([key,column])=><div key={key}><dt>{key}</dt><dd>{Array.isArray(column)?column.join(' / '):typeof column==='object'?JSON.stringify(column):String(column??'検出なし')}</dd></div>)}</dl></details>}
      {[...(summary?.experiment?.warnings??[]),...(unity?.warnings??[])].length>0&&<ul className="experiment-notes">{[...(summary?.experiment?.warnings??[]),...(unity?.warnings??[])].map((note,i)=><li key={i}>{note}</li>)}</ul>}
    </section>
    {config&&summary?.experiment&&<>
      <section className="glass-panel experiment-card">
        <div className="experiment-heading"><span className="step-index">02</span><div><h2>測定時刻とUnityの時計を合わせる</h2><p>同じ時刻の記録か、確認した開始時刻・相対秒で対応づけます。時刻の不足を行番号で自動補完しません。</p></div></div>
        <fieldset className="experiment-fieldset" disabled={disabled}>
          <div className="experiment-grid">
            <Field label="スペクトルの測定時刻"><select value={config.spectraTimeMode} onChange={e=>update('spectraTimeMode',e.target.value as ExperimentConfig['spectraTimeMode'])}><option value="column">CSVの時刻列を使用</option><option value="manual">フェーズごとの開始秒・測定間隔を指定</option></select></Field>
            {!manual&&<><Field label="スペクトル時刻列"><select value={config.spectraTimeColumn??''} onChange={e=>{const selected=times.find(t=>t.column===e.target.value);props.onConfig({...config,spectraTimeColumn:e.target.value||null,spectraTimeUnit:selected?.kind==='datetime'?'datetime':'seconds',anchorConfirmation:undefined});}}><option value="">列を選択</option>{summary.columns.filter(c=>!summary.wavelengthColumns.some(w=>w.column===c)).map(column=><option key={column}>{column}</option>)}</select></Field><Field label="スペクトル時刻の単位"><Units value={config.spectraTimeUnit} onChange={unit=>update('spectraTimeUnit',unit)}/></Field></>}
            <Field label="Unity時刻列"><select value={config.unityTimeColumn} onChange={e=>update('unityTimeColumn',e.target.value)}>{(unity?.columns??[config.unityTimeColumn]).map(column=><option key={column}>{column}</option>)}</select></Field>
            <Field label="Unity時刻の単位"><Units value={config.unityTimeUnit} onChange={unit=>update('unityTimeUnit',unit)}/></Field>
            <Field label="時刻補正 / 秒" hint="スペクトルの対応時刻に加算する値。+5はUnityログの5秒後に対応。"><input type="number" step="0.1" value={config.timeOffsetSeconds} onChange={e=>update('timeOffsetSeconds',Number(e.target.value))}/></Field>
          </div>
          {manual?<><div className="experiment-manual"><p>Unityの0秒を基準に、各CSVの先頭行の開始秒と、行ごとの測定間隔を指定してください。確認できない場合は時刻同期の結果として扱えません。</p>{phaseOrder.filter(phase=>summary.experiment?.phases.includes(phase)).map(phase=><div key={phase}><strong>{phase}</strong><Field label="先頭行の開始秒"><input type="number" step="0.1" value={config.manualPhases[phase].startSeconds} onChange={e=>update('manualPhases',{...config.manualPhases,[phase]:{...config.manualPhases[phase],startSeconds:Number(e.target.value)}})}/></Field><Field label="行間の測定間隔 / 秒"><input type="number" min="0.001" step="0.1" value={config.manualPhases[phase].intervalSeconds} onChange={e=>update('manualPhases',{...config.manualPhases,[phase]:{...config.manualPhases[phase],intervalSeconds:Number(e.target.value)}})}/></Field></div>)}</div><label className="experiment-confirm"><input type="checkbox" checked={manualConfirmed} onChange={e=>setManualConfirmed(e.target.checked)}/>この開始秒と測定間隔が実際の測定記録に対応することを確認しました。</label></>:anchorRequired?<div className="experiment-anchor"><Field label="Unityの0秒に対応する日時" hint="測定と同じ時計の日時を入力してください。ファイルの保存日時から推定しません。"><input type="text" placeholder="例：2026-01-01 12:00:00" value={config.unityStartTime??''} onChange={e=>update('unityStartTime',e.target.value||null)} required/></Field><button className="button outline" onClick={taskAnchor} type="button"><Clock3 size={14}/>Task先頭をUnity 0秒にする</button><p>この対応が実験記録で確認できている場合に選択してください。分単位の時刻しかない記録では、秒以下の対応は確定できません。</p></div>:<p className="field-note">相対秒を使用する場合は両方の0秒を同じ基準に合わせてください。必要なら時刻補正で調整します。</p>}
          <div className="setting-divider"/>
          <div className="experiment-grid"><Field label="集計窓の幅 / 秒" hint="各スペクトルの対応時刻を中心とする窓。"><input type="number" min="0.001" max="3600" step="0.5" value={config.windowSeconds} onChange={e=>update('windowSeconds',Number(e.target.value))}/></Field><Field label="欠測とみなすログ間隔 / 秒"><input type="number" min="0.001" max="60" step="0.05" value={config.maxGapSeconds} onChange={e=>update('maxGapSeconds',Number(e.target.value))}/></Field><Field label="最低カバー率 / %"><input type="number" min="0" max="100" step="5" value={config.minCoverage*100} onChange={e=>update('minCoverage',Number(e.target.value)/100)}/></Field><Field label="窓内の最低サンプル数"><input type="number" min="2" step="1" value={config.minSamples} onChange={e=>update('minSamples',Number(e.target.value))}/></Field></div>
          <details className="experiment-advanced"><summary>瞬き候補の検出条件</summary><p>左右の眼開度から閉眼区間を検出します。視線追跡の欠測や装置の判定と区別できない候補を含みます。しきい値を変えた結果も確認してください。</p><div className="experiment-grid"><Field label="眼開度の閉眼しきい値"><input type="number" min="0" max="1" step="0.05" value={config.blinkThreshold} onChange={e=>update('blinkThreshold',Number(e.target.value))}/></Field><Field label="候補の最短時間 / 秒"><input type="number" min="0.001" step="0.01" value={config.blinkMinSeconds} onChange={e=>update('blinkMinSeconds',Number(e.target.value))}/></Field><Field label="候補の最長時間 / 秒"><input type="number" min="0.001" max="10" step="0.05" value={config.blinkMaxSeconds} onChange={e=>update('blinkMaxSeconds',Number(e.target.value))}/></Field></div></details>
        </fieldset>
        <div className="experiment-actions"><button className="button primary" disabled={disabled||syncBlocked} onClick={()=>void props.onSync()}><Link2 size={15}/>{result?'時刻対応を再計算':'時刻同期と生理指標の集計を実行'}<ArrowRight size={15}/></button><button className="button outline" disabled={disabled} onClick={()=>{try{downloadBytes(strToU8(JSON.stringify(createExperimentSettings(config),null,2)),'experiment-settings.json','application/json');}catch(error){props.onError(error instanceof Error?error.message:String(error));}}}><ArrowDownToLine size={14}/>同期設定を保存</button><button className="button subtle" disabled={disabled} onClick={()=>settingsInput.current?.click()}><Upload size={14}/>同期設定を読込</button></div>
        {syncBlocked&&<p className="field-note">{!unity?'Unityログを追加してください。':anchorRequired&&!config.unityStartTime?'Unityの0秒に対応する日時を設定してください。':manual&&!manualConfirmed?'開始秒と測定間隔を入力し、測定記録との対応を確認してください。':''}</p>}
        {!analysis&&<p className="field-note">生理指標の集計は先に実行できます。PCA・前処理後スペクトルとの比較には、スペクトル解析を実行してから同期を再計算してください。</p>}
        {props.analysisStale&&<p className="field-note">スペクトルの解析設定に未適用の変更があります。比較には直前に完了したスペクトル解析を使用します。</p>}
      </section>
    </>}
    {result&&figures&&<>
      <div className="experiment-result-heading"><div><span className="eyebrow">SYNCHRONIZED RESULTS</span><h2>同期結果と対応率</h2></div><button className="button outline" disabled={disabled} onClick={()=>void props.onSave(figures)}><ArrowDownToLine size={15}/>実験比較を保存</button></div>
      {props.stale&&<div className="notice stale"><RefreshCw size={15}/><span>同期設定が変更されています。表示と保存は、直前に完了した同期結果と適用設定です。</span></div>}
      <div className="experiment-phase-cards">{result.phaseSummaries.map(phase=><section className="glass-panel" key={phase.phase}><span>{phase.phase}</span><strong>{phase.matchedSpectra}<small> / {phase.totalSpectra} 試料</small></strong><p>集計条件を満たした対応試料</p></section>)}</div>
      {result.warnings.length>0&&<div className="experiment-warning glass-panel"><strong>時刻と解析の確認事項</strong><ul>{result.warnings.map((warning,i)=><li key={i}>{warning}</li>)}</ul></div>}
      <section className="glass-panel experiment-card experiment-coverage"><h2>試料ごとの時刻対応</h2><p>対応するログがない試料、カバー率が不足する試料は集計・相関から除外します。最初の100行を表示し、CSVには全行を保存します。</p><div className="experiment-table-scroll"><table><thead><tr><th>フェーズ / 試料</th><th>対応時刻 / 秒</th><th>ログ数</th><th>カバー率</th><th>判定</th></tr></thead><tbody>{result.rows.slice(0,100).map(row=><tr key={row.id}><th>{row.phase}<small>{row.id}</small></th><td>{value(row.timeSeconds)}</td><td>{row.unitySamples}</td><td>{percent(row.coverage)}</td><td>{row.valid?'対応済み':row.reason||'対象外'}</td></tr>)}</tbody></table></div></section>
      <div className="experiment-result-controls"><Field label="比較する生理指標"><select value={metric} onChange={e=>setMetric(e.target.value)}>{result.metrics.map(item=><option key={item.key} value={item.key}>{item.label}{item.unit?` / ${item.unit}`:''}</option>)}</select></Field>{analysis&&<Field label="散布図のスペクトル側の値"><select value={spectralAxis} onChange={e=>setSpectralAxis(e.target.value)}>{analysis.pca.explainedVariance.map((_,i)=><option key={`PC${i+1}`}>PC{i+1}</option>)}{analysis.spectra.wavelengths.map(w=><option value={String(w)} key={w}>{w} nm（前処理後）</option>)}</select></Field>}</div>
      <div className="experiment-chart-grid"><section className="glass-panel experiment-chart"><Plot figure={figures.phase_summary} label="フェーズ別の生理指標"/></section><section className="glass-panel experiment-chart"><Plot figure={figures.unity_timeline} label="Unityの瞳孔径時系列と瞬き候補"/><p>下辺の灰色の帯は瞬き候補の区間です。表示用時系列は間引き、集計には全行を使用します。</p></section>{analysis&&<><section className="glass-panel experiment-chart"><Plot figure={figures.physiology_scatter} label="スペクトルと生理指標の散布図"/></section><section className="glass-panel experiment-chart"><Plot figure={figures.spectral_correlations} label="波長ごとのスペクトルと生理指標の相関"/></section></>}</div>
      {analysis&&<section className="glass-panel experiment-card"><h2>PCAとの相関</h2><div className="experiment-table-scroll"><table><thead><tr><th>指標</th>{analysis.pca.explainedVariance.map((_,i)=><th key={i}>PC{i+1} · r / n</th>)}</tr></thead><tbody>{result.correlations.map(c=><tr key={c.metric}><th>{result.metrics.find(m=>m.key===c.metric)?.label??c.metric}</th>{c.pca.map(p=><td key={p.component}>{value(p.r)} / {p.n}</td>)}</tr>)}</tbody></table></div></section>}
      <p className="experiment-footnote">Pearson相関は対応試料が3件以上あり、値に分散がある場合に算出します。反復測定・重なる時間窓・フェーズの影響を含む探索的な比較です。因果関係や独立した試料数を示すものではありません。フェーズ平均は対応したスペクトルの窓ごとの集計値で、連続ログ全体の平均とは異なります。</p>
      <section className="glass-panel experiment-card"><h2>結果CSVを個別に保存</h2><div className="experiment-actions">{Object.entries(result.exports).filter(([name])=>name.endsWith('.csv')).map(([name,contents])=><button className="button subtle" key={name} disabled={disabled} onClick={()=>downloadBytes(strToU8('\uFEFF'+contents.replace(/^\uFEFF/,'')),name.split('/').at(-1)??name,'text/csv;charset=utf-8')}><ArrowDownToLine size={13}/>{name.split('/').at(-1)}</button>)}</div></section>
    </>}
  </div>;
}
