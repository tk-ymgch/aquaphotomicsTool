import {useEffect, useMemo, useRef, useState} from 'react';
import type {CSSProperties, PointerEvent as ReactPointerEvent, ReactNode} from 'react';
import {ArrowDownToLine, ArrowLeft, ArrowRight, Maximize2, Minimize2, Pause, Play, RefreshCw, Upload, X} from 'lucide-react';
import {strToU8, zipSync} from 'fflate';
import type {AnalysisResult, ExperimentResult} from './types';
import {downloadBytes} from './downloads';
import {aquagramRms, explorerAxis, explorerCsv, explorerDisplayIndices, explorerIndices, explorerPoint, explorerScale, nearestExplorerIndex, orderedExplorerIndices, playbackDelay, seriesColumns, validExplorerSamples} from './aquagramExplorerData';
import type {ExplorerAxis, ExplorerSettings} from './aquagramExplorerData';
import {fitFormationModel} from './aquagramModel';
import './explorer.css';

const num = (value: number, digits = 3) => Number.isFinite(value) ? value.toLocaleString('ja-JP', {maximumFractionDigits: digits}) : '—';
const colours = ['#15191b', '#5c6266', '#939b9f', '#373d41', '#bcc3c6', '#737a7d'];
const initialSettings = (): ExplorerSettings => ({seriesColumn:'', seriesValue:'', timeColumn:'', timeUnit:'seconds', speed:30, selectedId:'', activeCoordinate:null, yaw:-.36, tilt:.72});
const path = (points: [number,number][], close = false) => points.map(([x,y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ') + (close ? ' Z' : '');
function Panel({number,title,subtitle,children,className=''}:{number:string;title:string;subtitle:string;children:ReactNode;className?:string}) { return <section className={`aqx-panel glass-panel ${className}`}><div className="aqx-panel-head"><span>{number}</span><div><h2>{title}</h2><p>{subtitle}</p></div></div>{children}</section>; }
function CoordinateLabel({aq,index}:{aq:AnalysisResult['aquagram'];index:number}) { return <>{aq.labels[index]} <small>{aq.coordinateRanges?.[index] ? `${aq.coordinateRanges[index].map(v=>num(v,1)).join('–')} nm` : `${num(aq.wavelengths[index],1)} nm`}</small></>; }

export default function AquagramExplorer({result,experiment,stale,onConfigure,onError}:{result:AnalysisResult|null;experiment?:ExperimentResult|null;stale?:boolean;onConfigure:()=>void;onError:(message:string)=>void}) {
  const [settings,setSettings] = useState<ExplorerSettings>(initialSettings);
  const [playing,setPlaying] = useState(false), [expanded,setExpanded] = useState(false), [nativeFullscreen,setNativeFullscreen] = useState(false);
  const [modelEnabled,setModelEnabled] = useState(false), [modelDelay,setModelDelay] = useState(0), [modelGroup,setModelGroup] = useState('');
  const [presentation,setPresentation]=useState<'overview'|'detail'>('overview');
  const [frame,setFrame]=useState({width:0,height:0});
  const host = useRef<HTMLDivElement>(null), stateInput = useRef<HTMLInputElement>(null);
  const drag = useRef<{x:number;y:number;yaw:number;tilt:number}|null>(null);
  const aq = result?.aquagram, samples = aq?.samples;
  const available = !!aq && validExplorerSamples(aq);
  const columns = useMemo(()=>samples ? seriesColumns(samples) : [],[samples]);
  const axis = useMemo(()=>samples ? explorerAxis(samples,settings.timeColumn,settings.timeUnit,experiment) : {values:[],label:'試料の順序',unit:'試料番号',kind:'order' as const,warnings:[]},[samples,settings.timeColumn,settings.timeUnit,experiment]);
  const indices = useMemo(()=>samples ? orderedExplorerIndices(explorerIndices(samples,settings.seriesColumn,settings.seriesValue),axis) : [],[samples,settings.seriesColumn,settings.seriesValue,axis]);
  const selected = samples ? indices.find(index=>samples.ids[index]===settings.selectedId) ?? indices[0] ?? -1 : -1;
  const position = indices.indexOf(selected);
  const scale = useMemo(()=>samples ? explorerScale(samples.values) : 1,[samples]);
  const stacked = useMemo(()=>explorerDisplayIndices(indices,selected,90),[indices,selected]);
  const heatIndices = useMemo(()=>explorerDisplayIndices(indices,selected,300),[indices,selected]);
  const traceIndices = useMemo(()=>explorerDisplayIndices(indices,selected,2000),[indices,selected]);
  const rms = useMemo(()=>samples ? samples.values.map(aquagramRms) : [],[samples]);
  const fitIndices = samples ? indices.filter(index=>!modelGroup || samples.groups[index]===modelGroup) : [];
  const model = useMemo(()=>{
    if (!modelEnabled || !samples || result?.paper) return {fit:null,error:''};
    try { return {fit:fitFormationModel(indices.filter(index=>!modelGroup || samples.groups[index]===modelGroup).map(index=>({time:axis.values[index],value:rms[index]})),{delay:modelDelay}),error:''}; }
    catch(error) { return {fit:null,error:error instanceof Error ? error.message : String(error)}; }
  },[modelEnabled,modelDelay,modelGroup,samples,indices,axis,rms,result?.paper]);
  const set = <K extends keyof ExplorerSettings>(key:K,value:ExplorerSettings[K])=>setSettings(old=>({...old,[key]:value}));
  const select = (index:number)=>{if(samples && index>=0){set('selectedId',samples.ids[index]);}};
  useEffect(()=>{
    const next=initialSettings(),paper=result?.paper,metadata=samples?.metadata;
    if(paper&&metadata?.paper_series&&metadata.paper_time_seconds){
      const first=paper.rows.findIndex(row=>row.isTask);
      if(first>=0){next.seriesColumn='paper_series';next.seriesValue=String(metadata.paper_series[first]);next.timeColumn='paper_time_seconds';next.selectedId=paper.rows[first].id;}
    }
    setSettings(next);setPlaying(false);setModelEnabled(false);setModelGroup('');setModelDelay(0);
  },[result]);
  useEffect(()=>{setPlaying(false);},[settings.seriesColumn,settings.seriesValue,settings.timeColumn,settings.timeUnit]);
  useEffect(()=>{
    if (!playing || !samples || position<0 || indices.length<2) return;
    if (position>=indices.length-1) {setPlaying(false);return;}
    const next = indices[position+1], timer = window.setTimeout(()=>setSettings(old=>({...old,selectedId:samples.ids[next]})),playbackDelay(axis.values[selected],axis.values[next],axis.kind,settings.speed));
    return ()=>window.clearTimeout(timer);
  },[playing,samples,position,indices,selected,axis,settings.speed]);
  useEffect(()=>{const listener=()=>{setNativeFullscreen(document.fullscreenElement===host.current);if(document.fullscreenElement===host.current)setExpanded(false);};document.addEventListener('fullscreenchange',listener);return()=>document.removeEventListener('fullscreenchange',listener);},[]);
  useEffect(()=>{
    if(!expanded)return;
    const previous=document.body.style.overflow,previousFocus=document.activeElement;
    document.body.style.overflow='hidden';host.current?.focus();
    const keydown=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();setExpanded(false);return;}
      if(event.key!=='Tab')return;
      const controls=Array.from(host.current?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),input:not(:disabled):not([type="file"]),[tabindex="0"]')??[]).filter(element=>element.offsetParent!==null);
      if(!controls.length){event.preventDefault();host.current?.focus();return;}
      const first=controls[0],last=controls.at(-1)!;
      if(event.shiftKey&&(document.activeElement===first||document.activeElement===host.current)){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&(document.activeElement===last||document.activeElement===host.current)){event.preventDefault();first.focus();}
    };
    document.addEventListener('keydown',keydown);
    return()=>{document.body.style.overflow=previous;document.removeEventListener('keydown',keydown);if(previousFocus instanceof HTMLElement&&previousFocus.isConnected)previousFocus.focus();};
  },[expanded]);
  useEffect(()=>()=>{if(document.fullscreenElement===host.current)void document.exitFullscreen().catch(()=>{});},[]);
  useEffect(()=>{
    const measure=()=>{const element=host.current;if(!element)return;const box=element.getBoundingClientRect(),style=getComputedStyle(element);setFrame({width:box.width-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),height:window.innerHeight-box.top-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom)-(document.fullscreenElement===element||expanded?0:10)});};
    const observer=new ResizeObserver(measure);if(host.current){observer.observe(host.current);if(host.current.parentElement)observer.observe(host.current.parentElement);}window.addEventListener('resize',measure);const request=requestAnimationFrame(measure);
    return()=>{observer.disconnect();window.removeEventListener('resize',measure);cancelAnimationFrame(request);};
  },[result,expanded,nativeFullscreen,presentation]);
  async function fullscreen(){
    if(document.fullscreenElement===host.current){await document.exitFullscreen();return;}
    if(expanded){setExpanded(false);return;}
    try {if(!host.current?.requestFullscreen)throw new Error('unavailable');await host.current.requestFullscreen();}catch{setExpanded(true);}
  }
  function stateDocument(){return {format:'aquaphotomics-explorer',version:1,settings:{...settings,selectedId:samples?.ids[selected]??''},selection:{sourceRow:selected,visiblePosition:position,visibleCount:indices.length,metadata:Object.fromEntries(Object.entries(samples?.metadata??{}).map(([key,column])=>[key,column[selected]??null]))},model:{enabled:modelEnabled,delay:modelDelay,group:modelGroup,fit:model.fit,error:model.error},coordinates:{labels:aq?.labels,wavelengths:aq?.wavelengths,ranges:aq?.coordinateRanges},axis:{label:axis.label,unit:axis.unit,kind:axis.kind,selectedValue:axis.values[selected]??null},calculation:{definition:samples?.definition,mode:aq?.mode,unit:aq?.unit,reference:aq?.reference,analysisSettings:result?.metadata.settings},scale:{maximumAbsoluteValueOrOneIfZero:scale,radialDefinition:'radius = 1 + 0.58 * value / scale; radius 1 is zero; scale uses all samples'}};}
  function saveState(){downloadBytes(strToU8(JSON.stringify(stateDocument(),null,2)),'aquagram-explorer-settings.json','application/json');}
  async function readState(file?:File){
    if(!file)return;
    try{
      if(file.size>1024*1024)throw new Error('表示設定は1 MiB以内のJSONを指定してください。');
      const doc=JSON.parse(await file.text()),value=doc?.settings;
      if(doc?.format!=='aquaphotomics-explorer'||doc?.version!==1||!value||JSON.stringify(doc.coordinates?.labels)!==JSON.stringify(aq?.labels)||JSON.stringify(doc.coordinates?.wavelengths)!==JSON.stringify(aq?.wavelengths)||JSON.stringify(doc.coordinates?.ranges)!==JSON.stringify(aq?.coordinateRanges))throw new Error('このAquagramと座標が一致する表示設定を選択してください。');
      const next=initialSettings();
      if(typeof value.seriesColumn!=='string'||typeof value.seriesValue!=='string'||typeof value.timeColumn!=='string'||!['seconds','milliseconds','datetime','numeric'].includes(value.timeUnit)||![1,5,10,30,60].includes(value.speed)||!Number.isFinite(value.yaw)||!Number.isFinite(value.tilt)||value.tilt<.15||value.tilt>1.3)throw new Error('表示設定の値が不正です。');
      if(value.seriesColumn && !columns.some(column=>column.key===value.seriesColumn))throw new Error('系列の列が現在のデータにありません。');
      if(value.seriesColumn && value.seriesValue && !columns.find(column=>column.key===value.seriesColumn)?.values.includes(value.seriesValue))throw new Error('保存された系列が現在のデータにありません。');
      if(value.timeColumn && value.timeColumn!=='$synchronized' && !Object.hasOwn(samples?.metadata??{},value.timeColumn))throw new Error('時刻の列が現在のデータにありません。');
      if(value.timeColumn==='$synchronized'&&!experiment?.rows.length)throw new Error('保存した横軸を再現するには、先にUnityとの時刻同期を実行してください。');
      for(const key of Object.keys(next) as (keyof ExplorerSettings)[])if(Object.hasOwn(value,key))(next as Record<string,unknown>)[key]=value[key];
      if(typeof next.selectedId!=='string'||next.activeCoordinate!==null&&(!Number.isInteger(next.activeCoordinate)||next.activeCoordinate<0||next.activeCoordinate>=(aq?.labels.length??0)))throw new Error('選択試料・座標の設定が不正です。');
      if(next.selectedId&&!samples?.ids.includes(next.selectedId))throw new Error('保存した選択試料が現在のデータにありません。');
      setSettings(next);setPlaying(false);setModelEnabled(!result?.paper&&doc.model?.enabled===true);setModelDelay(typeof doc.model?.delay==='number'&&Number.isFinite(doc.model.delay)&&doc.model.delay>=0?doc.model.delay:0);setModelGroup(typeof doc.model?.group==='string'?doc.model.group:'');
    }catch(error){onError(error instanceof Error?error.message:String(error));}
    finally{if(stateInput.current)stateInput.current.value='';}
  }
  function saveView(){
    if(!samples||!aq)return;
    try{
      const files:Record<string,Uint8Array>={'explorer-settings.json':strToU8(JSON.stringify(stateDocument(),null,2)),'aquagram-visible-samples.csv':strToU8('\uFEFF'+explorerCsv(samples,aq.labels,axis,indices)),'aquagram-all-samples.json':strToU8(JSON.stringify({coordinates:{labels:aq.labels,wavelengths:aq.wavelengths,ranges:aq.coordinateRanges},samples,analysisSettings:result?.metadata.settings,model:model.fit},null,2))};
      const chartNames:string[]=[];
      host.current?.querySelectorAll<SVGSVGElement>('svg[data-explorer-chart]').forEach(svg=>{
        const copy=svg.cloneNode(true)as SVGSVGElement;copy.setAttribute('xmlns','http://www.w3.org/2000/svg');copy.style.background='#fff';
        const originals=[svg,...svg.querySelectorAll<SVGElement>('*')],copies=[copy,...copy.querySelectorAll<SVGElement>('*')];
        const paints=['font-family','font-size','font-weight','font-style','fill','fill-opacity','stroke','stroke-width','stroke-dasharray','stroke-opacity','opacity','text-anchor','dominant-baseline','visibility','display'];
        originals.forEach((element,index)=>{const style=window.getComputedStyle(element);for(const property of paints)copies[index].style.setProperty(property,style.getPropertyValue(property));});
        const name=`figures/${svg.dataset.explorerChart}.svg`;chartNames.push(name);files[name]=strToU8(new XMLSerializer().serializeToString(copy));
      });
      files['manifest.json']=strToU8(JSON.stringify({format:'aquaphotomics-explorer-export',version:1,sourceSamples:samples.ids.length,visibleSamples:indices.length,coordinates:aq.labels.length,figures:chartNames,displayLimits:{layeredSections:91,heatmapColumns:301,tracePoints:2001},dataFiles:['aquagram-all-samples.json','aquagram-visible-samples.csv','explorer-settings.json'],notes:['CSV and JSON retain exact calculated coordinate values; display thinning does not change data.','SVG paint and font styles are inlined; no external scripts, stylesheets, or data are required to view a figure.','Zero is the reference ring, not the center. The radial scale is shared across every frame.','The optional RMS model is an empirical curve, not a molecular formation model.']},null,2));
      files['README.txt']=strToU8('Aquaphotomics Workbench / Aquagram時系列探索\n\nexplorer-settings.jsonは同じ解析結果に表示設定を再適用するためのファイルです。\naquagram-all-samples.jsonは、全試料の解析値・座標定義・メタデータ・適用解析設定と、使用した場合の参考モデルを保存しています。\naquagram-visible-samples.csvは、表示する系列・横軸で絞った全試料を保存しています。図の間引きは数値ファイルには適用しません。\nfigures/には現在の選択試料・表示条件でのSVG図を保存しています。参考モデルを使用していない場合、モデル速度の図はありません。\nmanifest.jsonに図一覧と表示上限を記録しています。元の測定データはアプリ上部の「解析を保存」から保存してください。\n\nAquagramは吸収スペクトルの解析表示です。参考モデルはAquagram座標RMSの記述的な曲線であり、水分子種・分子形成過程・反応速度の推定を意味しません。\n');
      downloadBytes(zipSync(files,{level:6}),'aquagram-explorer.zip','application/zip');
    }catch(error){onError(error instanceof Error?error.message:String(error));}
  }
  function stagePointer(event:ReactPointerEvent<SVGSVGElement>){if(!drag.current)return;setSettings(old=>({...old,yaw:drag.current!.yaw+(event.clientX-drag.current!.x)/150,tilt:Math.max(.15,Math.min(1.3,drag.current!.tilt+(event.clientY-drag.current!.y)/200))}));}
  if(!result)return <section className="empty-results glass-panel"><Maximize2 size={32}/><h1>Aquagramの時系列探索</h1><p>データを読み込み、解析を実行すると試料ごとのパターンを表示できます。</p><button className="button primary" onClick={onConfigure}>解析設定へ<ArrowRight size={15}/></button></section>;
  if(!available||!aq||!samples)return <section className="empty-results glass-panel"><h1>この結果には試料別Aquagramがありません</h1><p>aquap2pyまたはWorkbench標準Pythonで再解析してください。R本体の参照結果は既存の群平均Aquagramで確認できます。</p><button className="button primary" onClick={onConfigure}>解析設定へ<ArrowRight size={15}/></button></section>;
  const overview=presentation==='overview';
  const fitOverview=overview&&frame.width>=880&&frame.height>=595&&aq.labels.length<=15;
  const active=settings.activeCoordinate,values=selected>=0?samples.values[selected]:[];
  const lo=indices.length?axis.values[indices[0]]:0,hi=indices.length?axis.values[indices.at(-1)!]:1,extent=hi-lo||1;
  const gridHeight=Math.max(300,frame.height-150),rowSpace=gridHeight-16;
  const doubleWidth=Math.max(540,(frame.width-16)*2/3+8-14),singleWidth=Math.max(280,(frame.width-16)/3-14);
  const rowHeights=[rowSpace*.355,rowSpace*.417,rowSpace*.228];
  const dims={
    stack:overview?{w:fitOverview?doubleWidth:Math.max(600,frame.width-20),h:fitOverview?Math.max(118,rowHeights[0]-34):220}:{w:1100,h:380},
    radar:overview?{w:300,h:180}:{w:440,h:360},
    heat:overview?{w:fitOverview?doubleWidth:Math.max(420,frame.width-20),h:fitOverview?Math.max(118,rowHeights[1]-34):Math.max(170,aq.labels.length*12+28)}:{w:700,h:Math.max(160,aq.labels.length*15+55)},
    trace:overview?{w:fitOverview?doubleWidth:Math.max(420,frame.width-20),h:fitOverview?Math.max(60,rowHeights[2]-34):190}:{w:700,h:250},
    rms:overview?{w:fitOverview?singleWidth:Math.max(320,frame.width-20),h:fitOverview?Math.max(118,(result.paper?rowHeights[1]+rowHeights[2]+8:rowHeights[1])-34):190}:{w:700,h:250},
    rate:overview?{w:fitOverview?singleWidth:Math.max(320,frame.width-20),h:fitOverview?Math.max(60,rowHeights[2]-34):170}:{w:700,h:250}
  };
  const coordinateName=(coordinate:number)=>aq.labels[coordinate]+' · '+(aq.coordinateRanges?.[coordinate]?aq.coordinateRanges[coordinate].map(value=>num(value,1)).join('–'):num(aq.wavelengths[coordinate],1))+' nm';
  const left=(kind:'heat'|'trace'|'rms'|'rate')=>kind==='heat'?72:overview?42:52;
  const right=(kind:'heat'|'trace'|'rms'|'rate')=>overview?dims[kind].w-12:640;
  const timeX=(index:number,kind:'heat'|'trace'|'rms'|'rate')=>left(kind)+(axis.values[index]-lo)/extent*(right(kind)-left(kind));
  const valueX=(time:number,kind:'rms'|'rate')=>left(kind)+(time-lo)/extent*(right(kind)-left(kind));
  const chooseAt=(event:ReactPointerEvent<SVGSVGElement>,kind:'heat'|'trace'|'rms'|'rate')=>{
    const svg=event.currentTarget,ctm=svg.getScreenCTM();
    if(!ctm)return;
    const point=new DOMPoint(event.clientX,event.clientY).matrixTransform(ctm.inverse());
    select(nearestExplorerIndex(indices,axis,lo+Math.max(0,Math.min(1,(point.x-left(kind))/(right(kind)-left(kind))))*extent));
  };
  const stackLeft=overview?56:96,stackRight=dims.stack.w-(overview?56:96);
  const stackBottom=dims.stack.h-(overview?27:65),stackCenter=overview?(stackBottom+7)/2:174;
  const stackTimeX=(value:number)=>hi===lo?dims.stack.w/2:stackLeft+(value-lo)/extent*(stackRight-stackLeft);
  const stackTicks=hi===lo?[lo]:Array.from({length:overview?5:6},(_,index)=>lo+(hi-lo)*index/(overview?4:5));
  const selectedAxisCount=indices.filter(index=>axis.values[index]===axis.values[selected]).length;
  const project=(coordinate:number,value:number,index:number):[number,number]=>{
    const [x,y]=explorerPoint(coordinate,aq.labels.length,value,scale);
    const rx=x*Math.cos(settings.yaw)-y*Math.sin(settings.yaw),ry=x*Math.sin(settings.yaw)+y*Math.cos(settings.yaw);
    return[stackTimeX(axis.values[index])+rx*(overview?22:43)*Math.sin(settings.tilt),stackCenter+ry*(overview?(stackBottom-16)/3.3:80)];
  };
  const rmmax=Math.max(indices.reduce((maximum,index)=>Math.max(maximum,rms[index]),1e-9),model.fit?.curve.reduce((maximum,point)=>Math.max(maximum,point.value),1e-9)??1e-9);
  const rateMax=Math.max(1e-9,...(model.fit?.curve.map(point=>Math.abs(point.rate))??[]));
  const chartY=(value:number,kind:'trace'|'rms'|'rate')=>{
    const top=overview?7:22,bottom=overview?dims[kind].h-25:202;
    return kind==='trace'?top+(scale-value)/(scale*2)*(bottom-top):bottom-value/(kind==='rms'?rmmax:rateMax)*(bottom-top);
  };
  const svgStyle=(kind:keyof typeof dims):CSSProperties=>overview?{width:'100%',height:'100%',minWidth:fitOverview?0:dims[kind].w}:{};
  const graphSlot=(kind:keyof typeof dims,content:ReactNode)=> <div className={'aqx-graph-slot aqx-'+kind+'-slot'} style={overview&&!fitOverview?{height:dims[kind].h}:undefined}>{content}</div>;
  const rotationTools=<div className="aqx-view-tools"><span>断面の向き</span><button className="icon-button" aria-label="Aquagram断面を左へ回転" onClick={()=>set('yaw',settings.yaw-Math.PI/6)}><ArrowLeft size={14}/></button><button className="icon-button" aria-label="Aquagram断面を右へ回転" onClick={()=>set('yaw',settings.yaw+Math.PI/6)}><ArrowRight size={14}/></button><button className="icon-button" aria-label="Aquagram断面の視点を戻す" onClick={()=>setSettings(old=>({...old,yaw:-.36,tilt:.72}))}><RefreshCw size={13}/></button></div>;
  const stackGraph=graphSlot('stack',<svg width={dims.stack.w} height={dims.stack.h} viewBox={'0 0 '+dims.stack.w+' '+dims.stack.h} role="img" aria-label={'横軸が'+axis.label+'のAquagram時間積層図'} data-explorer-chart="time-layered-aquagram" data-axis-kind={axis.kind} data-axis-unit={axis.unit} style={{...svgStyle('stack'),touchAction:'pan-x',cursor:'grab'}} onPointerDown={event=>{if(event.pointerType==='touch'||(event.target instanceof Element&&event.target.closest('circle')))return;drag.current={x:event.clientX,y:event.clientY,yaw:settings.yaw,tilt:settings.tilt};event.currentTarget.setPointerCapture(event.pointerId);}} onPointerMove={stagePointer} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}>
    <rect width={dims.stack.w} height={dims.stack.h} fill="white" fillOpacity="0"/>
    {stackTicks.map((tick,index)=><g key={index}><line x1={stackTimeX(tick)} x2={stackTimeX(tick)} y1={overview?6:30} y2={stackBottom} stroke="#e6ebed" strokeWidth=".8"/><line x1={stackTimeX(tick)} x2={stackTimeX(tick)} y1={stackBottom} y2={stackBottom+4} stroke="#a1abb1"/><text x={stackTimeX(tick)} y={stackBottom+(overview?13:24)} textAnchor="middle" fill="#65727b" fontSize={overview?9:12}>{num(tick,2)}</text></g>)}
    <line x1={stackLeft} x2={stackRight} y1={stackCenter} y2={stackCenter} stroke="#cbd2d6" strokeDasharray="4 5" strokeWidth=".8"/>
    {[indices[0],indices.at(-1)!].map((index,ring)=><path key={'zero-'+ring} d={path(aq.labels.map((_,coordinate)=>project(coordinate,0,index)),true)} fill="none" stroke="#8c969c" strokeDasharray="4 4" strokeWidth=".9"/>)}
    {stacked.filter(index=>index!==selected).map(index=><path key={index} d={path(aq.labels.map((_,coordinate)=>project(coordinate,samples.values[index][coordinate],index)),true)} data-sample-id={samples.ids[index]} data-center-x={stackTimeX(axis.values[index])} data-axis-value={axis.values[index]} fill="none" stroke="#b7bdc1" strokeWidth=".75" opacity=".5"><title>{samples.ids[index]+' · '+axis.label+': '+num(axis.values[index],6)+' '+axis.unit+' · '+(indices.indexOf(index)+1)+'/'+indices.length}</title></path>)}
    {aq.labels.map((_,coordinate)=><path key={coordinate} d={path(stacked.map(index=>project(coordinate,samples.values[index][coordinate],index)))} fill="none" stroke={active===coordinate?'#101315':'#8b9398'} strokeWidth={active===coordinate?2.5:.65} opacity={active===null||active===coordinate?.8:.15}><title>{coordinateName(coordinate)}</title></path>)}
    <path d={path(aq.labels.map((_,coordinate)=>project(coordinate,values[coordinate]??0,selected)),true)} data-sample-id={samples.ids[selected]} data-center-x={stackTimeX(axis.values[selected])} data-axis-value={axis.values[selected]} data-selected="true" fill="#333a4018" stroke="#101315" strokeWidth="2.3"><title>{samples.ids[selected]+' · '+num(axis.values[selected],6)+' '+axis.unit}</title></path>
    <line x1={stackTimeX(axis.values[selected])} x2={stackTimeX(axis.values[selected])} y1={overview?5:27} y2={stackBottom} stroke="#202a31" strokeWidth="1.5" strokeDasharray="5 4"/>
    {stacked.map(index=><circle key={index} cx={stackTimeX(axis.values[index])} cy={stackBottom} r={index===selected?4:2.6} fill={index===selected?'#202a31':'#a0aab0'} onClick={()=>{setPlaying(false);select(index);}} style={{cursor:'pointer'}}><title>{samples.ids[index]+' · '+num(axis.values[index],6)+' '+axis.unit}</title></circle>)}
    <line x1={stackLeft} x2={stackRight} y1={stackBottom} y2={stackBottom} stroke="#8d999f" strokeWidth="1" pointerEvents="none"/>
    <text x={dims.stack.w/2} y={dims.stack.h-3} textAnchor="middle" fill="#66747d" fontSize={overview?9:12}>{axis.label+' / '+axis.unit+' →'}</text>
  </svg>);
  const radarCx=overview?150:220,radarCy=overview?88:178,radarR=overview?36:82,labelR=overview?80:154;
  const radarGraph=graphSlot('radar',<svg viewBox={'0 0 '+dims.radar.w+' '+dims.radar.h} role="img" aria-label="選択試料のAquagram" data-explorer-chart="selected-aquagram" style={svgStyle('radar')}>
    {[-1,-.5,0,.5,1].map(tick=><g key={tick}><circle cx={radarCx} cy={radarCy} r={(1+.58*tick)*radarR} fill="none" stroke={tick===0?'#8c969c':'#e5e8ea'} strokeDasharray={tick===0?'4 4':undefined}/>{(!overview||Number.isInteger(tick))&&<text x={radarCx+3} y={overview?radarCy+(1+.58*tick)*radarR+3:radarCy-(1+.58*tick)*radarR-2} fill="#7a8388" fontSize={overview?12.5:9}>{num(tick*scale,2)}</text>}</g>)}
    {aq.labels.map((label,coordinate)=>{const angle=2*Math.PI*coordinate/aq.labels.length-Math.PI/2,side=Math.cos(angle);return <g key={coordinate}><line x1={radarCx} y1={radarCy} x2={radarCx+side*radarR*1.61} y2={radarCy+Math.sin(angle)*radarR*1.61} stroke="#eceff0"/><text x={radarCx+side*labelR} y={radarCy+4+Math.sin(angle)*labelR} textAnchor={overview&&Math.abs(side)>.1?side>0?'start':'end':'middle'} fontSize={overview?13:11} fill={active===coordinate?'#050707':'#667075'}>{label}</text></g>;})}
    <path d={path(values.map((value,coordinate)=>{const[x,y]=explorerPoint(coordinate,aq.labels.length,value,scale);return[radarCx+x*radarR,radarCy+y*radarR];}),true)} fill="#434d5312" stroke="#20272b" strokeWidth="2"/>
    {values.map((value,coordinate)=>{const[x,y]=explorerPoint(coordinate,aq.labels.length,value,scale);return <circle key={coordinate} cx={radarCx+x*radarR} cy={radarCy+y*radarR} r={active===coordinate?5:2.8} fill="#20272b" onPointerEnter={()=>set('activeCoordinate',coordinate)} onPointerLeave={()=>set('activeCoordinate',null)}><title>{coordinateName(coordinate)+': '+num(value,6)}</title></circle>;})}
  </svg>);
  const heatTop=overview?4:17,heatBottom=overview?dims.heat.h-19:aq.labels.length*15+17,heatStep=(heatBottom-heatTop)/aq.labels.length;
  const heatGraph=graphSlot('heat',<svg viewBox={'0 0 '+dims.heat.w+' '+dims.heat.h} role="img" aria-label="Aquagram座標のヒートマップ" data-explorer-chart="coordinate-heatmap" style={svgStyle('heat')} onPointerDown={event=>chooseAt(event,'heat')}>
    {aq.labels.map((label,coordinate)=><g key={coordinate}><text x={left('heat')-7} y={heatTop+coordinate*heatStep+heatStep*.76} textAnchor="end" fill="#6f787d" fontSize={overview?8.8:10}>{label}</text>{heatIndices.map((index,column)=>{const x0=column?(timeX(heatIndices[column-1],'heat')+timeX(index,'heat'))/2:left('heat'),x1=column===heatIndices.length-1?right('heat'):(timeX(index,'heat')+timeX(heatIndices[column+1],'heat'))/2,value=samples.values[index][coordinate],light=96-Math.abs(value)/scale*67;return <rect key={index} x={x0} y={heatTop+coordinate*heatStep} width={Math.max(.8,x1-x0)} height={Math.max(1,heatStep-1)} fill={value<0?'hsl(210 9% '+light+'%)':'hsl(0 0% '+light+'%)'} stroke={active===coordinate?'#20272b':'none'} strokeWidth=".7" onPointerDown={event=>{event.stopPropagation();setPlaying(false);select(index);}} onPointerEnter={()=>set('activeCoordinate',coordinate)} onPointerLeave={()=>set('activeCoordinate',null)}><title>{samples.ids[index]+' · '+coordinateName(coordinate)+': '+num(value,6)}</title></rect>;})}</g>)}
    <line x1={timeX(selected,'heat')} x2={timeX(selected,'heat')} y1={heatTop-1} y2={heatBottom} stroke="#13191d" strokeWidth="1.8" pointerEvents="none"/><text x={left('heat')} y={dims.heat.h-3} fill="#7d868b" fontSize={overview?9:10}>{num(lo)+' '+axis.unit}</text><text x={right('heat')} y={dims.heat.h-3} textAnchor="end" fill="#7d868b" fontSize={overview?9:10}>{num(hi)+' '+axis.unit}</text>
  </svg>);
  const cartesianAxis=(kind:'trace'|'rms'|'rate')=><>{(kind==='trace'?[-1,0,1]:[0,.5,1]).map(tick=>{const value=kind==='trace'?tick*scale:tick*(kind==='rms'?rmmax:rateMax),y=chartY(value,kind);return <g key={tick}><line x1={left(kind)} x2={right(kind)} y1={y} y2={y} stroke="#e7ebed" strokeDasharray={kind==='trace'&&tick===0?'4 4':undefined}/><text x={left(kind)-7} y={y+3} textAnchor="end" fill="#849096" fontSize={overview?9:10}>{num(value,2)}</text></g>;})}<text x={left(kind)} y={dims[kind].h-3} fill="#7f8a90" fontSize={overview?9:10}>{axis.label+' / '+axis.unit}</text><line x1={timeX(selected,kind)} x2={timeX(selected,kind)} y1={overview?5:20} y2={overview?dims[kind].h-25:204} stroke="#7c878d" strokeDasharray="3 4"/></>;
  const traceGraph=graphSlot('trace',<svg viewBox={'0 0 '+dims.trace.w+' '+dims.trace.h} role="img" aria-label="全座標の時間トレース" data-explorer-chart="coordinate-traces" style={svgStyle('trace')} onPointerDown={event=>chooseAt(event,'trace')}>{cartesianAxis('trace')}{aq.labels.map((_,coordinate)=><path key={coordinate} d={path(traceIndices.map(index=>[timeX(index,'trace'),chartY(samples.values[index][coordinate],'trace')]))} fill="none" stroke={colours[coordinate%colours.length]} strokeWidth={active===coordinate?2.6:1.15} strokeDasharray={coordinate%3===1?'6 3':coordinate%3===2?'2 2':undefined} opacity={active===null||active===coordinate?.9:.13}/>)}</svg>);
  const rmsGraph=graphSlot('rms',<svg viewBox={'0 0 '+dims.rms.w+' '+dims.rms.h} role="img" aria-label="Aquagram座標RMSと任意の経験モデル" data-explorer-chart="observed-rms-model" style={svgStyle('rms')} onPointerDown={event=>chooseAt(event,'rms')}>{cartesianAxis('rms')}<path d={path(indices.map(index=>[timeX(index,'rms'),chartY(rms[index],'rms')]))} fill="none" stroke="#909a9f" strokeWidth="1.2"/>{indices.map(index=><circle key={index} cx={timeX(index,'rms')} cy={chartY(rms[index],'rms')} r={index===selected?4.5:2} fill={index===selected?'#111a1f':'#909a9f'} onPointerDown={event=>{event.stopPropagation();select(index);}} style={{cursor:'pointer'}}><title>{samples.ids[index]+': RMS '+num(rms[index],6)}</title></circle>)}{model.fit&&<path d={path(model.fit.curve.map(point=>[valueX(point.time,'rms'),chartY(point.value,'rms')]))} fill="none" stroke="#111b21" strokeWidth="2" strokeDasharray="6 3"/>}</svg>);
  const rateGraph=model.fit?graphSlot('rate',<svg viewBox={'0 0 '+dims.rate.w+' '+dims.rate.h} role="img" aria-label="参考モデルの変化率" data-explorer-chart="model-rate" style={svgStyle('rate')} onPointerDown={event=>chooseAt(event,'rate')}>{cartesianAxis('rate')}<path d={path(model.fit.curve.map(point=>[valueX(point.time,'rate'),chartY(point.rate,'rate')]))} fill="none" stroke="#242e35" strokeWidth="2"/></svg>):<div className="aqx-model-empty"><span>MODEL RATE</span><h3>{modelEnabled&&model.error?'参考モデルを適用できません':'参考モデルは未実行です'}</h3><p>{modelEnabled&&model.error?model.error:'「系列・時刻・モデル設定」から有効にすると表示します。'}</p></div>;
  const coordinateLegend=<div className={'aqx-coordinate-legend '+(overview?'aqx-overview-legend':'')}>{aq.labels.map((_,coordinate)=><button key={coordinate} aria-pressed={active===coordinate} aria-label={coordinateName(coordinate)+'を強調'} title={coordinateName(coordinate)} onClick={()=>set('activeCoordinate',active===coordinate?null:coordinate)}><span style={{background:colours[coordinate%colours.length]}}/>{overview?aq.labels[coordinate]:<CoordinateLabel aq={aq} index={coordinate}/>}</button>)}</div>;
  const filters=<div className="aqx-filter-grid"><label className="field"><span>系列を分ける列</span><select value={settings.seriesColumn} onChange={event=>setSettings(old=>({...old,seriesColumn:event.target.value,seriesValue:'',selectedId:''}))}><option value="">すべての試料</option>{columns.map(column=><option key={column.key} value={column.key}>{column.key==='$group'?'解析グループ':column.key}</option>)}</select></label><label className="field"><span>表示する系列</span><select disabled={!settings.seriesColumn} value={settings.seriesValue} onChange={event=>{set('seriesValue',event.target.value);set('selectedId','');}}><option value="">すべて</option>{columns.find(column=>column.key===settings.seriesColumn)?.values.map(value=><option key={value}>{value}</option>)}</select></label><label className="field"><span>横軸に使う列</span><select value={settings.timeColumn} onChange={event=>{set('timeColumn',event.target.value);set('selectedId','');}}><option value="">試料の順序（時間ではありません）</option>{experiment?.rows.length&&<option value="$synchronized">Unityと同期した測定時刻</option>}{Object.keys(samples.metadata??{}).map(column=><option key={column}>{column}</option>)}</select></label><label className="field"><span>選んだ列の単位</span><select value={settings.timeUnit} disabled={!settings.timeColumn||settings.timeColumn==='$synchronized'} onChange={event=>set('timeUnit',event.target.value as ExplorerSettings['timeUnit'])}><option value="seconds">秒</option><option value="milliseconds">ミリ秒</option><option value="datetime">日時（最初の有効日時からの秒）</option><option value="numeric">数値（時間の単位なし）</option></select></label></div>;
  const modelControls=<div className="aqx-model-controls"><label className="aqx-model-toggle"><input type="checkbox" disabled={!!result.paper} checked={modelEnabled} onChange={event=>setModelEnabled(event.target.checked)}/><span>{result.paper?'論文の符号付きモデルは「論文条件の結果」に表示します':'読み込んだデータに参考モデルを当てはめる'}</span></label>{modelEnabled&&<div className="aqx-model-fields"><label className="field"><span>モデルに使う群</span><select value={modelGroup} onChange={event=>setModelGroup(event.target.value)}><option value="">現在の表示試料すべて</option>{[...new Set(samples.groups)].map(group=><option key={group}>{group}</option>)}</select></label><label className="field"><span>固定する遅延 / {axis.unit}</span><input type="number" min="0" step="any" value={modelDelay} onChange={event=>setModelDelay(Number(event.target.value))}/></label></div>}<p className="aqx-note">{modelEnabled?'モデル y = b + A (1 − exp(−max(0, t − t₀ − d) / τ))。bは最初の観測値、dは固定値。A ≥ 0、τ > 0の単調増加を仮定します。':'参考モデルは初期状態では計算しません。RMSは全座標の二乗平均平方根で、水分子種の量を表しません。'}</p>{model.error&&<p className="aqx-note aqx-fit-warning" role="status">{model.error}</p>}{model.fit&&<><div className="aqx-fit-metrics"><span>A <strong>{num(model.fit.amplitude,5)}</strong></span><span>τ <strong>{num(model.fit.tau)+' '+axis.unit}</strong></span><span>R² <strong>{num(model.fit.r2)}</strong></span><span>RMSE <strong>{num(model.fit.rmse)}</strong></span><span>n <strong>{model.fit.n}</strong></span></div>{model.fit.warnings.map(warning=><p key={warning} className="aqx-note aqx-fit-warning">{warning}</p>)}</>}</div>;
  return <div ref={host} className={'aqx aqx-'+presentation+(fitOverview?' aqx-fit':'')+(expanded?' aqx-expanded':'')+(result.paper?' aqx-paper':'')} style={{'--aqx-overview-height':Math.max(0,frame.height)+'px'} as CSSProperties} data-testid="aquagram-explorer" data-presentation={presentation} data-viewport-fit={fitOverview} role={expanded?'dialog':undefined} aria-modal={expanded?true:undefined} aria-label="Aquagramの時系列探索" tabIndex={-1}>
    <div className="page-heading aqx-heading"><div><div className="eyebrow">AQUAGRAM / TEMPORAL EXPLORER</div><h1>Aquagramの時系列探索</h1><p>同じ座標・同じ尺度で、測定順や時間に沿った変化を確認します。</p></div><div className="aqx-heading-actions"><div className="segmented aqx-presentation" aria-label="グラフの配置"><button aria-pressed={overview} onClick={()=>setPresentation('overview')}>一覧</button><button aria-pressed={!overview} onClick={()=>setPresentation('detail')}>詳細</button></div>{overview&&<details className="aqx-settings-disclosure"><summary>系列・時刻・モデル設定{axis.warnings.length>0?' · 確認事項あり':''}</summary><div className="aqx-settings-popover">{filters}{modelControls}{axis.warnings.map(warning=><p className="aqx-note" key={warning}>{warning}</p>)}<p className="aqx-note">時刻列・単位を明示して指定してください。系列を絞っても解析値と尺度は再計算しません。未測定の形は補間しません。</p></div></details>}<button className="button outline" onClick={()=>void fullscreen()}>{expanded||nativeFullscreen?<Minimize2 size={14}/>:<Maximize2 size={14}/>}<span>{expanded||nativeFullscreen?'全画面を終了':'全画面'}</span></button>{expanded&&<button className="icon-button" aria-label="拡大表示を閉じる" onClick={()=>setExpanded(false)}><X size={18}/></button>}</div></div>
    {!overview&&stale&&<div className="notice stale">未適用の解析設定があります。表示・保存は直前に完了した解析結果です。</div>}
    <section className="glass-panel aqx-controls">{!overview&&filters}<div className="aqx-transport"><button className="button primary" disabled={indices.length<2} onClick={()=>{if(!playing&&position===indices.length-1)select(indices[0]);setPlaying(old=>!old);}} aria-label={playing?'再生を一時停止':'時系列を再生'}>{playing?<Pause size={14}/>:<Play size={14}/>} {playing?'一時停止':'再生'}</button><button className="icon-button" aria-label="前の試料" disabled={position<=0} onClick={()=>{setPlaying(false);select(indices[position-1]);}}><ArrowLeft size={15}/></button><input type="range" min={0} max={Math.max(0,indices.length-1)} value={Math.max(0,position)} disabled={!indices.length} aria-label="表示する測定時点" aria-valuetext={selected>=0?samples.ids[selected]+'・'+num(axis.values[selected])+' '+axis.unit:'試料なし'} onChange={event=>{setPlaying(false);select(indices[Number(event.target.value)]);}}/><button className="icon-button" aria-label="次の試料" disabled={position<0||position>=indices.length-1} onClick={()=>{setPlaying(false);select(indices[position+1]);}}><ArrowRight size={15}/></button><label className="aqx-speed"><span>再生速度</span><select value={settings.speed} onChange={event=>set('speed',Number(event.target.value))}>{[1,5,10,30,60].map(value=><option key={value} value={value}>{value+' '+(axis.kind==='seconds'?'倍':'試料 / 秒')}</option>)}</select></label></div><div className="aqx-status" aria-live={playing?'off':'polite'}><strong title={selected>=0?samples.ids[selected]:''}>{selected>=0?samples.ids[selected]:'該当する試料がありません'}</strong><span>{selected>=0?samples.groups[selected]:''}</span><span title={axis.label}>{selected>=0?num(axis.values[selected])+' '+axis.unit:''}</span><span>{indices.length?position+1+' / '+indices.length+' 試料':''}</span>{stale&&<span className="aqx-stale-state">未適用設定あり</span>}{selectedAxisCount>1&&<span>同じ時刻に{selectedAxisCount}試料</span>}</div>{!overview&&<>{axis.warnings.map(warning=><p className="aqx-note" key={warning}>{warning}</p>)}<p className="aqx-note">横軸の列・単位は明示して指定してください。系列を絞っても解析値と尺度は再計算しません。再生は観測試料間を移動し、未測定の形は補間しません。</p></>}</section>
    {!indices.length?<section className="glass-panel aqx-no-data"><h2>表示できる試料がありません</h2><p>系列・時刻列・単位を確認するか、横軸を「試料の順序」に戻してください。</p></section>:<div className="aqx-grid">
      <Panel number="01" title="時間を重ねたAquagram" subtitle="横軸は左から右へ進みます。各断面の中心が、その試料の時刻です。" className="aqx-stack-panel aqx-wide">{overview?rotationTools:<div className="aqx-stack-toolbar"><div className="aqx-stack-meta"><span>{'横軸：'+axis.label+' / '+axis.unit}</span><strong>{'選択：'+num(axis.values[selected])+' '+axis.unit}<small>{samples.ids[selected]}</small></strong></div>{rotationTools}</div>}<div className={overview?'aqx-stack-overview-scroll':'aqx-stack-scroll'} tabIndex={0} role="region" aria-label="Aquagram時間軸グラフ">{stackGraph}</div>{!overview&&<p className="aqx-note">{axis.kind==='order'?'横軸は試料の順序です。実時間で表示するには時刻列と単位を指定してください。':axis.kind==='seconds'?'断面の中心間隔は実際の時間差に比例します。':'中心間隔は指定した列の数値差に比例します。'} ドラッグ・矢印で断面を回転できます。0は基準リングです。{indices.length>90?'最大91断面を表示し、数値と保存には全試料を使用します。':''}</p>}</Panel>
      <Panel number="02" title="選択時点のAquagram" subtitle="共通の対称尺度。0は中心ではなく破線のリングです。" className="aqx-radar-panel">{radarGraph}{!overview&&<div className="aqx-coordinate-readout">{active!==null?<><CoordinateLabel aq={aq} index={active}/><strong>{num(values[active],6)}</strong></>:<span>座標に触れると全図で強調します。</span>}</div>}</Panel>
      <Panel number="03" title="RMS・観測と参考モデル" subtitle="全座標の二乗平均平方根。水分子種の量ではありません。" className="aqx-rms-panel">{rmsGraph}{!overview&&modelControls}{overview&&model.error&&<span className="aqx-compact-model-note" title={model.error}>参考モデル：設定を確認</span>}</Panel>
      {overview?<><Panel number="04" title="座標ヒートマップ" subtitle="クリックで時点を選択。" className="aqx-heat-panel">{heatGraph}</Panel><Panel number="05" title="全座標の時間トレース" subtitle="選んだ座標を全図で強調。" className="aqx-trace-panel">{traceGraph}</Panel></>:<Panel number="04" title="座標ごとの時間変化" subtitle="ヒートマップをクリックして試料を選択。下の座標ボタンで強調できます。" className="aqx-wide">{heatGraph}{traceGraph}{coordinateLegend}<p className="aqx-note">ヒートマップは濃さが絶対値、青みのあるグレーが負、無彩色が正。CSVには間引き前の全値を保存します。</p></Panel>}
      {!result.paper&&<Panel number={overview?'06':'05'} title="参考モデルの変化率" className="aqx-rate-panel aqx-wide" subtitle="解析的な微分。分子形成速度ではありません。">{rateGraph}{!overview&&model.fit&&<p className="aqx-note">dy/dt = (A / τ) exp(−(t − t₀ − d) / τ)、開始前は0。単位：Aquagram座標RMS / {axis.unit}。開始点は右側微分です。</p>}</Panel>}
    </div>}
    {overview&&coordinateLegend}
    <details className="aqx-method-disclosure" open={!overview}><summary>計算方法・表示条件の保存{overview&&!fitOverview?' · この画面では縦にスクロール／全画面で拡大できます':''}</summary><section className="aqx-method glass-panel"><div><span className="panel-caption">CALCULATION / EXPORT</span><h2>解析値と、表示の条件を残す</h2></div><p>{samples.definition}<br/>{'全試料で共通の尺度 '+num(scale,6)+' を使用し、半径 = 1 + 0.58 × 値 / 尺度。各フレームの再標準化はしません。'} 表示は吸収パターンであり、分子構造を直接観察した像ではありません。</p>{overview&&<p className="aqx-note">一覧は同じ観測値・同じ選択状態のグラフを並べます。小さな画面・高さが不足する画面では、読みやすさを保って縦にスクロールします。「全画面」または「詳細」でも状態を引き継ぎます。ヒートマップは濃さが絶対値、青みが負、無彩色が正です。</p>}<div className="aqx-export-actions"><button className="button primary" onClick={saveView}><ArrowDownToLine size={14}/>図・数値・表示条件を保存</button><button className="button outline" onClick={saveState}><ArrowDownToLine size={14}/>表示設定</button><button className="button outline" onClick={()=>stateInput.current?.click()}><Upload size={14}/>表示設定を読込</button><input ref={stateInput} className="visually-hidden" type="file" accept=".json,application/json" aria-label="Aquagram表示設定JSON" onChange={event=>void readState(event.target.files?.[0])}/></div><p className="aqx-note">ZIPには全試料の解析値JSON、表示試料CSV、各図のSVG、表示設定、参考モデルの計算結果を含みます。元の測定CSVは上部の「解析を保存」から保存できます。</p></section></details>
  </div>;
}
