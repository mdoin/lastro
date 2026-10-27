// SPDX-License-Identifier: AGPL-3.0-or-later
/** Ícones de traço fino, desenhados à mão (sem biblioteca, sem emoji). */
import type { SVGProps } from "react";

const PATHS = {
  home: "M4 11.5 12 5l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z",
  wallet: "M4 7.5A2.5 2.5 0 0 1 6.5 5H18v3M4 7.5V17a2 2 0 0 0 2 2h13a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1H6.5A2.5 2.5 0 0 1 4 7.5ZM16 13.5h.01",
  trend: "M4 19h16M5 15l4.5-4.5 3.5 3L19 7m0 0h-4m4 0v4",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-4a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0-4a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z",
  chat: "M5 18.5V6a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H8.5zM9 9.5h6M9 12.5h4",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13v4.5l3 2",
  book: "M5 4.5h9.5A2.5 2.5 0 0 1 17 7v12.5H7.5A2.5 2.5 0 0 1 5 17zM5 17a2.5 2.5 0 0 1 2.5-2.5H17M9 8.5h4",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7.5 7.5 0 0 0-2-1.2L14.6 3h-4l-.4 2.6a7.5 7.5 0 0 0-2 1.2l-2.3-.9-2 3.4 2 1.5a7.4 7.4 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-.9a7.5 7.5 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7.5 7.5 0 0 0 2-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2Z",
  more: "M6 12h.01M12 12h.01M18 12h.01",
  check: "m5 12.5 4.5 4.5L19 7.5",
  alert: "M12 4 21 19.5H3zM12 10v4M12 17h.01",
  x: "M6 6l12 12M18 6 6 18",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-10v5m0-8h.01",
  copy: "M9 9h10v11H9zM5 15V4h10",
  plus: "M12 5v14M5 12h14",
  trash: "M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13",
  edit: "M5 19h4l10-10-4-4L5 15zM13.5 6.5l4 4",
  play: "M8 5.5v13l10-6.5z",
  stop: "M7 7h10v10H7z",
  pause: "M9 6v12M15 6v12",
  refresh: "M19 8a7.5 7.5 0 1 0 .5 6M19 4v4h-4",
  logout: "M14 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 16l-4-4 4-4M6 12h9",
  download: "M12 4v11m0 0-4-4m4 4 4-4M5 20h14",
  panel: "M4 5h7v6H4zM13 5h7v6h-7zM4 13h16v6H4z",
  shield: "M12 3.5 19 6v5.5c0 4.3-3 7.7-7 9-4-1.3-7-4.7-7-9V6z",
  shieldCheck: "M12 3.5 19 6v5.5c0 4.3-3 7.7-7 9-4-1.3-7-4.7-7-9V6zM9 12l2.2 2.2L15.5 10",
  inbox: "M4 13.5 6.5 5h11l2.5 8.5V19H4zM4 13.5h5a3 3 0 0 0 6 0h5",
  arrow: "M5 12h14m0 0-5-5m5 5-5 5",
  arrowUp: "M12 19V5m0 0-6 6m6-6 6 6",
  arrowUpRight: "M7 17 17 7M9 7h8v8",
  chevronRight: "m9.5 6 6 6-6 6",
  chevronDown: "m6 9.5 6 6 6-6",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z",
  pulse: "M3 12h4l2.5-6 5 12 2.5-6h4",
  bars: "M5 19V11M10 19V6M15 19v-5M20 19V9",
  card: "M3.5 6.5h17v11h-17zM3.5 10.5h17M7 14.5h4",
  cap: "M2.5 9.5 12 5l9.5 4.5L12 14zM6.5 11.6V16c1.6 1.5 3.6 2.2 5.5 2.2s3.9-.7 5.5-2.2v-4.4M21.5 9.5v5",
  search: "M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13Zm4.8-1.7L20 20",
  layers: "M12 4 3 8.5l9 4.5 9-4.5zM3 12.5l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5",
  sliders: "M5 7h8m4 0h2M5 17h2m4 0h8M15 4.5v5M9 14.5v5",
  coins: "M9 11a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm5.6-2.6a5 5 0 1 1-6.2 6.2M9 4.5v3",
  flow: "M4 12h4c3 0 3-6 6-6h6M8 12c3 0 3 6 6 6h6M4 12h16",
  calendar: "M5 6h14v14H5zM5 10h14M9 3.5v4M15 3.5v4",
  ban: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM5.7 5.7l12.6 12.6",
  spark: "M12 4v3.5M12 16.5V20M4 12h3.5M16.5 12H20M6.5 6.5l2.3 2.3M15.2 15.2l2.3 2.3M6.5 17.5l2.3-2.3M15.2 8.8l2.3-2.3",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-9-9h18M12 3c2.5 2.4 3.7 5.4 3.7 9s-1.2 6.6-3.7 9c-2.5-2.4-3.7-5.4-3.7-9S9.5 5.4 12 3Z",
  sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0-13v1.5m0 15V21M3 12h1.5m15 0H21M5.6 5.6l1.1 1.1m10.6 10.6 1.1 1.1M5.6 18.4l1.1-1.1M17.3 6.7l1.1-1.1",
  moon: "M19.5 14.6A7.8 7.8 0 0 1 9.4 4.5 7.8 7.8 0 1 0 19.5 14.6Z",
  monitor: "M4 5h16v11H4zM9 20h6M12 16v4",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, ...rest }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

/*
 * Símbolo do Lastro: o "Bloco L". Um L maciço com as faces superiores em ouro —
 * a base que sustenta (lastro) e o ouro que dá valor (lastro-ouro). Grade de 64.
 * Fonte da geometria: docs/brand (mesmos pontos dos arquivos SVG do kit).
 */
const BM_FRONT = "M14.25 18.5 L24.75 18.5 L24.75 39.5 L45.75 39.5 L45.75 50 L14.25 50 Z";
const BM_TOPS =
  "M14.25 18.5 L24.75 18.5 L28.35 15.2 L17.85 15.2 Z M24.75 39.5 L45.75 39.5 L49.35 36.2 L28.35 36.2 Z";
const BM_SIDES =
  "M24.75 18.5 L28.35 15.2 L28.35 36.2 L24.75 39.5 Z M45.75 39.5 L49.35 36.2 L49.35 46.7 L45.75 50 Z";

/** `tone="auto"` segue o tema (tinta no claro, marfim no escuro); "ivory" para fundos sempre escuros. */
export function BrandMark({ className, tone = "auto" }: { className?: string; tone?: "auto" | "ivory" | "ink" }) {
  const front = tone === "ivory" ? "#F3EFE6" : tone === "ink" ? "#121211" : undefined;
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true" focusable="false">
      <path d={BM_FRONT} className="bm-front" style={front ? { fill: front } : undefined} />
      <path d={BM_TOPS} className="bm-top" style={tone === "ivory" ? { fill: "#E3BD68" } : undefined} />
      <path d={BM_SIDES} className="bm-side" style={tone === "ivory" ? { fill: "#B4852A" } : undefined} />
    </svg>
  );
}
