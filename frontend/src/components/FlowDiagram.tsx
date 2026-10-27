/**
 * Para onde vai a renda do mês: um "roteador" (inspirado no Model Router) que parte da renda
 * e se divide entre os destinos, com partículas correndo por cada caminho.
 * O desenho é decorativo (aria-hidden): os números ficam na lista ao lado, em texto.
 * Espessuras usam float (geometria); valores e percentuais exibidos chegam prontos, em texto.
 */
import { useEffect, useRef, useState, type RefObject } from "react";

export interface FlowItem {
  key: string;
  label: string;
  /** Valor exibido, já formatado. */
  valueText: string;
  /** Participação exibida, já formatada (ex.: "52,4% da renda"). */
  shareText: string;
  /** Participação para a geometria (0–1+). */
  weight: number;
  /** Cor CSS (variável de tema). */
  color: string;
}

const ROW = 56;

function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduce(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduce;
}

function useWidth(): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect.width;
      if (cw) setW(Math.round(cw));
    });
    ro.observe(el);
    setW(Math.round(el.clientWidth));
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export function FlowDiagram({ source, items, caption }: { source: string; items: FlowItem[]; caption: string }) {
  const [ref, width] = useWidth();
  const reduce = useReducedMotion();
  const H = Math.max(1, items.length) * ROW;
  const W = Math.max(60, width);
  const yc = H / 2;
  const x0 = 6;
  const x1 = W - 6;
  const xa = x0 + (x1 - x0) * 0.16;
  const xb = x0 + (x1 - x0) * 0.4;
  const xc = x0 + (x1 - x0) * 0.66;

  return (
    <figure className="flow" style={{ margin: 0 }}>
      <figcaption className="visually-hidden">{caption}</figcaption>
      <div className="flow-wrap">
        <div ref={ref} style={{ minWidth: 0, position: "relative" }}>
          {width > 0 && (
            <svg className="flow-svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false">
              {W >= 170 && (
                <text className="flow-label" x={x0} y={yc - 14}>
                  {source.toUpperCase()}
                </text>
              )}
              {items.map((it, i) => {
                const yi = i * ROW + ROW / 2 - 7;
                const d = `M${x0},${yc} L${xa},${yc} C${xb},${yc} ${xb},${yi} ${xc},${yi} L${x1},${yi}`;
                const w = Number.isFinite(it.weight) ? Math.max(0, it.weight) : 0;
                const halo = 3 + Math.min(1, w) * 15;
                const dots = w > 0 ? Math.min(6, Math.max(1, Math.round(w * 9))) : 0;
                const dur = 3.4;
                return (
                  <g key={it.key}>
                    <path className="flow-track" d={d} stroke={it.color} strokeWidth={halo} />
                    <path className="flow-line" d={d} stroke={it.color} />
                    {!reduce &&
                      Array.from({ length: dots }, (_, k) => (
                        <circle key={k} r={2.6} fill={it.color}>
                          <animateMotion
                            dur={`${dur}s`}
                            repeatCount="indefinite"
                            begin={`${(-(k * dur) / dots - i * 0.37).toFixed(2)}s`}
                            path={d}
                            keyPoints="0;1"
                            keyTimes="0;1"
                            calcMode="spline"
                            keySplines="0.45 0 0.55 1"
                          />
                        </circle>
                      ))}
                    <circle className="flow-end" cx={x1} cy={yi} r={4.5} fill={it.color} />
                  </g>
                );
              })}
              <circle className="flow-src" cx={x0} cy={yc} r={4.5} />
            </svg>
          )}
        </div>
        <ul className="flow-legend" style={{ ["--row" as string]: `${ROW}px` }}>
          {items.map((it) => (
            <li key={it.key} style={{ height: ROW }}>
              <span className="fl-name">
                <span className="fl-dot" style={{ ["--c" as string]: it.color }} aria-hidden="true" />
                {it.label}
              </span>
              <span className="fl-value">{it.valueText}</span>
              <span className="fl-share">{it.shareText}</span>
            </li>
          ))}
        </ul>
      </div>
    </figure>
  );
}
