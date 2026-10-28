// SPDX-License-Identifier: AGPL-3.0-or-later
import { memo, type CSSProperties } from "react";
import { BrandMark } from "./Icon";
import { EYE_CHARS, GRID, MASCOTS, runs } from "./mascots";
import "../styles/mascots.css";

export type AvatarState = "idle" | "thinking" | "speaking";

const RUNS = Object.fromEntries(Object.entries(MASCOTS).map(([id, m]) => [id, runs(m.rows)]));
// Piscadas fora de sincronia: cada agente com seu atraso (nunca todos ao mesmo tempo).
const BLINK_DELAY: Record<string, number> = {
  mentor: 0.4, planejador: 2.1, analista: 3.7, economista: 1.3, riscos: 4.6, comportamental: 2.9, cripto: 3.3, auditor: 5.2,
};

/**
 * Avatar de agente: o mascote em pixel art (SVG nítido, fundo transparente) ou, para ids desconhecidos, as iniciais.
 * `decorative` quando o nome do agente já está escrito ao lado (o leitor de tela não repete).
 */
export const AgentAvatar = memo(function AgentAvatar({
  id,
  size = 32,
  state = "idle",
  decorative = false,
  className = "",
  label,
}: {
  id: string;
  size?: number;
  state?: AvatarState;
  decorative?: boolean;
  className?: string;
  /** Nome a anunciar quando o id não é de um mascote (ex.: nome vindo da API). */
  label?: string;
}) {
  const mascot = MASCOTS[id];
  const a11y = decorative ? { "aria-hidden": true as const } : { role: "img", "aria-label": mascot?.alt ?? label ?? id };
  const style = { width: size, height: size, "--blink-delay": `${BLINK_DELAY[id] ?? 0}s` } as CSSProperties;
  if (id === "lastro") {
    return (
      <span className={`agent-avatar agent-avatar-brand ${className}`} style={style} {...(decorative ? { "aria-hidden": true } : { role: "img", "aria-label": "Lastro" })}>
        <BrandMark className="agent-avatar-mark" />
      </span>
    );
  }
  if (!mascot) {
    const initials = (label ?? id).split(/[\s-]+/).map((p) => p[0] ?? "").join("").slice(0, 2).toUpperCase();
    return (
      <span className={`agent-avatar agent-avatar-fallback ${className}`} style={style} {...a11y}>
        {initials}
      </span>
    );
  }
  const body = RUNS[id]!.filter((r) => !EYE_CHARS.has(r.ch));
  const eyes = RUNS[id]!.filter((r) => EYE_CHARS.has(r.ch));
  const fill = (ch: string) => (ch === "o" ? `var(--mascot-outline, ${mascot.palette.o})` : mascot.palette[ch] ?? "#ff00ff");
  return (
    <span className={`agent-avatar is-${state} ${size < 24 ? "is-tiny" : ""} ${className}`} style={style} {...a11y}>
      <svg viewBox={`0 0 ${GRID} ${GRID}`} width={size} height={size} shapeRendering="crispEdges" focusable="false" aria-hidden="true">
        {body.map((r) => (
          <rect key={`${r.x}-${r.y}`} x={r.x} y={r.y} width={r.w} height={1} fill={fill(r.ch)} />
        ))}
        <g className="agent-avatar-eyes">
          {eyes.map((r) => (
            <rect key={`${r.x}-${r.y}`} x={r.x} y={r.y} width={r.w} height={1} fill={fill(r.ch)} />
          ))}
        </g>
      </svg>
    </span>
  );
});
