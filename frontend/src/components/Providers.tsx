// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Contas de IA da instalação: conectar (chave ou login oficial do CLI), testar, escolher modelo, tornar padrão,
 * desconectar; e o provedor/modelo de cada agente. Nenhum segredo volta do servidor: só "…1234".
 */
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import {
  codexApiKey,
  deleteProvider,
  getProviders,
  providerAction,
  putAgentModels,
  saveProvider,
  submitLoginCode,
} from "../api/endpoints";
import type { AgentModelChoice, ProviderConnection, ProviderResult, ProvidersOverview, ProviderType } from "../api/types";
import { useAsync } from "../lib/useAsync";
import { Icon } from "./Icon";
import { Badge, CopyButton, ErrorNotice, Field, Loading, Notice } from "./ui";

const SETTING_LABELS: Record<string, string> = {
  model: "Modelo padrão",
  base_url: "Endereço da API",
  timeout: "Tempo limite (s)",
  max_tokens: "Limite de saída por passo",
  tools: "Suporta ferramentas?",
  context_tokens: "Janela de contexto (tokens)",
  effort: "Enviar esforço de raciocínio?",
};
const CLI_TYPES = new Set(["claude_code", "codex"]);
const TERMINAL_LOGIN: Record<string, string> = {
  claude_code: "docker compose exec -it mentor python -m providers.claude_code login",
  codex: "docker compose exec -it mentor codex login --device-auth",
};

function message(err: unknown): string {
  return err instanceof ApiError ? err.detail : "Não foi possível concluir.";
}

function capabilityBadges(c: ProviderConnection["capabilities"]) {
  return (
    <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
      {c.tools ? <Badge tone="good">ferramentas do Lastro</Badge> : <Badge tone="warning">sem ferramentas</Badge>}
      {c.streaming && <Badge>respostas em tempo real</Badge>}
      {c.native_resume ? <Badge>retoma sessão nativa</Badge> : <Badge>contexto pelo histórico do Lastro</Badge>}
      {c.external_login && <Badge>login pelo CLI oficial</Badge>}
      {c.experimental && <Badge tone="warning">experimental</Badge>}
    </div>
  );
}

// ---------------------------------------------------------------- login oficial dos executáveis

function CliLogin({ conn, onDone }: { conn: ProviderConnection; onDone: () => void }) {
  const [flow, setFlow] = useState<ProviderResult | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<ProviderResult>) {
    setBusy(true);
    setError(null);
    try {
      const result = await fn();
      if (result.ok === false) setError(result.error || result.detail || "Login não concluído.");
      return result;
    } catch (err) {
      setError(message(err));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    const result = await run(() => providerAction(conn.id, "login_start"));
    if (result?.ok) setFlow(result);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const result = await run(() => submitLoginCode(conn.id, code.trim()));
    setCode("");
    if (result?.state === "done") {
      setFlow(null);
      onDone();
    } else if (result) setFlow(result);
  }

  async function confirmDevice() {
    const result = await run(() => providerAction(conn.id, "login_status", flow?.login_id));
    if (result?.ok) {
      setFlow(null);
      onDone();
    } else setError("Ainda não confirmado na página da OpenAI. Conclua lá e tente de novo.");
  }

  async function cancel() {
    await run(() => providerAction(conn.id, "login_cancel", flow?.login_id));
    setFlow(null);
  }

  if (!flow) {
    return (
      <div className="stack-sm">
        {conn.type === "claude_code" && (
          <Notice tone="warning" title="Antes de usar uma assinatura Claude:">
            o login acontece na página da Anthropic e o código vai direto para o Claude Code oficial no servidor; o
            Lastro não guarda esse código nem o token. A Anthropic recomenda chave de API para produtos que usam o Agent
            SDK. Leia <code className="tag">docs/PROVIDER_TERMS.md</code> e decida.
          </Notice>
        )}
        <div className="row" style={{ flexWrap: "wrap" }}>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void start()} disabled={busy}>
            <Icon name="lock" />
            {conn.type === "codex" ? "Entrar com a conta do ChatGPT" : "Entrar com a conta Claude"}
          </button>
        </div>
        <p className="tiny muted">
          Prefere o terminal do servidor? <code className="tag">{TERMINAL_LOGIN[conn.type]}</code>
        </p>
        {error && <Notice tone="error">{error}</Notice>}
      </div>
    );
  }

  return (
    <div className="stack-sm">
      {flow.kind === "device_code" ? (
        <>
          <p className="small">
            1. Abra a página da OpenAI e entre na sua conta. 2. Digite este código:{" "}
            <strong className="mono">{flow.code}</strong> <CopyButton text={flow.code ?? ""} label="Copiar código" />
          </p>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <a className="btn btn-secondary btn-sm" href={flow.url ?? "#"} target="_blank" rel="noopener noreferrer">
              <Icon name="arrowUpRight" />
              Abrir página da OpenAI
            </a>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => void confirmDevice()} disabled={busy}>
              <Icon name="check" />
              Já confirmei
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void cancel()} disabled={busy}>
              Cancelar
            </button>
          </div>
        </>
      ) : (
        <form className="stack-sm" onSubmit={submit}>
          <p className="small">
            1. Abra a página da Anthropic e entre na sua conta. 2. Copie o código que ela mostrar e cole aqui.
          </p>
          <a className="btn btn-secondary btn-sm" href={flow.url ?? "#"} target="_blank" rel="noopener noreferrer">
            <Icon name="arrowUpRight" />
            Abrir página da Anthropic
          </a>
          <Field label="Código mostrado pela Anthropic" htmlFor={`code-${conn.id}`}>
            <input id={`code-${conn.id}`} className="input mono" value={code} autoComplete="off" spellCheck={false}
              onChange={(e) => setCode(e.target.value)} />
          </Field>
          <div className="row">
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy || code.trim().length < 4}>
              {busy ? "Conferindo…" : "Concluir login"}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void cancel()} disabled={busy}>
              Cancelar
            </button>
          </div>
        </form>
      )}
      {error && <Notice tone="error">{error}</Notice>}
    </div>
  );
}

// ---------------------------------------------------------------- uma conexão

function ConnectionCard({ conn, onChange }: { conn: ProviderConnection; onChange: () => void }) {
  const [result, setResult] = useState<ProviderResult | null>(null);
  const [models, setModels] = useState<{ id: string; label: string }[] | null>(null);
  const [model, setModel] = useState(conn.settings.model ?? "");
  const [codexKey, setCodexKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError(message(err));
      return null;
    } finally {
      setBusy(false);
    }
  }

  const test = () => act(async () => setResult(await providerAction(conn.id, "test")));
  const loadModels = () =>
    act(async () => {
      const r = await providerAction(conn.id, "models");
      if (r.ok === false) setError(r.detail ?? "Não foi possível listar os modelos.");
      else setModels(r.models ?? []);
    });
  const saveModel = () =>
    act(async () => {
      await saveProvider({ id: conn.id, type: conn.type, label: conn.label, settings: { ...conn.settings, model } });
      onChange();
    });
  const makeDefault = () => act(async () => { await providerAction(conn.id, "default"); onChange(); });
  const revoke = () =>
    act(async () => {
      if (!window.confirm("Desconectar esta conta neste servidor?")) return;
      setResult(await providerAction(conn.id, "revoke"));
      onChange();
    });
  const remove = () =>
    act(async () => {
      if (!window.confirm(`Remover a conexão "${conn.label}"? Agentes que a usam voltam para a conexão padrão.`)) return;
      await deleteProvider(conn.id);
      onChange();
    });
  const sendCodexKey = () =>
    act(async () => {
      setResult(await codexApiKey(conn.id, codexKey.trim()));
      setCodexKey("");
    });

  return (
    <article className="card stack-sm" aria-label={conn.label}>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <div>
          <strong>{conn.label}</strong> <span className="tag">{conn.type}</span>
        </div>
        <div className="row" style={{ gap: 6 }}>
          {conn.default && <Badge tone="gold" icon="check">padrão</Badge>}
          {conn.configured ? <Badge tone="good">{CLI_TYPES.has(conn.type) ? "CLI instalado" : "configurada"}</Badge>
            : <Badge tone="warning">incompleta</Badge>}
        </div>
      </div>
      {capabilityBadges(conn.capabilities)}
      {conn.capabilities.notes && <p className="tiny muted">{conn.capabilities.notes}</p>}
      <dl className="kv small">
        {conn.secret_hint && (<><dt>Chave</dt><dd className="mono">{conn.secret_hint}</dd></>)}
        {conn.settings.base_url && (<><dt>Endereço</dt><dd className="mono">{conn.settings.base_url}</dd></>)}
        <dt>Modelo padrão</dt>
        <dd>{conn.settings.model || <span className="muted">o do provedor</span>}</dd>
      </dl>

      {CLI_TYPES.has(conn.type) && <CliLogin conn={conn} onDone={() => void test()} />}
      {conn.type === "codex" && (
        <div className="row" style={{ flexWrap: "wrap" }}>
          <input className="input" type="password" placeholder="ou chave de API da OpenAI" value={codexKey}
            autoComplete="off" aria-label="Chave de API da OpenAI para o Codex" onChange={(e) => setCodexKey(e.target.value)} />
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy || codexKey.trim().length < 8}
            onClick={() => void sendCodexKey()}>Usar chave</button>
        </div>
      )}

      <div className="row" style={{ flexWrap: "wrap" }}>
        <input className="input" list={`models-${conn.id}`} value={model} placeholder="modelo"
          aria-label={`Modelo padrão de ${conn.label}`} onChange={(e) => setModel(e.target.value)} />
        <datalist id={`models-${conn.id}`}>
          {(models ?? []).map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </datalist>
        {conn.capabilities.model_listing && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void loadModels()} disabled={busy}>
            Listar modelos
          </button>
        )}
        <button type="button" className="btn btn-secondary btn-sm" disabled={busy || model === (conn.settings.model ?? "")}
          onClick={() => void saveModel()}>Salvar modelo</button>
      </div>

      <div className="row" style={{ flexWrap: "wrap" }}>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => void test()} disabled={busy}>
          <Icon name="pulse" />
          Testar conexão
        </button>
        {!conn.default && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void makeDefault()} disabled={busy}>
            Tornar padrão
          </button>
        )}
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => void revoke()} disabled={busy}>
          <Icon name="logout" />
          {CLI_TYPES.has(conn.type) ? "Desconectar conta" : "Apagar chave"}
        </button>
        <button type="button" className="btn btn-danger btn-sm" onClick={() => void remove()} disabled={busy}>
          <Icon name="trash" />
          Remover
        </button>
      </div>
      {result && (
        <Notice tone={result.ok ? "success" : "warning"}>{result.detail ?? (result.ok ? "Tudo certo." : "Falhou.")}</Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}
    </article>
  );
}

// ---------------------------------------------------------------- nova conexão

function NewConnection({ types, onSaved }: { types: ProviderType[]; onSaved: (conn: ProviderConnection) => void }) {
  const available = types.filter((t) => t.installed);
  const [type, setType] = useState(available[0]?.type ?? "");
  const [label, setLabel] = useState("");
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chosen = available.find((t) => t.type === type);
  const needsKey = chosen?.capabilities.api_key && !CLI_TYPES.has(type);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const clean = Object.fromEntries(Object.entries(settings).filter(([, v]) => v.trim() !== ""));
      // A primeira conexão vira a padrão no servidor; as demais só quando a pessoa pedir ("Tornar padrão").
      const conn = await saveProvider({ type, label, settings: clean, api_key: apiKey || undefined });
      setApiKey("");
      setSettings({});
      setLabel("");
      onSaved(conn);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  if (!chosen) return <Notice tone="warning">Nenhum tipo de provedor disponível neste servidor.</Notice>;
  return (
    <form className="card stack-sm" onSubmit={submit} aria-label="Nova conexão de IA">
      <Field label="Provedor" htmlFor="provider-type">
        <select id="provider-type" className="select" value={type} onChange={(e) => { setType(e.target.value); setSettings({}); }}>
          {available.map((t) => <option key={t.type} value={t.type}>{t.label}{t.capabilities.experimental ? " (experimental)" : ""}</option>)}
        </select>
      </Field>
      {chosen.capabilities.notes && <p className="tiny muted">{chosen.capabilities.notes}</p>}
      <Field label="Nome" htmlFor="provider-label" help="Opcional. Ex.: Claude da família, Ollama do notebook.">
        <input id="provider-label" className="input" value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} />
      </Field>
      {Object.keys(chosen.settings).map((key) => (
        <Field key={key} label={SETTING_LABELS[key] ?? key} htmlFor={`setting-${key}`} help={chosen.settings[key]}>
          <input id={`setting-${key}`} className="input" value={settings[key] ?? ""}
            placeholder={key === "base_url" ? chosen.default_base_url ?? "" : ""}
            onChange={(e) => setSettings({ ...settings, [key]: e.target.value })} />
        </Field>
      ))}
      {needsKey && (
        <Field label="Chave de API" htmlFor="provider-key"
          help="Vai direto para o worker do servidor e fica num arquivo que só ele lê. Nunca volta para o navegador.">
          <input id="provider-key" className="input" type="password" autoComplete="off" value={apiKey}
            onChange={(e) => setApiKey(e.target.value)} />
        </Field>
      )}
      {CLI_TYPES.has(type) && (
        <p className="small muted">Depois de criar, use “Entrar” no cartão da conexão: o login é feito pelo CLI oficial.</p>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      <button type="submit" className="btn btn-primary" disabled={busy}>
        <Icon name="plus" />
        {busy ? "Salvando…" : "Adicionar conexão"}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------- painel completo

export function ProviderManager({ onChange }: { onChange?: (o: ProvidersOverview) => void }) {
  const overview = useAsync(getProviders, []);
  const [adding, setAdding] = useState(false);
  const data = overview.data;

  useEffect(() => {
    if (data && onChange) onChange(data);
  }, [data, onChange]);

  if (overview.loading && !data) return <Loading />;
  return (
    <div className="stack">
      <ErrorNotice error={overview.error} onRetry={overview.reload} />
      {data && data.connections.length === 0 && (
        <Notice tone="info" title="Nenhuma IA conectada.">
          O motor financeiro, metas, projeções, Radar e diários funcionam sem IA. O Mentor e os especialistas precisam de
          uma conexão.
        </Notice>
      )}
      {data?.connections.map((c) => <ConnectionCard key={c.id} conn={c} onChange={() => void overview.reload()} />)}
      {data && (adding || data.connections.length === 0 ? (
        <NewConnection types={data.types} onSaved={() => { setAdding(false); void overview.reload(); }} />
      ) : (
        <button type="button" className="btn btn-secondary" onClick={() => setAdding(true)}>
          <Icon name="plus" />
          Adicionar outra conexão
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- provedor/modelo por agente

export function AgentModels({ only }: { only?: string[] }) {
  const overview = useAsync(getProviders, []);
  const [choices, setChoices] = useState<Record<string, AgentModelChoice>>({});
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const data = overview.data;

  useEffect(() => {
    if (data) setChoices(data.agent_models);
  }, [data]);

  const agents = useMemo(() => (data?.agents ?? []).filter((a) => !only || only.includes(a.id)), [data, only]);

  async function save() {
    setError(null);
    setSaved(false);
    try {
      const body = Object.fromEntries(agents.map((a) => [a.id, { connection: choices[a.id]?.connection ?? "",
        model: choices[a.id]?.model ?? "" }]));
      setChoices({ ...choices, ...(await putAgentModels(body)) });
      setSaved(true);
    } catch (err) {
      setError(message(err));
    }
  }

  if (overview.loading && !data) return <Loading />;
  if (!data) return <ErrorNotice error={overview.error} onRetry={overview.reload} />;
  const fallback = data.connections.find((c) => c.default)?.label ?? "nenhuma";
  return (
    <div className="stack-sm">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th scope="col">Agente</th><th scope="col">Conexão</th><th scope="col">Modelo</th></tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.id}>
                <th scope="row">{a.name}<div className="tiny muted">{a.title}</div></th>
                <td>
                  <select className="select" aria-label={`Conexão de ${a.name}`} value={choices[a.id]?.connection ?? ""}
                    onChange={(e) => setChoices({ ...choices, [a.id]: { connection: e.target.value, model: "" } })}>
                    <option value="">Padrão ({fallback})</option>
                    {data.connections.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                  </select>
                </td>
                <td>
                  <input className="input" aria-label={`Modelo de ${a.name}`} placeholder="padrão da conexão"
                    disabled={!choices[a.id]?.connection} value={choices[a.id]?.model ?? ""}
                    onChange={(e) => setChoices({ ...choices, [a.id]: { connection: choices[a.id]?.connection ?? "",
                      model: e.target.value } })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="tiny muted">
        Trocar o provedor de um agente não apaga histórico, memória, relatórios nem decisões: a próxima conversa recomeça
        no provedor novo com o contexto guardado no Lastro.
      </p>
      <div className="row">
        <button type="button" className="btn btn-primary btn-sm" onClick={() => void save()}>Salvar escolhas</button>
        {saved && <Badge tone="good">salvo</Badge>}
      </div>
      {error && <Notice tone="error">{error}</Notice>}
    </div>
  );
}
