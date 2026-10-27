/**
 * Valor que "rola" até o número final, dígito a dígito (como o saldo do app Plasma).
 * Recebe o texto JÁ formatado (ex.: "R$ 2.200,00"): nada aqui converte dinheiro.
 * Leitores de tela recebem o texto inteiro; a animação é só visual e respeita movimento reduzido.
 */
import { useEffect, useState, type CSSProperties } from "react";

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function RollingNumber({ value, className = "", style }: { value: string; className?: string; style?: CSSProperties }) {
  const [armed, setArmed] = useState(prefersReducedMotion);
  const [rolling, setRolling] = useState(false);

  // Primeiro quadro com todos os dígitos em 0; no seguinte, rola até o valor.
  useEffect(() => {
    if (armed) return;
    let inner = 0;
    const outer = window.requestAnimationFrame(() => {
      inner = window.requestAnimationFrame(() => setArmed(true));
    });
    return () => {
      window.cancelAnimationFrame(outer);
      window.cancelAnimationFrame(inner);
    };
  }, [armed]);

  useEffect(() => {
    if (!armed || prefersReducedMotion()) return;
    setRolling(true);
    const t = window.setTimeout(() => setRolling(false), 1700);
    return () => window.clearTimeout(t);
  }, [armed, value]);

  const chars = [...value];
  const digitCount = chars.filter((ch) => ch >= "0" && ch <= "9").length;
  let seen = 0;

  return (
    <span className={className} style={style}>
      <span className="visually-hidden">{value}</span>
      <span className={`roll ${rolling ? "rolling" : ""}`} data-armed={armed ? "true" : "false"} aria-hidden="true">
        {chars.map((ch, i) => {
          // Chave pela posição a partir da direita: os centavos continuam na mesma coluna quando o valor cresce.
          const key = chars.length - i;
          if (ch < "0" || ch > "9") {
            return (
              <span key={`c${key}`} className="roll-char">
                {ch}
              </span>
            );
          }
          const order = seen++;
          const delay = Math.round((order / Math.max(1, digitCount - 1)) * 260);
          return (
            <span key={`d${key}`} className="roll-col">
              <span className="roll-sizer">{ch}</span>
              <span
                className="roll-strip"
                style={{ ["--d" as string]: armed ? Number(ch) : 0, ["--delay" as string]: `${delay}ms` }}
              >
                {DIGITS.map((n) => (
                  <span key={n}>{n}</span>
                ))}
              </span>
            </span>
          );
        })}
      </span>
    </span>
  );
}
