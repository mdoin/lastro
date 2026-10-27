import { useNavigate } from "react-router-dom";
import { EXPORT_URL, getStatus, logout } from "../api/endpoints";
import { Icon } from "../components/Icon";
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

      {status.loading && !s && <Loading />}
      <ErrorNotice error={status.error} onRetry={status.reload} />

      {s && (
        <div className="grid-2">
          <Card title="Mentor" eyebrow="Assistente de IA">
            <dl className="kv small">
              <dt>Disponível</dt>
              <dd>{s.mentor.available ? <Badge tone="good">Sim</Badge> : <Badge tone="critical">Não</Badge>}</dd>
              <dt>Conectado à assinatura</dt>
              <dd>
                {s.mentor.logged_in === null ? (
                  <span className="muted">desconhecido</span>
                ) : s.mentor.logged_in ? (
                  <Badge tone="good">Sim</Badge>
                ) : (
                  <Badge tone="warning">Não</Badge>
                )}
              </dd>
              <dt>Assinatura</dt>
              <dd>{s.mentor.subscription ?? "—"}</dd>
              <dt>Turnos em andamento</dt>
              <dd>{s.mentor.busy}</dd>
              <dt>Na fila</dt>
              <dd>{s.mentor.queued}</dd>
              <dt>Limite da assinatura</dt>
              <dd>{s.mentor.limit_until ? `até ${formatDateTime(s.mentor.limit_until)}` : "livre"}</dd>
            </dl>
            {s.mentor.logged_in === false && (
              <p className="tiny muted" style={{ marginTop: 12 }}>
                A conexão com a assinatura é feita no servidor pelo administrador, nunca pela web.
              </p>
            )}
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
          A senha é definida apenas no servidor (<code className="tag">sudo lastro-admin set-password</code>). A sessão usa
          um cookie protegido, que o navegador não expõe a scripts.
        </p>
      </Card>
    </div>
  );
}
