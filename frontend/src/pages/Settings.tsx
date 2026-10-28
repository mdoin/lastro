// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { EXPORT_URL, getAuthState, getProfile, getStatus, logout, putProfile } from "../api/endpoints";
import { Icon } from "../components/Icon";
import { AgentModels, ProviderManager } from "../components/Providers";
import { ThemeSwitch } from "../components/ThemeSwitch";
import { Badge, Card, ErrorNotice, Loading, PageHeader } from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDate, formatDateTime, relativeDays } from "../lib/dates";
import { useAsync } from "../lib/useAsync";

const NEVER = [
  "Não envia ordens de compra ou venda de investimentos.",
  "Não faz transferências, PIX, pagamentos ou resgates.",
  "Não pede, guarda ou usa senhas e credenciais de bancos ou corretoras.",
  "Não promete rentabilidade: simulações usam premissas que você controla.",
  "Não decide por você. Ele organiza, explica e simula; a decisão é sua.",
];

export function SettingsPage() {
  const app = useApp();
  const navigate = useNavigate();
  const status = useAsync(getStatus, []);
  const auth = useAsync(getAuthState, []);
  const s = status.data;

  async function doLogout() {
    try {
      await logout();
    } finally {
      navigate("/login", { replace: true });
    }
  }

  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Configurações e auditoria"
        title="Estado do sistema"
        lede="Transparência sobre o que está rodando, de quando são seus dados e o que o Lastro pode e não pode fazer."
        actions={
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { void status.reload(); void app.refresh(); }}>
            <Icon name="refresh" />
            Atualizar
          </button>
        }
      />

      <Card className="accent" title="O que o Lastro não faz" eyebrow="Compromisso permanente"
        aside={<Icon name="shieldCheck" style={{ width: 18, height: 18, color: "var(--gold-mark)" }} />}>
        <ul className="never-list">
          {NEVER.map((t) => (
            <li key={t}>
              <span className="never-icon" aria-hidden="true">
                <Icon name="ban" />
              </span>
              {t}
            </li>
          ))}
        </ul>
      </Card>

      <ProfileCard />

      {status.loading && !s && <Loading />}
      <ErrorNotice error={status.error} onRetry={status.reload} />

      {s && (
        <div className="grid-2">
          <Card title="Mentor" eyebrow="Assistente de IA">
            <dl className="kv small">
              <dt>Disponível</dt>
              <dd>{s.mentor.available ? <Badge tone="good">Sim</Badge> : <Badge tone="critical">Não</Badge>}</dd>
              <dt>Provedor padrão</dt>
              <dd>{s.mentor.connection ? s.mentor.connection.label : <Badge tone="warning">nenhum</Badge>}</dd>
              {s.mentor.connection?.type === "claude_code" && (
                <>
                  <dt>Login do Claude Code</dt>
                  <dd>
                    {s.mentor.logged_in === null ? <span className="muted">desconhecido</span>
                      : s.mentor.logged_in ? <Badge tone="good">{s.mentor.subscription ?? "Sim"}</Badge>
                      : <Badge tone="warning">Não</Badge>}
                  </dd>
                </>
              )}
              <dt>Turnos em andamento</dt>
              <dd>{s.mentor.busy}</dd>
              <dt>Na fila</dt>
              <dd>{s.mentor.queued}</dd>
              <dt>Limite do provedor</dt>
              <dd>{s.mentor.limit_until ? `até ${formatDateTime(s.mentor.limit_until)}` : "livre"}</dd>
            </dl>
          </Card>

          <Card title="Seus dados" eyebrow="Atualização">
            <dl className="kv small">
              <dt>Último retrato</dt>
              <dd>
                {s.data.latest_snapshot_as_of
                  ? `${formatDate(s.data.latest_snapshot_as_of)} (${relativeDays(s.data.latest_snapshot_as_of)})`
                  : "nenhum"}
              </dd>
              <dt>Situação</dt>
              <dd>
                {!s.data.latest_snapshot_as_of ? (
                  <Badge tone="warning">Sem dados</Badge>
                ) : s.data.stale ? (
                  <Badge tone="warning">Desatualizado</Badge>
                ) : (
                  <Badge tone="good">Em dia</Badge>
                )}
              </dd>
              <dt>Versão do app</dt>
              <dd>
                <span className="tag">{s.app_version}</span>
              </dd>
              <dt>Versão do motor financeiro</dt>
              <dd>
                <span className="tag">{s.engine_version}</span>
              </dd>
            </dl>
          </Card>
        </div>
      )}

      <Card title="Contas de IA" eyebrow="Provedores"
        footer={<span>Chaves e logins ficam só no servidor. Provedores externos recebem o contexto de cada pergunta.</span>}>
        <ProviderManager />
      </Card>

      <Card title="Modelo de cada agente" eyebrow="Equipe">
        <AgentModels />
      </Card>

      <Card title="Tema" eyebrow="Aparência"
        footer={<span>A escolha vale para este navegador. Automático segue o tema claro ou escuro do aparelho.</span>}>
        <ThemeSwitch />
      </Card>

      <Card title="Exportar meus dados" eyebrow="Portabilidade"
        footer={
          <>
            <span>Guarde o arquivo em local seguro: ele contém sua vida financeira.</span>
            <a className="btn btn-secondary btn-sm" href={EXPORT_URL} download>
              <Icon name="download" />
              Exportar (JSON)
            </a>
          </>
        }>
        <p className="small">
          Baixe um arquivo JSON com tudo o que está guardado: retratos, metas, premissas, decisões, rotinas e conversas.
        </p>
      </Card>

      <Card title="Código-fonte e licença" eyebrow="Software livre">
        <p className="small">
          O Lastro é software livre sob a GNU AGPL-3.0 (versão 3 ou posterior), sem nenhuma garantia. Você pode estudar,
          modificar e redistribuir o código; se oferecer uma versão modificada pela rede, o código dela precisa estar
          disponível para quem a usa. O nome e a marca seguem uma política própria.
        </p>
        {auth.data && (
          <a className="btn btn-secondary btn-sm" href={auth.data.source_url} target="_blank" rel="noopener noreferrer">
            <Icon name="arrowUpRight" />
            Ver o código-fonte
          </a>
        )}
      </Card>

      <Card title="Sessão" eyebrow="Segurança"
        footer={
          <>
            <span>Encerra a sessão só neste navegador.</span>
            <button type="button" className="btn btn-danger btn-sm" onClick={() => void doLogout()}>
              <Icon name="logout" />
              Sair deste aparelho
            </button>
          </>
        }>
        <p className="small">
          A senha do Lastro é independente das contas de IA. Para trocá-la, use o servidor
          (<code className="tag">lastro-admin set-password</code>). A sessão usa
          um cookie protegido, que o navegador não expõe a scripts.
        </p>
      </Card>
    </div>
  );
}

/** Como a equipe chama a pessoa. Os agentes leem daqui a cada resposta; nada é deduzido de documentos. */
function ProfileCard() {
  const app = useApp();
  const profile = useAsync(getProfile, []);
  const [form, setForm] = useState({ nome: "", apelido: "", tratamento: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (profile.data) setForm({ nome: profile.data.nome, apelido: profile.data.apelido, tratamento: profile.data.tratamento });
  }, [profile.data]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      profile.setData(await putProfile(form));
      app.toast("Pronto: a equipe já usa o novo jeito de chamar você.");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível salvar.");
    } finally {
      setSaving(false);
    }
  }

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <Card title="Como a equipe chama você" eyebrow="Seu perfil">
      <div className="stack">
      <p className="small muted">Bento, Lia, Caio e os demais usam isto em todas as conversas, individuais e em grupo. Nenhum nome é tirado de extratos ou documentos.</p>
      <ErrorNotice error={profile.error} onRetry={profile.reload} />
      <form className="stack" onSubmit={(e) => void save(e)}>
        <div className="form-grid">
          <label className="field">
            <span className="field-label">Como a equipe deve chamar você</span>
            <input className="input" value={form.nome} maxLength={60} onChange={set("nome")} placeholder="Ex.: Ana" autoComplete="given-name" />
          </label>
          <label className="field">
            <span className="field-label">Apelido (opcional)</span>
            <input className="input" value={form.apelido} maxLength={40} onChange={set("apelido")} autoComplete="nickname" />
          </label>
        </div>
        <label className="field">
          <span className="field-label">Preferências de tratamento (opcional)</span>
          <input className="input" value={form.tratamento} maxLength={240} onChange={set("tratamento")}
            placeholder="Ex.: pode ser informal; prefiro linguagem neutra" />
        </label>
        {error && <p className="small" role="alert">{error}</p>}
        <div className="row"><button type="submit" className="btn btn-primary btn-sm" disabled={saving || !profile.data}>Salvar</button></div>
      </form>
      </div>
    </Card>
  );
}
