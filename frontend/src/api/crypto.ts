// SPDX-License-Identifier: AGPL-3.0-or-later
/** Radar cripto e central de notificações (docs/CRYPTO.md). Preços são strings decimais com moeda explícita. */
import { api } from "./client";

export type Severity = "comum" | "atencao" | "risco" | "conselho";
export interface Measure { value: string | null; reason: string }
export interface CryptoQuote {
  source: string; currency: "USDT" | "USD" | "BRL"; price: string; change_24h_pct: string | null;
  reference_time: string | null; fetched_at: string | null; status: "fresh" | "stale" | "unavailable";
}
export interface CryptoAsset {
  symbol: string; name: string; pair: string | null; quotes: CryptoQuote[];
  indicators: Record<string, Measure | null>; series: { t: string; close: string }[]; series_currency: string | null;
}
export interface CryptoProvider {
  name: "binance" | "coingecko" | "defillama"; requires_key: boolean; configured: boolean; docs_url: string;
  last_run_at: string | null; last_ok_at: string | null; last_error: string | null; latency_ms: number | null;
  failures: number; runs: number; every_seconds: number; stale: boolean; blocked_until?: string | null;
  quota: { used_month: number; limit_month: number; remaining: number; remaining_for_poll: number; reset_at: string } | null;
}
export interface CryptoEvent {
  id: string; asset: string; categories: string[]; direction: string; severity: Severity; relevance: string;
  data_quality: "boa" | "limitada" | "insuficiente"; hypothesis: string; evidence: string[];
  sources: { source: string; reference_time?: string; fetched_at?: string }[];
  first_seen_at: string; last_seen_at: string; updates: number;
  status: "registrado" | "alerta" | "reuniao" | "pendente" | "descartado"; reason: string;
  conversation_id: string | null; run_id: string | null;
}
export interface CryptoPrefs {
  watchlist: string[]; holdings: Record<string, string>; sensitivity: "baixa" | "media" | "alta"; muted: string[];
  concentration_limit: string; autonomous: boolean; deliver: "alertas" | "analises"; min_severity: "atencao" | "risco" | "conselho";
  max_meetings_per_day: number; cooldown_hours: number; quiet_start: string; quiet_end: string; paused_until: string | null;
  monthly_token_budget: number;
}
export interface CryptoOverview {
  assets: CryptoAsset[]; providers: CryptoProvider[]; events: CryptoEvent[]; prefs: CryptoPrefs; stats: Record<string, number>;
  catalog: { symbol: string; name: string; kind: string }[]; categories: string[]; limitations: string[]; attribution: string[];
  tokens_this_month: number; now: string;
}
export interface AppNotification {
  id: string; kind: string; severity: string; title: string; body: string; link: string; status: "novo" | "lido"; created_at: string;
}

export const getCryptoOverview = () => api.get<CryptoOverview>("/api/crypto/overview");
export const saveCryptoPrefs = (p: Partial<CryptoPrefs> & { clear_pause?: boolean }) => api.put<CryptoPrefs>("/api/crypto/prefs", p);
export const setCoinGeckoKey = (key: string) => api.put<void>("/api/crypto/coingecko-key", { key });
export const deleteCoinGeckoKey = () => api.del<void>("/api/crypto/coingecko-key");
export const testProvider = (name: CryptoProvider["name"]) =>
  api.post<{ provider: string; ok: boolean; detail: string; latency_ms: number; quota: CryptoProvider["quota"] }>(`/api/crypto/providers/${name}/test`);
export const collectNow = () => api.post<unknown>("/api/crypto/collect");
export const conveneEvent = (id: string) => api.post<{ status: string; event: CryptoEvent }>(`/api/crypto/events/${encodeURIComponent(id)}/convene`);

export const getNotifications = () => api.get<{ items: AppNotification[]; unread: number }>("/api/notifications");
export const readNotification = (id: string) => api.post<void>(`/api/notifications/${encodeURIComponent(id)}/read`);
export const readAllNotifications = () => api.post<void>("/api/notifications/read-all");

export const SEVERITY_LABEL: Record<Severity, string> = {
  comum: "Movimentação comum", atencao: "Merece atenção", risco: "Risco relevante", conselho: "Investigação do Conselho",
};
export const CATEGORY_LABEL: Record<string, string> = {
  preco: "preço", volume: "volume", volatilidade: "volatilidade", concentracao: "concentração", liquidez: "liquidez",
  stablecoin: "paridade de stablecoin", defi: "DeFi",
};
