import { useEffect, useRef, useState } from 'react';
import Plotly from 'plotly.js-strict-dist-min';
import type { Config } from 'plotly.js';

export interface Figure { data: any[]; layout: Record<string, any> }
interface Props { figure: Figure; label: string; onSelect?: (id: string) => void; className?: string }

const chartConfig: Partial<Config> = { responsive: true, displaylogo: false, scrollZoom: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'], toImageButtonOptions: { format: 'png', filename: 'aquaphotomics', scale: 2 } };

/** The same figure object is used on screen and when exporting the analysis. */
export async function figurePng(figure: Figure): Promise<string> {
  const element = document.createElement('div');
  Object.assign(element.style, { position: 'fixed', left: '-10000px', top: '0', width: '1440px', height: '900px', pointerEvents: 'none' });
  document.body.appendChild(element);
  try {
    await Plotly.newPlot(element, structuredClone(figure.data), { ...structuredClone(figure.layout), width: 1440, height: 900, autosize: false }, chartConfig);
    return await Plotly.toImage(element, { format: 'png', width: 1440, height: 900, scale: 1.5 });
  } finally { Plotly.purge(element); element.remove(); }
}

export default function Plot({ figure, label, onSelect, className = '' }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const select = useRef(onSelect);
  select.current = onSelect;
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const host = container.current;
    if (!host) return;
    const element = document.createElement('div');
    element.className = 'plot-canvas';
    host.appendChild(element);
    let disposed = false;
    let observer: ResizeObserver | undefined;
    setError(''); setLoading(true);
    void (async () => {
      try {
        const graph = await Plotly.newPlot(element, structuredClone(figure.data), { ...structuredClone(figure.layout), autosize: true }, chartConfig);
        if (disposed) return;
        graph.on('plotly_click', (event: any) => {
          const id = event.points?.[0]?.customdata;
          if (typeof id === 'string') select.current?.(id);
        });
        observer = new ResizeObserver(() => { if (!disposed && host.clientWidth) void Promise.resolve(Plotly.Plots.resize(element)).catch(() => {}); });
        observer.observe(host);
        setLoading(false);
      } catch (cause) { if (!disposed) { setError(cause instanceof Error ? cause.message : String(cause)); setLoading(false); } }
    })().finally(() => { if (disposed) { Plotly.purge(element); element.remove(); } });
    return () => { disposed = true; observer?.disconnect(); Plotly.purge(element); element.remove(); };
  }, [figure]);
  return <div className={`plot-host ${className}`} role="group" aria-label={label}>
    {loading && <div className="plot-loading" role="status"><span className="spinner" /> グラフを描画しています</div>}
    {error && <div className="notice error" role="alert">グラフを表示できませんでした。{error}</div>}
    <div className="plot-target" ref={container} />
  </div>;
}
