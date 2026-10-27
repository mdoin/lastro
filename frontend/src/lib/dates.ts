/** Datas no padrão brasileiro, sem deslocamento de fuso para datas puras (AAAA-MM-DD). */

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** "2026-10-26" → "26/10/2026". */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const m = DATE_RE.exec(value.slice(0, 10));
  if (!m) return value;
  return `${m[3]}/${m[2]}/${m[1]}`;
}

/** "2026-10" → "out/2026" a partir de uma data pura. */
export function formatMonthYear(value: string): string {
  const m = DATE_RE.exec(value.slice(0, 10));
  if (!m) return value;
  const months = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  return `${months[Number(m[2]) - 1] ?? m[2]}/${m[1]}`;
}

const dateTimeFmt = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const timeFmt = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });

/** Data-hora ISO → "26/10/2026, 14:05" no fuso do aparelho (ou no fuso IANA informado). */
export function formatDateTime(value: string | null | undefined, timeZone?: string): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  if (timeZone) {
    try {
      return new Intl.DateTimeFormat("pt-BR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone,
      }).format(d);
    } catch {
      /* fuso inválido: cai no fuso do aparelho */
    }
  }
  return dateTimeFmt.format(d);
}

/** Data-hora ISO → "14:05". */
export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return timeFmt.format(d);
}

/** Hoje como AAAA-MM-DD no fuso do aparelho. */
export function todayISO(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** Dias inteiros entre uma data pura e hoje (positivo = no passado). */
export function daysSince(value: string | null | undefined): number | null {
  if (!value) return null;
  const m = DATE_RE.exec(value.slice(0, 10));
  if (!m) return null;
  const then = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((today - then) / 86_400_000);
}

export function relativeDays(value: string | null | undefined): string {
  const n = daysSince(value);
  if (n === null) return "";
  if (n <= 0) return "hoje";
  if (n === 1) return "ontem";
  if (n < 45) return `há ${n} dias`;
  const months = Math.round(n / 30);
  return months <= 1 ? "há cerca de 1 mês" : `há cerca de ${months} meses`;
}
