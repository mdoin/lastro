// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Radar cripto: ativos acompanhados (preço com moeda e fonte explícitas, indicadores determinísticos, série),
 * eventos separados por gravidade, fontes de dados (saúde, cota, teste, chave da CoinGecko) e preferências, inclusive
 * o opt-in das reuniões autônomas do Conselho. Nada aqui compra, vende ou move ativos.
 */
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  CATEGORY_LABEL,
  SEVERITY_LABEL,
  collectNow,
  conveneEvent,
  deleteCoinGeckoKey,
  getCryptoOverview,
  saveCryptoPrefs,
  setCoinGeckoKey,
  testProvider,
  type CryptoAsset,
  type CryptoEvent,
  type CryptoPrefs,
  type CryptoProvider,
  type Measure,
  type Severity,
} from "../api/crypto";
import { Icon } from "../components/Icon";
import { compactTick, LineChart } from "../components/LineChart";
import { Badge, ErrorNotice, Loading, PageHeader } from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDateTime } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import "../styles/crypto.css";

const PROVIDER_LABEL = { binance: "Binance (dados públicos)", coingecko: "CoinGecko Demo", defillama: "DefiLlama" } as const;
const IND_LABEL: Record<string, string> = {
  retorno_1h: "Retorno 1 h", retorno_4h: "Retorno 4 h", retorno_24h: "Retorno 24 h", retorno_7d: "Retorno 7 d",
  volatilidade: "Volatilidade (por vela)", volume_relativo: "Volume relativo", drawdown_7d: "Queda máxima 7 d",
};
const TIERS: Severity[] = ["conselho", "risco", "atencao"];

const num = (v: string | null | undefined, digits = 2) =>
  v == null ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const pct = (v: string | null | undefined) => (v == null ? "—" : `${num(v)}%`);

export function CryptoRadarPage() {
  const ov = useAsync(getCryptoOverview, []);
  const { toast } = useApp();
  const [busy, setBusy] = useState(false);
  const fail = (e: unknown) => toast(e instanceof ApiError ? e.detail : "Não foi possível concluir.", "error");
  const d = ov.data;

  return (
    <div className="stack-lg crypto">
      <PageHeader eyebrow="Radar" title="Radar cripto"
        lede="O Lastro acompanha BTC, ETH, SOL e o que você escolher, com dados públicos e indicadores calculados sem IA. Só eventos relevantes viram alerta, e o Conselho só se reúne sozinho com a sua autorização."
        actions={<button type="button" className="btn btn-secondary btn-sm" disabled={busy}
          onClick={() => { setBusy(true); void collectNow().then(ov.reload).catch(fail).finally(() => setBusy(false)); }}>
          <Icon name="refresh" /> {busy ? "Coletando…" : "Coletar agora"}</button>} />
      {ov.loading && !d && <Loading />}
      <ErrorNotice error={ov.error} onRetry={ov.reload} />
      {d && (
        <>
          <section className="crypto-assets" aria-label="Ativos acompanhados">
            {d.assets.map((a) => <AssetCard key={a.symbol} a={a} />)}
            {!d.assets.length && <p className="small muted">Nenhum ativo na lista de acompanhamento.</p>}
          </section>

          <section className="crypto-events" aria-labelledby="ev-title">
            <h2 id="ev-title">Eventos</h2>
            <p className="small muted">Oscilações comuns aparecem só nos indicadores. Um sinal é uma observação, nunca uma recomendação.</p>
            {TIERS.map((tier) => {
              const list = d.events.filter((e) => e.severity === tier);
              return (
                <div key={tier} className="crypto-tier" data-tier={tier}>
                  <h3 className="eyebrow">{SEVERITY_LABEL[tier]} ({list.length})</h3>
                  {list.length ? list.map((e) => <EventCard key={e.id} e={e} onConvene={() => void conveneEvent(e.id).then(ov.reload).catch(fail)} />)
                    : <p className="tiny muted">Nenhum.</p>}
                </div>
              );
            })}
          </section>

          <Providers providers={d.providers} onChange={ov.reload} fail={fail} />
          <Prefs prefs={d.prefs} catalog={d.catalog} categories={d.categories} tokens={d.tokens_this_month}
            onSaved={() => { toast("Preferências salvas."); void ov.reload(); }} fail={fail} />

          <section className="crypto-limits" aria-label="Limitações e atribuição">
            <ul className="bullets small">{d.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            <p className="tiny muted">{d.attribution.join(" · ")} · <a href="https://www.coingecko.com" target="_blank" rel="noreferrer noopener">coingecko.com</a></p>
          </section>
        </>
      )}
    </div>
  );
}

function IndicatorValue({ m, kind }: { m: Measure | null | undefined; kind: string }) {
  if (!m || m.value == null) return <span className="muted" title={m?.reason}>—</span>;
  return <span className="mono">{kind === "volume_relativo" ? `${num(m.value)}×` : pct(m.value)}</span>;
}

function AssetCard({ a }: { a: CryptoAsset }) {
  const main = a.quotes.find((q) => q.source === "binance") ?? a.quotes[0];
  const brl = a.quotes.find((q) => q.currency === "BRL");
  const points = a.series.map((p) => ({ x: Date.parse(p.t), y: Number(p.close), raw: p.close }));
  return (
    <article className="crypto-asset" aria-label={`${a.name} (${a.symbol})`}>
      <header className="row between">
        <span><strong className="crypto-symbol">{a.symbol}</strong> <span className="small muted">{a.name}</span></span>
        {main && <Badge tone={main.status === "fresh" ? "good" : "warning"}>{main.status === "fresh" ? "atualizado" : main.status === "stale" ? "desatualizado" : "indisponível"}</Badge>}
      </header>
      {main ? (
        <p className="crypto-price">
          <span className="mono">{num(main.price, main.currency === "USDT" ? 2 : 2)}</span> <span className="crypto-ccy">{main.currency}</span>
          {main.change_24h_pct != null && <span className={`crypto-change mono${Number(main.change_24h_pct) < 0 ? " neg" : " pos"}`}>{pct(main.change_24h_pct)} 24 h</span>}
        </p>
      ) : <p className="small muted">Sem cotação coletada ainda.</p>}
      {brl && <p className="tiny muted">R$ {num(brl.price)} pela CoinGecko · ref. {formatDateTime(brl.reference_time ?? "")}</p>}
      {main && <p className="tiny muted">{main.source === "binance" ? `Binance ${a.pair} (USDT ≠ USD)` : main.source} · ref. {formatDateTime(main.reference_time ?? "")} · coletado {formatDateTime(main.fetched_at ?? "")}</p>}
      {points.length > 2 && (
        <LineChart height={110} ariaLabel={`Fechamento por hora de ${a.symbol} nos últimos 7 dias, em ${a.series_currency}`}
          series={[{ key: a.symbol, label: a.symbol, color: "var(--agent-cripto)", points }]}
          formatX={(x) => new Date(x).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}
          formatTick={compactTick} formatValue={(v) => `${num(v)} ${a.series_currency}`}
          zeroBased={false} />
      )}
      <dl className="crypto-ind">
        {Object.entries(IND_LABEL).map(([k, label]) => (
          <div key={k}><dt>{label}</dt><dd><IndicatorValue m={a.indicators[k]} kind={k} /></dd></div>
        ))}
      </dl>
    </article>
  );
}

function EventCard({ e, onConvene }: { e: CryptoEvent; onConvene: () => void }) {
  return (
    <article className="crypto-event" id={`evento-${e.id}`} data-severity={e.severity}>
      <p className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <strong>{e.asset}</strong>
        <span className="tag plain">{e.categories.map((c) => CATEGORY_LABEL[c] ?? c).join(", ")}</span>
        <span className="tag plain">{e.direction}</span>
        <Badge tone={e.data_quality === "boa" ? "good" : "warning"}>dados: {e.data_quality}</Badge>
        {e.updates > 0 && <span className="tiny muted">{e.updates} atualização(ões) agrupada(s)</span>}
      </p>
      <p className="small">{e.hypothesis}</p>
      <details className="small">
        <summary>Evidências e fontes</summary>
        <ul className="bullets">{e.evidence.map((x, i) => <li key={i}>{x}</li>)}</ul>
        <p className="tiny muted">{e.sources.map((s) => `${s.source} · ref. ${s.reference_time ?? "—"}`).join(" · ")}</p>
      </details>
      <p className="tiny muted">Detectado {formatDateTime(e.first_seen_at)} · última ocorrência {formatDateTime(e.last_seen_at)}</p>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        {e.status === "reuniao" && e.conversation_id ? (
          <Link className="btn btn-secondary btn-sm" to={`/mentor/${e.conversation_id}`}><Icon name="layers" /> Ver reunião do Conselho</Link>
        ) : (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onConvene}><Icon name="layers" /> Pedir análise do Conselho</button>
        )}
        {e.status === "pendente" && <span className="tiny muted">Análise pendente: {e.reason}</span>}
      </div>
    </article>
  );
}

function Providers({ providers, onChange, fail }: { providers: CryptoProvider[]; onChange: () => void; fail: (e: unknown) => void }) {
  const [results, setResults] = useState<Record<string, string>>({});
  const [key, setKey] = useState("");
  const test = async (name: CryptoProvider["name"]) => {
    setResults((r) => ({ ...r, [name]: "Testando…" }));
    try {
      const out = await testProvider(name);
      setResults((r) => ({ ...r, [name]: `${out.ok ? "Conectado" : "Falhou"}: ${out.detail} (${out.latency_ms} ms)` }));
    } catch (e) { fail(e); }
  };
  async function saveKey(e: FormEvent) {
    e.preventDefault();
    try { await setCoinGeckoKey(key.trim()); setKey(""); onChange(); } catch (err) { fail(err); }
  }
  return (
    <section className="crypto-providers" aria-labelledby="prov-title">
      <h2 id="prov-title">Fontes de dados</h2>
      <div className="crypto-provider-grid">
        {providers.map((p) => (
          <article key={p.name} className="crypto-provider">
            <header className="row between">
              <strong>{PROVIDER_LABEL[p.name]}</strong>
              <Badge tone={!p.configured ? "neutral" : p.last_error ? "warning" : p.stale ? "warning" : p.last_ok_at ? "good" : "neutral"}>
                {!p.configured ? "aguarda chave" : p.last_error ? "com erro" : p.stale ? "desatualizada" : p.last_ok_at ? "funcionando" : "sem coleta"}
              </Badge>
            </header>
            <p className="tiny muted">{p.requires_key ? "Exige chave Demo (gratuita)." : "Sem chave: endpoints públicos de leitura."} Coleta a cada {Math.round(p.every_seconds / 60)} min.</p>
            <p className="tiny">Última coleta bem-sucedida: {p.last_ok_at ? formatDateTime(p.last_ok_at) : "—"}{p.latency_ms != null && ` · ${p.latency_ms} ms`} · falhas: {p.failures}</p>
            {p.last_error && <p className="tiny muted">Último erro: {p.last_error}</p>}
            {p.quota && <p className="tiny">Cota: {p.quota.used_month} de {p.quota.limit_month} chamadas no mês · renova em {formatDateTime(p.quota.reset_at)}</p>}
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => void test(p.name)} disabled={!p.configured}>Testar conexão</button>
              <a className="btn btn-ghost btn-sm" href={p.docs_url} target="_blank" rel="noreferrer noopener">Documentação</a>
            </div>
            {results[p.name] && <p className="tiny" role="status">{results[p.name]}</p>}
            {p.name === "coingecko" && (
              <form className="crypto-key" onSubmit={(e) => void saveKey(e)}>
                <label htmlFor="cg-key" className="tiny">{p.configured ? "Substituir a chave Demo" : "Chave Demo da CoinGecko"}</label>
                <input id="cg-key" className="input" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)}
                  placeholder="CG-…" />
                <span className="row" style={{ gap: 8 }}>
                  <button type="submit" className="btn btn-primary btn-sm" disabled={key.trim().length < 10}>Salvar no servidor</button>
                  {p.configured && <button type="button" className="btn btn-ghost btn-sm" onClick={() => void deleteCoinGeckoKey().then(onChange).catch(fail)}>Remover chave</button>}
                </span>
                <span className="tiny muted">A chave fica num arquivo protegido do servidor e nunca volta para o navegador. Veja o passo a passo em docs/CRYPTO.md.</span>
              </form>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function Prefs({ prefs, catalog, categories, tokens, onSaved, fail }: {
  prefs: CryptoPrefs; catalog: { symbol: string; name: string; kind: string }[]; categories: string[]; tokens: number;
  onSaved: () => void; fail: (e: unknown) => void;
}) {
  const [p, setP] = useState<CryptoPrefs>(prefs);
  useEffect(() => setP(prefs), [prefs]);
  const set = <K extends keyof CryptoPrefs>(k: K, v: CryptoPrefs[K]) => setP((x) => ({ ...x, [k]: v }));
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const paused = p.paused_until && Date.parse(p.paused_until) > Date.now();
  async function save(e?: FormEvent, extra: Partial<CryptoPrefs> & { clear_pause?: boolean } = {}) {
    e?.preventDefault();
    try {
      const holdings = Object.fromEntries(Object.entries(p.holdings).filter(([, v]) => v !== "").map(([k, v]) => [k, v.replace(",", ".")]));
      await saveCryptoPrefs({ ...p, holdings, paused_until: undefined, ...extra } as Partial<CryptoPrefs>);
      onSaved();
    } catch (err) { fail(err); }
  }
  return (
    <form className="crypto-prefs" onSubmit={(e) => void save(e)} aria-labelledby="prefs-title">
      <h2 id="prefs-title">Preferências</h2>
      <fieldset>
        <legend className="eyebrow">Lista de acompanhamento e exposição</legend>
        <div className="crypto-watch">
          {catalog.map((c) => (
            <label key={c.symbol} className="team-check small">
              <input type="checkbox" checked={p.watchlist.includes(c.symbol)} onChange={() => set("watchlist", toggle(p.watchlist, c.symbol))} />
              {c.symbol} <span className="muted tiny">{c.name}</span>
            </label>
          ))}
        </div>
        <p className="tiny muted">Quanto você tem em cada ativo (R$, opcional). Sem isso, o Conselho é avisado de que a exposição é desconhecida — nada é presumido.</p>
        <div className="crypto-holdings">
          {p.watchlist.map((s) => (
            <label key={s} className="small">{s}
              <input className="input" inputMode="decimal" value={p.holdings[s] ?? ""} placeholder="0,00"
                onChange={(e) => set("holdings", { ...p.holdings, [s]: e.target.value })} />
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="crypto-grid2">
        <legend className="eyebrow">Sensibilidade e categorias</legend>
        <label className="small">Sensibilidade
          <select className="select" value={p.sensitivity} onChange={(e) => set("sensitivity", e.target.value as CryptoPrefs["sensitivity"])}>
            <option value="baixa">Baixa (só movimentos grandes)</option><option value="media">Média</option><option value="alta">Alta</option>
          </select></label>
        <label className="small">Concentração máxima tolerada
          <input className="input" value={p.concentration_limit} onChange={(e) => set("concentration_limit", e.target.value)} placeholder="0.25" /></label>
        <div className="small">Silenciar categorias:
          <span className="crypto-watch">{categories.map((c) => (
            <label key={c} className="team-check tiny"><input type="checkbox" checked={p.muted.includes(c)} onChange={() => set("muted", toggle(p.muted, c))} /> {CATEGORY_LABEL[c] ?? c}</label>
          ))}</span></div>
      </fieldset>
      <fieldset className="crypto-autonomy">
        <legend className="eyebrow">Reuniões autônomas do Conselho</legend>
        <label className="team-check">
          <input type="checkbox" role="switch" checked={p.autonomous} onChange={(e) => set("autonomous", e.target.checked)} />
          <span><strong>Permitir que o Conselho se reúna sozinho</strong> quando um evento justificar investigação. Cada reunião usa o provedor de IA configurado e consome sua cota ou assinatura; uma assinatura não é capacidade ilimitada.</span>
        </label>
        <div className="crypto-grid2">
          <label className="small">Quero receber
            <select className="select" value={p.deliver} onChange={(e) => set("deliver", e.target.value as CryptoPrefs["deliver"])}>
              <option value="alertas">Só alertas</option><option value="analises">Alertas e análises do Conselho</option>
            </select></label>
          <label className="small">Gravidade mínima para reunião
            <select className="select" value={p.min_severity} onChange={(e) => set("min_severity", e.target.value as CryptoPrefs["min_severity"])}>
              <option value="conselho">Só quando justifica investigação</option><option value="risco">A partir de risco relevante</option>
            </select></label>
          <label className="small">Reuniões por dia (máx.)
            <input className="input" type="number" min={0} max={10} value={p.max_meetings_per_day} onChange={(e) => set("max_meetings_per_day", Number(e.target.value))} /></label>
          <label className="small">Intervalo mínimo por ativo (horas)
            <input className="input" type="number" min={1} max={168} value={p.cooldown_hours} onChange={(e) => set("cooldown_hours", Number(e.target.value))} /></label>
          <label className="small">Silêncio das
            <input className="input" type="time" value={p.quiet_start} onChange={(e) => set("quiet_start", e.target.value)} /></label>
          <label className="small">até as
            <input className="input" type="time" value={p.quiet_end} onChange={(e) => set("quiet_end", e.target.value)} /></label>
          <label className="small">Orçamento mensal de IA (tokens; 0 = sem teto)
            <input className="input" type="number" min={0} value={p.monthly_token_budget} onChange={(e) => set("monthly_token_budget", Number(e.target.value))} /></label>
          <p className="tiny muted">Usados neste mês por reuniões automáticas: {tokens.toLocaleString("pt-BR")} tokens (quando o provedor informa).</p>
        </div>
      </fieldset>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button type="submit" className="btn btn-primary btn-sm">Salvar preferências</button>
        {paused ? (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void save(undefined, { clear_pause: true })}>Retomar monitoramento (pausado até {formatDateTime(p.paused_until!)})</button>
        ) : (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void save(undefined, { paused_until: new Date(Date.now() + 24 * 3600_000).toISOString() })}>Pausar reuniões por 24 h</button>
        )}
      </div>
    </form>
  );
}
