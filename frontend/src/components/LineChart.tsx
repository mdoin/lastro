// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Gráfico de linhas em SVG escrito à mão (sem biblioteca).
 * Segue a skill de dataviz: linhas de 2px, grade em linha fina sólida, um único eixo Y,
 * legenda sempre presente para 2+ séries (no componente pai), rótulos diretos só no fim,
 * crosshair + tooltip no hover e no teclado (setas), e tabela equivalente fornecida pelo pai.
 * Floats aqui servem só para geometria; os valores exibidos vêm das strings decimais (`raw`).
 */
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type RefObject } from "react";

export interface ChartPoint {
  x: number;
  y: number;
  /** Valor exato (string decimal) para tooltip. */
  raw: string;
}

export interface ChartSeries {
  key: string;
  label: string;
  /** Variável CSS da cor (ex.: "var(--series-1)"). */
  color: string;
  points: ChartPoint[];
  /** Rótulo curto no fim da linha. */
  endLabel?: string;
}

interface Props {
  series: ChartSeries[];
  /** Descrição acessível do gráfico inteiro. */
  ariaLabel: string;
  formatX: (x: number) => string;
  formatTick: (y: number) => string;
  formatValue: (raw: string) => string;
  /** Domínio Y compartilhado (pequenos múltiplos usam a mesma escala). */
  yMax?: number;
  yMin?: number;
  height?: number;
  /** Arredonda candidatos a rótulo do eixo X (ex.: anos inteiros). */
  snapX?: (x: number) => number;
}

const compact = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
export const compactTick = (v: number) => (v === 0 ? "0" : compact.format(v));

function niceStep(range: number, count: number): number {
  if (!(range > 0)) return 1;
  const raw = range / count;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const n = raw / pow;
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return nice * pow;
}

export function niceDomain(min: number, max: number, count = 4): { lo: number; hi: number; ticks: number[] } {
  const lo0 = Math.min(0, min);
  const hi0 = max > lo0 ? max : lo0 + 1;
  const step = niceStep(hi0 - lo0, count);
  const lo = Math.floor(lo0 / step) * step;
  const hi = Math.ceil(hi0 / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toPrecision(12)));
  return { lo, hi, ticks };
}

function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(320);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect.width;
      if (cw && Math.abs(cw - w) > 0.5) setW(cw);
    });
    ro.observe(el);
    setW(el.clientWidth || 320);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return [ref, w];
}

export function LineChart({
  series,
  ariaLabel,
  formatX,
  formatTick,
  formatValue,
  yMax,
  yMin,
  height = 200,
  snapX,
}: Props) {
  const [wrapRef, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const descId = useId();

  const M = { top: 22, right: 8, bottom: 26, left: 44 };
  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = Math.max(40, height - M.top - M.bottom);

  const xs = useMemo(() => series[0]?.points.map((p) => p.x) ?? [], [series]);
  const xMin = xs.length ? Math.min(...xs) : 0;
  const xMax = xs.length ? Math.max(...xs) : 1;

  const { lo, hi, ticks } = useMemo(() => {
    const ys = series.flatMap((s) => s.points.map((p) => p.y)).filter(Number.isFinite);
    const dataMax = yMax ?? (ys.length ? Math.max(...ys) : 1);
    const dataMin = yMin ?? (ys.length ? Math.min(...ys) : 0);
    return niceDomain(dataMin, dataMax);
  }, [series, yMax, yMin]);

  const sx = (x: number) => M.left + (xMax === xMin ? plotW / 2 : ((x - xMin) / (xMax - xMin)) * plotW);
  const sy = (y: number) => M.top + plotH - ((y - lo) / (hi - lo || 1)) * plotH;

  // Rótulos do eixo X: primeiro alinhado à esquerda, último à direita, demais centralizados.
  // Mantém só os que não colidem (largura estimada pelo texto).
  const xTicks = useMemo(() => {
    if (xs.length <= 1) return xs;
    const width = (x: number) => formatX(x).length * 6.4 + 4;
    const cand: number[] = [];
    const n = Math.max(2, Math.min(6, Math.floor(plotW / 60)));
    for (let i = 0; i < n; i++) {
      let v = xs[Math.round((i / (n - 1)) * (xs.length - 1))];
      if (v !== undefined && snapX && i > 0 && i < n - 1) {
        const snapped = snapX(v);
        if (xs.includes(snapped)) v = snapped;
      }
      if (v !== undefined && !cand.includes(v)) cand.push(v);
    }
    const first = cand[0]!;
    const last = cand[cand.length - 1]!;
    const lastLeft = sx(last) - width(last);
    const kept = [first];
    let right = sx(first) + width(first);
    for (const v of cand.slice(1, -1)) {
      const half = width(v) / 2;
      if (sx(v) - half >= right + 10 && sx(v) + half <= lastLeft - 10) {
        kept.push(v);
        right = sx(v) + half;
      }
    }
    if (lastLeft >= right + 10) kept.push(last);
    return kept;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [xs, plotW, formatX, snapX]);

  function indexFromClientX(clientX: number, target: Element) {
    const rect = target.getBoundingClientRect();
    const px = ((clientX - rect.left) / rect.width) * width;
    let best = 0;
    let bestD = Infinity;
    xs.forEach((x, i) => {
      const d = Math.abs(sx(x) - px);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    return best;
  }

  function onPointer(e: PointerEvent<SVGRectElement>) {
    const svg = e.currentTarget.ownerSVGElement;
    if (svg) setHover(indexFromClientX(e.clientX, svg));
  }

  function onKey(e: KeyboardEvent<SVGSVGElement>) {
    if (!xs.length) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const step = e.shiftKey ? Math.max(1, Math.round(xs.length / 10)) : 1;
      setHover((h) => {
        const cur = h ?? (e.key === "ArrowRight" ? -1 : xs.length);
        const next = e.key === "ArrowRight" ? cur + step : cur - step;
        return Math.max(0, Math.min(xs.length - 1, next));
      });
    } else if (e.key === "Home") {
      setHover(0);
    } else if (e.key === "End") {
      setHover(xs.length - 1);
    } else if (e.key === "Escape") {
      setHover(null);
    }
  }

  // Rótulos diretos no fim das linhas; se colidirem, ficam só legenda + tooltip.
  const endLabels = useMemo(() => {
    const items = series
      .map((s) => {
        const last = s.points[s.points.length - 1];
        return last && s.endLabel ? { key: s.key, text: s.endLabel, y: sy(last.y), x: sx(last.x) } : null;
      })
      .filter((v): v is { key: string; text: string; y: number; x: number } => v !== null)
      .sort((a, b) => a.y - b.y);
    // Acima do ponto final; se não couber, abaixo — sempre dentro da área do gráfico,
    // para não colidir com os rótulos do eixo X nem com outro rótulo.
    const placed: { key: string; text: string; x: number; y: number }[] = [];
    const fits = (y: number) =>
      y >= M.top - 4 && y <= M.top + plotH - 3 && !placed.some((p) => Math.abs(p.y - y) < 14);
    items.forEach((it) => {
      const y = fits(it.y - 9) ? it.y - 9 : fits(it.y + 17) ? it.y + 17 : null;
      if (y !== null) placed.push({ ...it, y });
    });
    return placed;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, width, lo, hi]);

  const hx = hover !== null ? xs[hover] : undefined;
  const ttRef = useRef<HTMLDivElement>(null);
  const [ttW, setTtW] = useState(200);
  useLayoutEffect(() => {
    const w = ttRef.current?.offsetWidth;
    if (w && Math.abs(w - ttW) > 1) setTtW(w);
  });
  // Tooltip ao lado do crosshair, sempre dentro da largura do gráfico.
  const cx = hx !== undefined ? sx(hx) : 0;
  const preferRight = cx + 12 + ttW <= width;
  const rawLeft = preferRight ? cx + 12 : cx - 12 - ttW;
  const tooltipLeft = Math.max(0, Math.min(rawLeft, width - ttW));

  return (
    <div className="chart" ref={wrapRef}>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
        aria-describedby={descId}
        tabIndex={0}
        onKeyDown={onKey}
        onBlur={() => setHover(null)}
      >
        <desc id={descId}>Use as setas para percorrer os pontos. Os valores também estão na tabela.</desc>
        {ticks.map((t) => (
          <g key={t}>
            <line className={t === 0 ? "baseline" : "gridline"} x1={M.left} x2={M.left + plotW} y1={sy(t)} y2={sy(t)} />
            <text className="tick" x={M.left - 8} y={sy(t)} dy="0.32em" textAnchor="end">
              {formatTick(t)}
            </text>
          </g>
        ))}
        {xTicks.map((x, i) => (
          <text
            key={x}
            className="tick"
            x={sx(x)}
            y={M.top + plotH + 18}
            textAnchor={xTicks.length > 1 && i === 0 ? "start" : i === xTicks.length - 1 && xTicks.length > 1 ? "end" : "middle"}
          >
            {formatX(x)}
          </text>
        ))}
        {series.map((s) => {
          const pts = s.points.filter((p) => Number.isFinite(p.y));
          if (!pts.length) return null;
          const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join("");
          const last = pts[pts.length - 1]!;
          return (
            <g key={s.key}>
              <path className="series-line" d={d} stroke={s.color} />
              <circle className="end-dot" cx={sx(last.x)} cy={sy(last.y)} r={4} fill={s.color} />
            </g>
          );
        })}
        {endLabels.map((l) => (
          <text key={l.key} className="tick" x={l.x} y={l.y} textAnchor="end">
            {l.text}
          </text>
        ))}
        {hx !== undefined && hover !== null && (
          <g aria-hidden="true">
            <line className="crosshair" x1={sx(hx)} x2={sx(hx)} y1={M.top} y2={M.top + plotH} />
            {series.map((s) => {
              const p = s.points[hover];
              return p && Number.isFinite(p.y) ? (
                <circle key={s.key} className="end-dot" cx={sx(p.x)} cy={sy(p.y)} r={4.5} fill={s.color} />
              ) : null;
            })}
          </g>
        )}
        <rect
          x={M.left}
          y={0}
          width={plotW}
          height={height}
          fill="transparent"
          onPointerMove={onPointer}
          onPointerDown={onPointer}
          onPointerLeave={() => setHover(null)}
        />
      </svg>
      {hx !== undefined && hover !== null && (
        <div
          ref={ttRef}
          className="tooltip"
          style={{ top: 4, left: tooltipLeft }}
          role="status"
          aria-live="polite"
        >
          <div className="tt-head">{formatX(hx)}</div>
          {series.map((s) => {
            const p = s.points[hover];
            return (
              <div className="tt-row" key={s.key}>
                <span className="tt-key" style={{ background: s.color }} />
                <span>
                  <span className="tt-value">{p ? formatValue(p.raw) : "—"}</span> <span>{s.label}</span>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <ul className="legend" aria-label="Legenda">
      {items.map((i) => (
        <li key={i.label}>
          <span className="key-line" style={{ background: i.color }} aria-hidden="true" />
          {i.label}
        </li>
      ))}
    </ul>
  );
}
