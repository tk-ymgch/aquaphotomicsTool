/** Optional empirical curve. It does not identify molecular states or kinetics. */
export interface FormationPoint {time:number;value:number}
export interface FormationFit {
  baseline:number;amplitude:number;tau:number;delay:number;timeOrigin:number;
  r2:number;rmse:number;n:number;inputCount:number;
  curve:{time:number;value:number;rate:number}[];warnings:string[];
  definition:string;
}

export function fitFormationModel(points:FormationPoint[],options:{delay?:number;baseline?:number}={}):FormationFit {
  if(!Array.isArray(points))throw new Error('モデルに使う観測値を確認してください。');
  const finite=points.filter(p=>Number.isFinite(p.time)&&Number.isFinite(p.value)).sort((a,b)=>a.time-b.time);
  const grouped=new Map<number,{sum:number;n:number}>();
  for(const p of finite){const old=grouped.get(p.time)??{sum:0,n:0};old.sum+=p.value;old.n++;grouped.set(p.time,old);}
  const data=Array.from(grouped,([time,g])=>({time,value:g.sum/g.n}));
  if(data.length<6)throw new Error('参考モデルには異なる時刻または試料順の観測値が6点以上必要です。');
  if(data.length>20_000)throw new Error('参考モデルは異なる時刻が20,000点以内の区間に絞ってください。');
  const timeOrigin=data[0].time,span=data.at(-1)!.time-timeOrigin;
  const delay=options.delay??0,baseline=options.baseline??data[0].value;
  if(!Number.isFinite(delay)||delay<0||delay>=span||!Number.isFinite(baseline))throw new Error('モデルの遅延・初期値を確認してください。');
  const elapsed=data.map(p=>p.time-timeOrigin),ys=data.map(p=>p.value);
  const mean=ys.reduce((a,b)=>a+b,0)/ys.length;
  const total=ys.reduce((a,y)=>a+(y-mean)**2,0);
  if(total<=Number.EPSILON*Math.max(1,ys.reduce((a,y)=>a+y*y,0)))throw new Error('値の変動が小さく、参考モデルの時定数を推定できません。');
  const steps=elapsed.slice(1).map((t,i)=>t-elapsed[i]);
  const minStep=steps.reduce((a,b)=>Math.min(a,b),Infinity),lo=Math.log(Math.max(minStep*.001,span*.000001,1e-12)),hi=Math.log(span*1000);
  function evaluate(logTau:number){
    const tau=Math.exp(logTau),basis=elapsed.map(t=>t<=delay?0:-Math.expm1(-(t-delay)/tau));
    const denominator=basis.reduce((a,s)=>a+s*s,0);
    const amplitude=denominator>0?Math.max(0,basis.reduce((a,s,i)=>a+s*(ys[i]-baseline),0)/denominator):0;
    const sse=basis.reduce((a,s,i)=>a+(ys[i]-(baseline+amplitude*s))**2,0);
    return {tau,amplitude,sse};
  }
  // Search the full log-scale range before refining a local bracket. A single
  // start can hide slow/fast solutions and would not diagnose boundary fits.
  const divisions=160;let bestIndex=0,best=evaluate(lo);
  for(let i=1;i<=divisions;i++){const candidate=evaluate(lo+(hi-lo)*i/divisions);if(candidate.sse<best.sse){best=candidate;bestIndex=i;}}
  let a=lo+(hi-lo)*Math.max(0,bestIndex-1)/divisions,b=lo+(hi-lo)*Math.min(divisions,bestIndex+1)/divisions;
  for(let i=0;i<70;i++){const c=a+(b-a)/3,d=b-(b-a)/3;if(evaluate(c).sse<=evaluate(d).sse)b=d;else a=c;}
  const refined=evaluate((a+b)/2);if(refined.sse<best.sse)best=refined;
  if(best.amplitude<=1e-12*ys.reduce((a,y)=>Math.max(a,Math.abs(y)),1))throw new Error('単調増加モデルに対応する変化を推定できません。観測値の表示を使用してください。');
  const r2=1-best.sse/total,warnings:string[]=[];
  if(finite.length!==points.length)warnings.push('非有限値を除外しました。');
  if(data.length!==finite.length)warnings.push('同一時刻の値を平均し、異なる時刻を等しい重みで当てはめました。');
  if(r2<.5)warnings.push('この単調増加モデルへの適合は低い値です。別の過程や観測変動を表している可能性があります。');
  if(best.tau>span*100||best.tau<minStep*.01)warnings.push('時定数が観測間隔または観測期間の外側にあり、識別が弱い推定です。');
  warnings.push('初期値と遅延は固定した記述的な曲線です。分子の形成過程・反応速度・因果関係を推定するものではありません。');
  const curve=Array.from({length:241},(_,i)=>{
    const t=span*i/240,x=t-delay;
    return {time:timeOrigin+t,value:x<=0?baseline:baseline+best.amplitude*(-Math.expm1(-x/best.tau)),
      rate:x<0?0:best.amplitude/best.tau*Math.exp(-x/best.tau)};
  });
  return {baseline,amplitude:best.amplitude,tau:best.tau,delay,timeOrigin,r2,rmse:Math.sqrt(best.sse/data.length),n:data.length,inputCount:points.length,
    curve,warnings,definition:'y(t)=b+A(1−exp(−max(0,t−t0−d)/τ)), A≥0, τ>0; b and d fixed; least squares on equal-weight unique-time means. Rate is the analytic derivative, not an observed derivative.'};
}
