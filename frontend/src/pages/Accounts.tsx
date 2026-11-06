// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Contas e acessos (docs/CONTAS.md): pendências que os agentes abriram e o estado de cada plataforma.
 * Compartilhada por Finanças e Carreira. Senhas vão direto ao backend (que repassa ao cofre cifrado do worker);
 * a página nunca recebe senha, token ou cookie, e nada disso fica no navegador depois do envio.
 */
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  disconnectAccount, getAccounts, resolvePending, revokeCredential, saveCredential, verifyAccount,
  type AccountState, type AuthKind, type Pending, type Platform,
} from "../api/contas";
import { Icon } from "../components/Icon";
import { Badge, Card, EmptyState, ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDateTime } from "../lib/dates";
import type { Tone } from "../lib/labels";
import { useAsync } from "../lib/useAsync";
import "../styles/crypto.css";

const STATE: Record<AccountState, { label: string; tone: Tone }> = {
  conectada: { label: "Conectada", tone: "good" },
  nao_configurada: { label: "Não configurada", tone: "neutral" },
  sessao_expirada: { label: "Sessão expirada", tone: "warning" },
  aguardando_autenticacao: { label: "Aguardando autenticação", tone: "warning" },
  requer_verificacao: { label: "Requer verificação", tone: "serious" },
  erro: { label: "Erro", tone: "critical" },
};
const AUTH: Record<AuthKind, string> = {
  oauth: "Integração oficial (OAuth)", sessao: "Login seu no navegador do agente", senha: "Senha no cofre", env: "Configurada no servidor",
};
const KIND: Record<Pending["tipo"], string> = {
  login: "Login necessário", cadastro: "Cadastro necessário", sessao_expirada: "Sessão expirada",
  verificacao_identidade: "Verificação de identidade", dois_fatores: "Autenticação em duas etapas",
  confirmacao_email: "Confirmação por e-mail", informacao_ausente: "Informação ausente",
};
const AGENT: Record<string, string> = { aplicador: "Aplicador (Carreira)", carteiro: "Carteiro (Carreira)" };
const ACCESS = new Set<Pending["tipo"]>(["login", "cadastro", "sessao_expirada", "verificacao_identidade", "dois_fatores", "confirmacao_email"]);

const fail = (e: unknown) => (e instanceof ApiError ? e.detail : "Não foi possível concluir.");
const browserLink = (url: string) => `/carreira/navegador?abrir=${encodeURIComponent(url)}`;

type Sensitive = { id: string; mode: "credencial" | "revogar" | "desconectar" };

export function AccountsPage() {
  const q = useAsync(getAccounts, []);
  const { refresh } = useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [sensitive, setSensitive] = useState<Sensitive | null>(null);

  const act = async (key: string, fn: () => Promise<unknown>, ok: (r: unknown) => string) => {
    setBusy(key);
    setMessage(null);
    try {
      const r = await fn();
      setMessage({ tone: "success", text: ok(r) });
      await q.reload();
      void refresh();
    } catch (e) {
      setMessage({ tone: "error", text: fail(e) });
    } finally {
      setBusy(null);
    }
  };
  const resumed = (r: unknown) => {
    const n = (r as { retomadas?: number })?.retomadas ?? 0;
    return n ? `${n} candidatura(s) voltaram para a fila e serão retomadas em instantes.` : "Pronto.";
  };

  const open = (q.data?.pendencias ?? []).filter((p) => p.estado === "aberta");
  const closed = (q.data?.pendencias ?? []).filter((p) => p.estado !== "aberta");
  const platforms = q.data?.plataformas ?? [];
  const byId = new Map(platforms.map((p) => [p.id, p]));

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Configurações" title="Contas e acessos"
        lede="Plataformas que os agentes usam e o que eles precisam de você. Senhas ficam cifradas no servidor; nenhum agente nem a IA as lê."
        actions={<button type="button" className="btn btn-ghost btn-sm" onClick={() => void q.reload()}><Icon name="refresh" />Atualizar</button>} />
      {q.loading && !q.data && <Loading />}
      <ErrorNotice error={q.error} onRetry={q.reload} />
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      {q.data?.cofre.disponivel === false && (
        <Notice tone="warning">O cofre está indisponível: a chave do cofre não foi instalada no servidor. Logins pelo navegador continuam funcionando.</Notice>
      )}
      {q.data && q.data.cofre.disponivel === null && <Notice tone="warning">O worker não respondeu: o estado das senhas no cofre não pôde ser lido.</Notice>}

      {q.data && (
        <Card title="Pendências" eyebrow={open.length ? `${open.length} aguardando você` : "Central"}>
          {!open.length && <EmptyState title="Nenhuma pendência" icon="check">Quando um agente precisar de login, cadastro ou verificação, o pedido aparece aqui e as outras tarefas continuam.</EmptyState>}
          <ul className="notif-list">
            {open.map((p) => {
              const plat = byId.get(p.plataforma);
              return (
                <li key={p.id} className="notif" data-status="novo">
                  <span className="notif-icon" aria-hidden="true"><Icon name={ACCESS.has(p.tipo) ? "lock" : "info"} /></span>
                  <div className="notif-main">
                    <p className="notif-title"><strong>{p.plataforma_nome}</strong> <Badge tone="warning">{KIND[p.tipo]}</Badge></p>
                    <p className="small">{p.motivo}</p>
                    <p className="small"><strong>O que fazer:</strong> {p.acao}</p>
                    {p.tarefas.length > 0 && (
                      <p className="small">Em espera: {p.tarefas.map((t, i) => (
                        <span key={t.n}>{i > 0 && ", "}<Link to={`/carreira/candidaturas/${t.n}`}>#{t.n} {t.title}</Link></span>))}
                      </p>
                    )}
                    <p className="tiny muted">Pedido por {AGENT[p.agente] ?? p.agente} · {formatDateTime(p.created_at)}</p>
                  </div>
                  <div className="notif-actions">
                    {ACCESS.has(p.tipo) && p.url_oficial && (
                      <Link className="btn btn-secondary btn-sm" to={browserLink(p.url_oficial)}><Icon name="globe" />Abrir navegador</Link>
                    )}
                    {ACCESS.has(p.tipo) && plat?.url_verificacao && (
                      <button type="button" className="btn btn-primary btn-sm" disabled={busy !== null}
                        onClick={() => void act(`p${p.id}`, () => resolvePending(p.id, "verificar"), resumed)}>
                        {busy === `p${p.id}` ? "Verificando…" : "Já entrei — verificar"}
                      </button>
                    )}
                    <button type="button" className="btn btn-ghost btn-sm" disabled={busy !== null}
                      onClick={() => void act(`c${p.id}`, () => resolvePending(p.id, "concluir"), resumed)}>Marcar como resolvida</button>
                    <button type="button" className="btn btn-ghost btn-sm" disabled={busy !== null}
                      onClick={() => { if (window.confirm("Descartar? As candidaturas presas nesta pendência serão encerradas.")) void act(`d${p.id}`, () => resolvePending(p.id, "descartar"), () => "Pendência descartada."); }}>
                      Descartar
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
          {closed.length > 0 && (
            <details className="small">
              <summary>Resolvidas nos últimos 7 dias ({closed.length})</summary>
              <ul>{closed.map((p) => <li key={p.id}>{p.plataforma_nome} · {KIND[p.tipo]} · {p.estado} {p.resolved_at && `em ${formatDateTime(p.resolved_at)}`} {p.resolucao && `(${p.resolucao})`}</li>)}</ul>
            </details>
          )}
        </Card>
      )}

      {q.data && (
        <div className="grid-2">
          {platforms.map((p) => (
            <PlatformCard key={p.id} p={p} busy={busy} vaultReady={q.data?.cofre.disponivel === true}
              sensitive={sensitive?.id === p.id ? sensitive.mode : null} setSensitive={(mode) => setSensitive(mode ? { id: p.id, mode } : null)}
              onVerify={() => void act(`v${p.id}`, () => verifyAccount(p.id), (r) => {
                const est = (r as { estado: AccountState }).estado;
                return est === "conectada" ? `${p.nome}: sessão ativa. ${resumed(r)}` : `${p.nome}: ${STATE[est].label.toLowerCase()}. Entre pelo navegador do agente e verifique de novo.`;
              })}
              onSensitive={(mode, body) => act(`s${p.id}`,
                () => mode === "credencial" ? saveCredential(p.id, body as { usuario: string; senha: string; senha_dono: string })
                  : mode === "revogar" ? revokeCredential(p.id, body.senha_dono) : disconnectAccount(p.id, body.senha_dono),
                () => { setSensitive(null); return mode === "credencial" ? "Credencial guardada no cofre." : mode === "revogar" ? "Senha removida do cofre." : `${p.nome} desconectada.`; })} />
          ))}
        </div>
      )}
    </div>
  );
}

export function PlatformCard({ p, busy, vaultReady, sensitive, setSensitive, onVerify, onSensitive }: {
  p: Platform; busy: string | null; vaultReady: boolean; sensitive: Sensitive["mode"] | null;
  setSensitive: (mode: Sensitive["mode"] | null) => void; onVerify: () => void;
  onSensitive: (mode: Sensitive["mode"], body: { usuario?: string; senha?: string; senha_dono: string }) => Promise<void>;
}) {
  const state = STATE[p.estado];
  const env = p.autenticacao === "env";
  const perms = [
    ...(p.autenticacao === "sessao" ? ["usar a sessão aberta no navegador do agente"] : []),
    ...(p.tem_credencial ? [`digitar a senha do cofre só em ${(p.credencial?.dominios ?? p.dominios).join(", ")}`] : []),
    ...(env ? ["usar a configuração do servidor"] : []),
  ];
  return (
    <Card title={p.nome} eyebrow={p.modulo === "sistema" ? "Sistema" : p.modulo === "financas" ? "Finanças" : "Carreira"}
      aside={<Badge tone={state.tone}>{state.label}</Badge>}>
      <dl className="kv small">
        <dt>Endereço oficial</dt>
        <dd>{p.url_oficial ? <a href={p.url_oficial} target="_blank" rel="noopener noreferrer">{new URL(p.url_oficial).host}</a> : <span className="muted">não verificado</span>}</dd>
        <dt>Autenticação</dt><dd>{AUTH[p.autenticacao]}{p.tem_credencial && p.autenticacao !== "senha" ? " + senha no cofre" : ""}</dd>
        <dt>Última autenticação</dt><dd>{p.ultima_autenticacao ? formatDateTime(p.ultima_autenticacao) : "—"}</dd>
        <dt>Última verificação</dt><dd>{p.ultima_verificacao ? formatDateTime(p.ultima_verificacao) : "—"}</dd>
        <dt>Agentes autorizados</dt><dd>{p.agentes.length ? p.agentes.map((a) => AGENT[a] ?? a).join(", ") : "nenhum"}</dd>
        <dt>Permissões</dt><dd>{perms.length ? perms.join("; ") : "nenhuma"}</dd>
      </dl>
      <div className="row" style={{ marginTop: 12 }}>
        {!env && p.url_oficial && (
          <Link className="btn btn-secondary btn-sm" to={browserLink(p.url_oficial)}>
            <Icon name="globe" />{p.estado === "conectada" ? "Abrir navegador" : p.ultima_autenticacao ? "Reconectar" : "Conectar"}
          </Link>
        )}
        {p.url_verificacao && (
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy !== null} onClick={onVerify}>
            {busy === `v${p.id}` ? "Verificando…" : "Verificar sessão"}
          </button>
        )}
        {!env && vaultReady && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSensitive("credencial")}>{p.tem_credencial ? "Atualizar credenciais" : "Guardar senha"}</button>}
        {p.tem_credencial && vaultReady && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSensitive("revogar")}>Revogar acesso</button>}
        {!env && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSensitive("desconectar")}>Desconectar</button>}
      </div>
      {sensitive && <SensitiveForm mode={sensitive} p={p} busy={busy === `s${p.id}`} onCancel={() => setSensitive(null)} onSubmit={(body) => onSensitive(sensitive, body)} />}
      <details className="small" style={{ marginTop: 8 }}>
        <summary>Ver detalhes</summary>
        <dl className="kv small">
          <dt>Domínios</dt><dd>{p.dominios.join(", ") || "—"}</dd>
          <dt>Página de verificação</dt><dd>{p.url_verificacao || "—"}</dd>
          {p.credencial && <><dt>Usuário no cofre</dt><dd>{p.credencial.usuario_dica || "—"}</dd><dt>Senha atualizada</dt><dd>{p.credencial.atualizado_em ? formatDateTime(p.credencial.atualizado_em) : "—"}</dd></>}
          {p.detalhe && <><dt>Detalhe</dt><dd>{p.detalhe}</dd></>}
          {env && <><dt>Como mudar</dt><dd>No servidor (docs/CONTAS.md, seção migração do .env).</dd></>}
        </dl>
      </details>
    </Card>
  );
}

function SensitiveForm({ mode, p, busy, onCancel, onSubmit }: {
  mode: Sensitive["mode"]; p: Platform; busy: boolean; onCancel: () => void;
  onSubmit: (body: { usuario?: string; senha?: string; senha_dono: string }) => Promise<void>;
}) {
  // Só em memória, enquanto o formulário está aberto; limpo ao enviar. Nunca em localStorage/sessionStorage.
  const [usuario, setUsuario] = useState("");
  const [senha, setSenha] = useState("");
  const [dono, setDono] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body = mode === "credencial" ? { usuario, senha, senha_dono: dono } : { senha_dono: dono };
    setSenha("");
    setDono("");
    await onSubmit(body);
  };
  const id = `acc-${p.id}`;
  return (
    <form className="stack-sm" style={{ marginTop: 12 }} onSubmit={(e) => void submit(e)} autoComplete="off">
      {mode === "credencial" && (
        <>
          <p className="small muted">A senha vai direto ao cofre cifrado do servidor e só é digitada em {p.dominios.join(", ")}. Prefira o login pelo navegador do agente quando der.</p>
          <Field label={`Usuário ou e-mail na ${p.nome}`} htmlFor={`${id}-u`}>
            <input id={`${id}-u`} className="input" value={usuario} maxLength={254} autoComplete="off" spellCheck={false} onChange={(e) => setUsuario(e.target.value)} />
          </Field>
          <Field label={`Senha na ${p.nome}`} htmlFor={`${id}-s`}>
            <input id={`${id}-s`} className="input" type="password" value={senha} maxLength={512} required autoComplete="new-password" onChange={(e) => setSenha(e.target.value)} />
          </Field>
        </>
      )}
      {mode === "revogar" && <p className="small">Remove a senha da {p.nome} do cofre. Uma sessão aberta no navegador do agente continua; use Desconectar para encerrá-la.</p>}
      {mode === "desconectar" && <p className="small">Apaga os cookies da {p.nome} no navegador do agente e remove a senha do cofre. Os agentes deixam de usar esta conta.</p>}
      <Field label="Sua senha do Lastro (confirmação)" htmlFor={`${id}-d`}>
        <input id={`${id}-d`} className="input" type="password" value={dono} maxLength={256} required autoComplete="current-password" onChange={(e) => setDono(e.target.value)} />
      </Field>
      <div className="row">
        <button type="submit" className={`btn btn-sm ${mode === "credencial" ? "btn-primary" : "btn-danger"}`} disabled={busy}>
          {busy ? "Enviando…" : mode === "credencial" ? "Guardar no cofre" : mode === "revogar" ? "Revogar" : "Desconectar"}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancelar</button>
      </div>
    </form>
  );
}
