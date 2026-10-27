// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Campo de data com calendário próprio: o calendário nativo do navegador não aceita estilo e destoava do sistema.
 * Valor no formato da API (AAAA-MM-DD); exibe e aceita digitação em dd/mm/aaaa.
 * Teclado no calendário (padrão "date picker dialog" da WAI-ARIA): setas, PageUp/PageDown (Shift = ano),
 * Home/End (início/fim da semana), Enter/Espaço escolhe, Esc fecha.
 */
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { Icon } from "./Icon";

const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const WEEKDAYS = ["D", "S", "T", "Q", "Q", "S", "S"];
const WEEKDAYS_LONG = ["domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado"];

interface Ymd {
  y: number;
  /** 0 = janeiro */
  m: number;
  d: number;
}

const pad = (n: number) => String(n).padStart(2, "0");
const daysIn = (y: number, m: number) => new Date(y, m + 1, 0).getDate();
const valid = (y: number, m: number, d: number) => y >= 1000 && y <= 9999 && m >= 0 && m <= 11 && d >= 1 && d <= daysIn(y, m);

function parseISO(v: string): Ymd | null {
  const r = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (!r) return null;
  const y = Number(r[1]), m = Number(r[2]) - 1, d = Number(r[3]);
  return valid(y, m, d) ? { y, m, d } : null;
}

/** "27/10/2026" → data; só aceita a data completa e existente. */
function parseBR(v: string): Ymd | null {
  const r = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(v);
  if (!r) return null;
  const d = Number(r[1]), m = Number(r[2]) - 1, y = Number(r[3]);
  return valid(y, m, d) ? { y, m, d } : null;
}

const toISO = (p: Ymd) => `${p.y}-${pad(p.m + 1)}-${pad(p.d)}`;
const toBR = (p: Ymd) => `${pad(p.d)}/${pad(p.m + 1)}/${p.y}`;
const same = (a: Ymd | null, b: Ymd | null) => !!a && !!b && a.y === b.y && a.m === b.m && a.d === b.d;

function fromDate(dt: Date): Ymd {
  return { y: dt.getFullYear(), m: dt.getMonth(), d: dt.getDate() };
}

const addDays = (p: Ymd, n: number) => fromDate(new Date(p.y, p.m, p.d + n));

function addMonths(p: Ymd, n: number): Ymd {
  const first = new Date(p.y, p.m + n, 1);
  const y = first.getFullYear(), m = first.getMonth();
  return { y, m, d: Math.min(p.d, daysIn(y, m)) };
}

const weekday = (p: Ymd) => new Date(p.y, p.m, p.d).getDay();
const today = () => fromDate(new Date());

/** Máscara progressiva: "27102026" → "27/10/2026". */
function mask(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

/** Semanas do mês (domingo primeiro); dias de outros meses ficam vazios. */
function monthWeeks(y: number, m: number): (Ymd | null)[][] {
  const lead = new Date(y, m, 1).getDay();
  const cells: (Ymd | null)[] = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= daysIn(y, m); d++) cells.push({ y, m, d });
  while (cells.length % 7) cells.push(null);
  const weeks: (Ymd | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

export function DateInput({
  id: idProp,
  value,
  onChange,
  required = false,
  placeholder = "dd/mm/aaaa",
  "aria-describedby": describedBy,
}: {
  id?: string;
  /** AAAA-MM-DD ou "". */
  value: string;
  /** Recebe AAAA-MM-DD (ou "" ao limpar), no mesmo formato de evento do campo nativo. */
  onChange: (e: { target: { value: string } }) => void;
  required?: boolean;
  placeholder?: string;
  "aria-describedby"?: string;
}) {
  const autoId = useId();
  const id = idProp ?? autoId;
  const selected = parseISO(value);
  const [text, setText] = useState(selected ? toBR(selected) : "");
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"days" | "months">("days");
  const [cursor, setCursor] = useState<Ymd>(selected ?? today());
  const [place, setPlace] = useState({ up: false, right: false });
  const wrapRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const titleId = `${id}-cal-title`;

  // Valor mudou por fora (escolha no calendário, formulário reiniciado): o texto acompanha.
  useEffect(() => {
    const p = parseISO(value);
    setText(p ? toBR(p) : "");
  }, [value]);

  const emit = (v: string) => onChange({ target: { value: v } });

  function close(returnFocus: boolean) {
    setOpen(false);
    if (returnFocus) toggleRef.current?.focus();
  }

  function openCalendar() {
    setCursor(parseISO(value) ?? today());
    setView("days");
    setOpen(true);
  }

  function pick(p: Ymd) {
    emit(toISO(p));
    close(true);
  }

  // Fecha ao tocar fora.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  // Abre para cima e/ou alinhado à direita quando não cabe na tela.
  useLayoutEffect(() => {
    if (!open || !wrapRef.current || !popRef.current) return;
    const field = wrapRef.current.getBoundingClientRect();
    const pop = popRef.current.getBoundingClientRect();
    const below = window.innerHeight - field.bottom;
    setPlace({
      up: below < pop.height + 12 && field.top > pop.height + 12,
      right: field.left + pop.width > window.innerWidth - 12,
    });
  }, [open]);

  // O dia em foco acompanha o cursor do teclado.
  useEffect(() => {
    if (!open || view !== "days") return;
    popRef.current?.querySelector<HTMLElement>(`[data-iso="${toISO(cursor)}"]`)?.focus();
  }, [open, view, cursor]);

  function onText(raw: string) {
    const t = mask(raw);
    setText(t);
    if (!t) emit("");
    const p = parseBR(t);
    if (p) emit(toISO(p));
  }

  function onBlur() {
    // O que fica na tela é sempre o valor que o formulário vai usar.
    if (!text) return;
    const p = parseBR(text);
    if (!p) setText(selected ? toBR(selected) : "");
  }

  function onGridKey(e: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, () => Ymd> = {
      ArrowLeft: () => addDays(cursor, -1),
      ArrowRight: () => addDays(cursor, 1),
      ArrowUp: () => addDays(cursor, -7),
      ArrowDown: () => addDays(cursor, 7),
      PageUp: () => addMonths(cursor, e.shiftKey ? -12 : -1),
      PageDown: () => addMonths(cursor, e.shiftKey ? 12 : 1),
      Home: () => addDays(cursor, -weekday(cursor)),
      End: () => addDays(cursor, 6 - weekday(cursor)),
    };
    const move = moves[e.key];
    if (move) {
      e.preventDefault();
      setCursor(move());
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      pick(cursor);
    }
  }

  const typedInvalid = text.length === 10 && !parseBR(text);
  const now = today();

  return (
    <div className="date-field" ref={wrapRef}>
      <input
        id={id}
        className="input num"
        inputMode="numeric"
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholder}
        maxLength={10}
        value={text}
        required={required}
        aria-invalid={typedInvalid ? true : undefined}
        aria-describedby={describedBy}
        onChange={(e) => onText(e.target.value)}
        onBlur={onBlur}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && e.altKey) {
            e.preventDefault();
            openCalendar();
          }
        }}
      />
      <button
        ref={toggleRef}
        type="button"
        className="date-toggle"
        aria-label={open ? "Fechar calendário" : "Abrir calendário"}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => (open ? close(false) : openCalendar())}
      >
        <Icon name="calendar" />
      </button>

      {open && (
        <div
          ref={popRef}
          className={`datepicker ${place.up ? "up" : ""} ${place.right ? "right" : ""}`}
          role="dialog"
          aria-modal="false"
          aria-labelledby={titleId}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              e.stopPropagation();
              close(true);
            }
          }}
        >
          <div className="dp-head">
            <button
              type="button"
              className="dp-nav"
              aria-label={view === "days" ? "Mês anterior" : "Ano anterior"}
              onClick={() => setCursor(addMonths(cursor, view === "days" ? -1 : -12))}
            >
              <Icon name="chevronRight" style={{ transform: "rotate(180deg)" }} />
            </button>
            <button
              type="button"
              id={titleId}
              className="dp-title"
              aria-label={view === "days" ? `${MONTHS[cursor.m]} de ${cursor.y}. Escolher mês e ano` : `${cursor.y}. Voltar aos dias`}
              onClick={() => setView(view === "days" ? "months" : "days")}
            >
              {view === "days" ? `${MONTHS[cursor.m]} de ${cursor.y}` : cursor.y}
              <Icon name="chevronDown" className={view === "months" ? "flip" : ""} />
            </button>
            <button
              type="button"
              className="dp-nav"
              aria-label={view === "days" ? "Próximo mês" : "Próximo ano"}
              onClick={() => setCursor(addMonths(cursor, view === "days" ? 1 : 12))}
            >
              <Icon name="chevronRight" />
            </button>
          </div>

          <div className="dp-sheet">
            {view === "days" ? (
              <div role="grid" aria-labelledby={titleId} className="dp-grid" onKeyDown={onGridKey}>
                <div role="row" className="dp-row dp-week">
                  {WEEKDAYS.map((w, i) => (
                    <span key={i} role="columnheader" aria-label={WEEKDAYS_LONG[i]}>
                      {w}
                    </span>
                  ))}
                </div>
                {monthWeeks(cursor.y, cursor.m).map((week, wi) => (
                  <div role="row" key={wi} className="dp-row">
                    {week.map((p, di) =>
                      p ? (
                        <div
                          key={di}
                          role="gridcell"
                          data-iso={toISO(p)}
                          tabIndex={same(p, cursor) ? 0 : -1}
                          aria-selected={same(p, selected)}
                          aria-current={same(p, now) ? "date" : undefined}
                          aria-label={`${p.d} de ${MONTHS[p.m]} de ${p.y}, ${WEEKDAYS_LONG[weekday(p)]}${same(p, now) ? ", hoje" : ""}`}
                          className={`dp-day ${same(p, now) ? "today" : ""}`}
                          onClick={() => pick(p)}
                        >
                          {p.d}
                        </div>
                      ) : (
                        <div key={di} role="gridcell" className="dp-empty" />
                      ),
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="dp-months" role="group" aria-label={`Meses de ${cursor.y}`}>
                {MONTHS_SHORT.map((label, m) => (
                  <button
                    key={label}
                    type="button"
                    className="dp-month"
                    aria-pressed={!!selected && selected.y === cursor.y && selected.m === m}
                    aria-label={`${label}, ${MONTHS[m]} de ${cursor.y}`}
                    onClick={() => {
                      setCursor({ y: cursor.y, m, d: Math.min(cursor.d, daysIn(cursor.y, m)) });
                      setView("days");
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="dp-foot">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => pick(now)}>
              Hoje
            </button>
            {!required && value && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  emit("");
                  close(true);
                }}
              >
                Limpar
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
