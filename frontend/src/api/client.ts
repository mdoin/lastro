// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Cliente HTTP do Lastro.
 * - `credentials: "same-origin"` (cookie de sessão HttpOnly).
 * - `X-Lastro: 1` em toda requisição que altera estado (POST/PUT/DELETE).
 * - 401 → redireciona para o login (exceto no próprio login).
 * - Erros viram `ApiError` com a mensagem em português de `{"detail": ...}`.
 */
import { readSSE, type SSEFrame } from "./sse";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type Method = "GET" | "POST" | "PUT" | "DELETE";

let unauthorizedHandler: () => void = () => {
  if (!window.location.pathname.startsWith("/login")) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/login?next=${next}`);
  }
};

/** O App registra aqui a navegação do roteador para 401 (evita recarregar a página). */
export function setUnauthorizedHandler(fn: () => void): void {
  unauthorizedHandler = fn;
}

const FALLBACK_BY_STATUS: Record<number, string> = {
  400: "Requisição inválida.",
  401: "Sessão expirada. Entre novamente.",
  403: "Acesso negado.",
  404: "Não encontrado.",
  409: "Conflito: o estado mudou. Atualize a página.",
  422: "Dados inválidos. Revise os campos.",
  429: "Muitas tentativas. Aguarde um pouco e tente de novo.",
  503: "Serviço temporariamente indisponível.",
};

/** Extrai a mensagem de `{"detail": ...}`. FastAPI pode mandar `detail` como lista de erros (422). */
function detailFrom(body: unknown, status: number): string {
  const fallback = FALLBACK_BY_STATUS[status] ?? `Erro ${status}.`;
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => {
        if (d && typeof d === "object") {
          const msg = (d as { msg?: unknown }).msg;
          const loc = (d as { loc?: unknown }).loc;
          const field = Array.isArray(loc) ? loc.filter((x) => x !== "body").join(".") : "";
          if (typeof msg === "string") return field ? `${field}: ${msg}` : msg;
        }
        return null;
      })
      .filter((m): m is string => !!m);
    if (msgs.length) return msgs.join(" · ");
  }
  return fallback;
}

interface RequestOptions {
  body?: unknown;
  /** Não redirecionar em 401 (ex.: senha errada no login). */
  noAuthRedirect?: boolean;
  signal?: AbortSignal;
}

function buildInit(method: Method, opts: RequestOptions, accept: string): RequestInit {
  const headers: Record<string, string> = { Accept: accept };
  if (method !== "GET") headers["X-Lastro"] = "1";
  const init: RequestInit = { method, credentials: "same-origin", headers, cache: "no-store" };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  if (opts.signal) init.signal = opts.signal;
  return init;
}

async function failFrom(res: Response, opts: RequestOptions): Promise<never> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (res.status === 401 && !opts.noAuthRedirect) unauthorizedHandler();
  throw new ApiError(res.status, detailFrom(body, res.status));
}

export async function request<T>(method: Method, path: string, opts: RequestOptions = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, buildInit(method, opts, "application/json"));
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Sem conexão com o servidor. Verifique a rede e tente de novo.");
  }
  if (!res.ok) return failFrom(res, opts);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(res.status, "Resposta inesperada do servidor.");
  }
}

/** Envia um arquivo como corpo binário (sem multipart); o nome vai no cabeçalho, codificado. */
export async function uploadBinary<T>(path: string, file: Blob, filename: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST", credentials: "same-origin", cache: "no-store", body: file,
      headers: { Accept: "application/json", "X-Lastro": "1", "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(filename) },
    });
  } catch {
    throw new ApiError(0, "Sem conexão com o servidor. Verifique a rede e tente de novo.");
  }
  if (!res.ok) return failFrom(res, {});
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("POST", path, { ...opts, body }),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("PUT", path, { ...opts, body }),
  del: <T = void>(path: string, opts?: RequestOptions) => request<T>("DELETE", path, opts),
};

/** Um evento SSE já com `data` convertido de JSON. */
export interface ParsedEvent {
  event: string;
  data: unknown;
}

function parseFrame(frame: SSEFrame): ParsedEvent {
  try {
    return { event: frame.event, data: frame.data ? JSON.parse(frame.data) : null };
  } catch {
    return { event: frame.event, data: { text: frame.data } };
  }
}

/**
 * POST que responde com Server-Sent Events. Resolve quando o fluxo termina.
 * Erros HTTP antes do fluxo viram `ApiError`; queda de conexão no meio vira `ApiError(0)`.
 */
export async function postStream<E extends { event: string; data: unknown }>(
  path: string,
  body: unknown,
  onEvent: (ev: E) => void,
  signal?: AbortSignal,
): Promise<void> {
  const opts: RequestOptions = { body };
  if (signal) opts.signal = signal;
  let res: Response;
  try {
    res = await fetch(path, buildInit("POST", opts, "text/event-stream"));
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Sem conexão com o servidor.");
  }
  if (!res.ok) return failFrom(res, opts);
  if (!res.body) throw new ApiError(res.status, "O servidor não enviou o fluxo de resposta.");
  try {
    await readSSE(res.body, (f) => onEvent(parseFrame(f) as E), signal);
  } catch (e) {
    if (signal?.aborted) return;
    if (e instanceof DOMException && e.name === "AbortError") return;
    throw new ApiError(0, "A conexão caiu durante a resposta.");
  }
}
