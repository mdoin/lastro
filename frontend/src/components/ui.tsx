// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { parseBRL, parsePercent } from "../lib/money";
import type { Tone } from "../lib/labels";
import { BrandMark, Icon, type IconName } from "./Icon";

export function PageHeader({
  eyebrow,
  title,
  lede,
  actions,
}: {
  eyebrow?: string;
  title: string;
  lede?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {lede && <p className="lede">{lede}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

/**
 * Cartão. Com título, rótulo, complemento ou rodapé vira o painel aninhado das referências:
 * casca cinza (cabeçalho e rodapé) envolvendo uma folha branca com o conteúdo.
 * Sem nada disso, é só a folha.
 */
export function Card({
  title,
  eyebrow,
  aside,
  footer,
  children,
  className = "",
  as: Tag = "section",
  labelledBy,
}: {
  title?: ReactNode;
  eyebrow?: string;
  aside?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
  labelledBy?: string;
}) {
  const autoId = useId();
  const headingId = labelledBy ?? (title ? autoId : undefined);
  if (!title && !eyebrow && !aside && !footer) {
    return (
      <Tag className={`card ${className}`} aria-labelledby={headingId}>
        {children}
      </Tag>
    );
  }
  return (
    <Tag className={`panel ${className}`} aria-labelledby={headingId}>
      <div className="panel-head">
        <div>
          {eyebrow && <div className="eyebrow">{eyebrow}</div>}
          {title && <h2 id={headingId}>{title}</h2>}
        </div>
        {aside}
      </div>
      <div className="panel-body">{children}</div>
      {footer && <div className="panel-foot">{footer}</div>}
    </Tag>
  );
}

const TONE_ICON: Partial<Record<Tone, IconName>> = {
  good: "check",
  warning: "alert",
  serious: "alert",
  critical: "x",
  gold: "clock",
};

export function Badge({ tone = "neutral", children, icon }: { tone?: Tone; children: ReactNode; icon?: IconName }) {
  const name = icon ?? TONE_ICON[tone];
  return (
    <span className={`badge ${tone}`}>
      {name && <Icon name={name} />}
      {children}
    </span>
  );
}

/** Etiqueta em fonte mono: contagens, códigos, metadados. */
export function Tag({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`tag ${className}`}>{children}</span>;
}

export function Notice({
  tone = "info",
  children,
  title,
}: {
  tone?: "info" | "warning" | "error" | "success";
  children: ReactNode;
  title?: string;
}) {
  const icon: IconName = tone === "error" ? "x" : tone === "warning" ? "alert" : tone === "success" ? "check" : "info";
  return (
    <div className={`notice ${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon name={icon} />
      <div>
        {title && <strong>{title} </strong>}
        {children}
      </div>
    </div>
  );
}

export function Loading({ label = "Carregando…" }: { label?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="typing" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      {label}
    </div>
  );
}

export function ErrorNotice({ error, onRetry }: { error: { detail: string } | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <Notice tone="error">
      {error.detail}{" "}
      {onRetry && (
        <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}>
          Tentar de novo
        </button>
      )}
    </Notice>
  );
}

export function EmptyState({
  title,
  children,
  action,
  icon,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  /** Ícone no selo; sem ícone, mostra o símbolo do Lastro. */
  icon?: IconName;
}) {
  return (
    <div className="empty">
      <span className="empty-mark" aria-hidden="true">
        {icon ? <Icon name={icon} style={{ width: 24, height: 24 }} /> : <BrandMark />}
      </span>
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function FirstSnapshotCTA({ what = "esta tela" }: { what?: string }) {
  return (
    <Card className="flat">
      <EmptyState
        title="Comece pelo retrato do mês"
        action={
          <Link className="btn btn-primary" to="/vida-financeira">
            <Icon name="plus" />
            Criar primeiro retrato
          </Link>
        }
      >
        Para preencher {what}, o Lastro precisa de um retrato da sua vida financeira: renda, despesas, reserva e
        dívidas. Leva poucos minutos e nada é enviado a bancos.
      </EmptyState>
    </Card>
  );
}

/** Aviso legal vindo da API (nunca inventado). */
export function Disclaimer({ text, extra }: { text: string | null | undefined; extra?: ReactNode }) {
  if (!text && !extra) return null;
  return (
    <aside className="disclaimer" aria-label="Aviso importante">
      <Icon name="shield" />
      <div>
        {text && <p>{text}</p>}
        {extra}
      </div>
    </aside>
  );
}

export function Meter({
  value,
  max,
  label,
  gold = false,
}: {
  value: number;
  max: number;
  label: string;
  gold?: boolean;
}) {
  const ratio = Number.isFinite(value) && Number.isFinite(max) && max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  return (
    <div
      className={`meter ${gold ? "gold-track" : ""}`}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={Number.isFinite(max) ? max : 0}
      aria-valuenow={Number.isFinite(value) ? Math.min(value, max) : 0}
    >
      <div className={`meter-fill ${gold ? "gold" : ""}`} style={{ width: `${ratio * 100}%` }} />
    </div>
  );
}

/**
 * Anel segmentado (como no cartão de projeto): `segments` fatias com respiro entre elas,
 * preenchidas até `value`. Com `segments` = 0, vira um anel contínuo proporcional.
 */
export function ProgressRing({
  value,
  max,
  segments = 0,
  size = 40,
  stroke = 3.5,
  label,
  children,
}: {
  value: number;
  max: number;
  segments?: number;
  size?: number;
  stroke?: number;
  /** Descrição acessível do progresso. */
  label: string;
  children?: ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const ratio = Number.isFinite(value) && max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const n = Math.max(0, Math.round(segments));
  const gap = n > 1 ? Math.min(c / n / 3, 4.5) : 0;
  const seg = n > 0 ? c / n : c;
  const filledSegs = n > 0 ? Math.round(ratio * n) : 0;
  return (
    <span className="ring" role="img" aria-label={label} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        {n > 0 ? (
          Array.from({ length: n }, (_, i) => (
            <circle
              key={i}
              className={i < filledSegs ? "ring-fill" : "ring-track"}
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={`${Math.max(0.01, seg - gap - stroke)} ${c}`}
              strokeDashoffset={-(i * seg + gap / 2 + stroke / 2)}
            />
          ))
        ) : (
          <>
            <circle className="ring-track" cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} />
            <circle
              className="ring-fill"
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={`${ratio * c} ${c}`}
              style={{ transition: "stroke-dasharray 0.9s var(--ease)" }}
            />
          </>
        )}
      </svg>
      {children !== undefined && (
        <span className="ring-label" aria-hidden="true">
          {children}
        </span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------- Campos

export function Field({
  label,
  help,
  error,
  children,
  htmlFor,
}: {
  label: string;
  help?: ReactNode;
  error?: string | null;
  children: ReactNode;
  htmlFor: string;
}) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {error ? (
        <p className="error" id={`${htmlFor}-err`}>
          {error}
        </p>
      ) : help ? (
        <p className="help" id={`${htmlFor}-help`}>
          {help}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Campo de dinheiro em formato brasileiro. Mantém o texto digitado e valida no blur;
 * `onValue` recebe a string decimal com ponto (ou null se inválido/vazio).
 */
export function MoneyField({
  label,
  help,
  value,
  onChange,
  required = false,
  optional = false,
  kind = "money",
  id: idProp,
  placeholder,
}: {
  label: string;
  help?: ReactNode;
  value: string;
  onChange: (text: string) => void;
  required?: boolean;
  optional?: boolean;
  kind?: "money" | "percent";
  id?: string;
  placeholder?: string;
}) {
  const autoId = useId();
  const id = idProp ?? autoId;
  const [touched, setTouched] = useState(false);
  const err = touched ? validateNumberText(value, kind, required) : null;
  return (
    <Field label={optional ? `${label} (opcional)` : label} help={help} error={err} htmlFor={id}>
      <div className={`input-affix ${kind === "money" ? "has-prefix" : "has-suffix"}`}>
        {kind === "money" && (
          <span className="prefix" aria-hidden="true">
            R$
          </span>
        )}
        <input
          id={id}
          className="input num"
          inputMode="decimal"
          autoComplete="off"
          spellCheck={false}
          value={value}
          placeholder={placeholder ?? (kind === "money" ? "0,00" : "0,0")}
          onChange={(e) => onChange(e.target.value)}
          onBlur={() => setTouched(true)}
          aria-invalid={err ? true : undefined}
          aria-describedby={err ? `${id}-err` : help ? `${id}-help` : undefined}
          required={required}
        />
        {kind === "percent" && (
          <span className="suffix" aria-hidden="true">
            %
          </span>
        )}
      </div>
    </Field>
  );
}

export function validateNumberText(text: string, kind: "money" | "percent", required: boolean): string | null {
  if (!text.trim()) return required ? "Campo obrigatório." : null;
  const r = kind === "money" ? parseBRL(text) : parsePercent(text);
  return r.ok ? null : r.error;
}

/** Converte vários campos de uma vez; devolve o primeiro erro com o nome do campo. */
export function parseFields<K extends string>(
  fields: Record<K, { text: string; kind: "money" | "percent"; label: string; required?: boolean; allowNegative?: boolean }>,
): { ok: true; values: Record<K, string | null> } | { ok: false; error: string } {
  const values = {} as Record<K, string | null>;
  for (const key of Object.keys(fields) as K[]) {
    const f = fields[key];
    if (!f.text.trim()) {
      if (f.required) return { ok: false, error: `${f.label}: campo obrigatório.` };
      values[key] = null;
      continue;
    }
    const r = f.kind === "money" ? parseBRL(f.text) : parsePercent(f.text);
    if (!r.ok) return { ok: false, error: `${f.label}: ${r.error}` };
    if (!f.allowNegative && r.value.startsWith("-")) return { ok: false, error: `${f.label}: não pode ser negativo.` };
    values[key] = r.value;
  }
  return { ok: true, values };
}

// ---------------------------------------------------------------- Copiar

export function CopyButton({ text, label = "Copiar" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(t);
  }, [copied]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      window.prompt("Copie o texto:", text);
    }
  }
  return (
    <button type="button" className="btn btn-ghost btn-sm" onClick={copy} aria-label={`${label}: ${text}`}>
      <Icon name={copied ? "check" : "copy"} />
      <span aria-live="polite">{copied ? "Copiado" : label}</span>
    </button>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  variant,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  /** "mono": rótulos curtos em maiúsculas, como os seletores de modo das referências. */
  variant?: "mono";
}) {
  return (
    <div className={`segmented ${variant ?? ""}`} role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** AGPL-3.0 §13: quem usa a instância pela rede encontra o código-fonte desta versão. */
export function SourceNotice({ url, license }: { url: string; license: string }) {
  return (
    <p className="tiny muted" style={{ textAlign: "center" }}>
      Software livre ({license}).{" "}
      <a href={url} target="_blank" rel="noopener noreferrer">
        Código-fonte
      </a>
    </p>
  );
}
