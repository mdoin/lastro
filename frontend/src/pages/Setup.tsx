/**
 * Assistente inicial: boas-vindas → conta administrativa (token de instalação) → região → provedor de IA (conexão,
 * login autorizado, teste e modelo) → Mentor → diagnóstico → painel. Sem IA, o que é determinístico já funciona.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { completeSetup, getAuthState, getSetupState, getStatus, setupPassword } from "../api/endpoints";
import type { AuthState, ProvidersOverview, SetupState } from "../api/types";
import { BrandMark, Icon } from "../components/Icon";
import { AgentModels, ProviderManager } from "../components/Providers";
import { Badge, Field, Loading, Notice } from "../components/ui";
import { useAsync } from "../lib/useAsync";

const STEPS = ["Boas-vindas", "Conta", "Região", "Provedor de IA", "Mentor", "Diagnóstico", "Pronto"] as const;
const WITHOUT_AI = ["Retratos financeiros e diagnóstico", "Metas e projeções", "Simulações", "Motor do Radar",
  "Diário de Oportunidades", "Diário de Decisões", "Histórico e auditoria matemática"];
const WITH_AI = ["Mentor e especialistas", "Conselho multiagente", "Pareceres do Radar", "Rotinas com análise"];

function PasswordStep({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError("As senhas não conferem.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await setupPassword(token.trim(), password);
      setPassword("");
      setConfirm("");
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível criar a conta.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit} noValidate>
      <p className="small">
        Esta é a conta de quem administra esta instalação. Para provar que é você, use o <strong>token de instalação</strong>,
        que só existe no servidor:
      </p>
      <pre className="card sunken mono" style={{ margin: 0, padding: "12px 14px", overflowX: "auto" }}>
        docker compose exec web cat /data/setup-token
      </pre>
      <Field label="Token de instalação" htmlFor="setup-token">
        <input id="setup-token" className="input mono" autoComplete="off" spellCheck={false} value={token}
          onChange={(e) => setToken(e.target.value)} />
      </Field>
      <Field label="Senha (mínimo 12 caracteres)" htmlFor="setup-password">
        <input id="setup-password" className="input" type="password" autoComplete="new-password" value={password}
          onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <Field label="Repita a senha" htmlFor="setup-confirm">
        <input id="setup-confirm" className="input" type="password" autoComplete="new-password" value={confirm}
          onChange={(e) => setConfirm(e.target.value)} />
      </Field>
      {error && <Notice tone="error">{error}</Notice>}
      <button type="submit" className="btn btn-primary" disabled={busy || !token || password.length < 12}>
        <Icon name="lock" />
        {busy ? "Criando…" : "Criar conta administrativa"}
      </button>
    </form>
  );
}

function DiagnosisStep() {
  const status = useAsync(getStatus, []);
  const s = status.data;
  if (!s) return <Loading label="Conferindo a instalação…" />;
  const rows: [string, boolean, string][] = [
    ["Servidor do Lastro", true, `versão ${s.app_version}, motor ${s.engine_version}`],
    ["Worker dos agentes", s.mentor.available, s.mentor.available ? "respondendo" : "sem resposta"],
    ["IA conectada", !!s.mentor.ai_configured, s.mentor.connection?.label ?? "nenhuma (funções sem IA continuam)"],
    ["Retrato financeiro", !!s.data.latest_snapshot_as_of, s.data.latest_snapshot_as_of ? "registrado" : "ainda não"],
  ];
  return (
    <div className="stack">
      <dl className="kv small">
        {rows.map(([label, ok, detail]) => (
          <div key={label} style={{ display: "contents" }}>
            <dt>{label}</dt>
            <dd>{ok ? <Badge tone="good">ok</Badge> : <Badge tone="warning">pendente</Badge>} <span className="muted">{detail}</span></dd>
          </div>
        ))}
      </dl>
      {!s.data.latest_snapshot_as_of && (
        <Notice tone="info" title="Próximo passo:">
          registre seu primeiro retrato financeiro em <Link to="/vida-financeira">Minha vida financeira</Link> (use
          valores aproximados; dá para corrigir depois). O diagnóstico é calculado pelo motor, sem IA.
        </Notice>
      )}
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => void status.reload()}>
        <Icon name="refresh" />
        Conferir de novo
      </button>
    </div>
  );
}

export function SetupPage() {
  const navigate = useNavigate();
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [region, setRegion] = useState<SetupState | null>(null);
  const [step, setStep] = useState(0);
  const [ai, setAi] = useState<ProvidersOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshAuth = useCallback(() => {
    getAuthState().then(setAuth).catch(() => setError("Servidor indisponível."));
  }, []);
  useEffect(refreshAuth, [refreshAuth]);
  useEffect(() => {
    if (auth?.authenticated && !region) getSetupState().then(setRegion).catch(() => undefined);
  }, [auth, region]);
  const onProviders = useCallback((o: ProvidersOverview) => setAi(o), []);

  if (error) return <div className="login"><div className="login-card"><Notice tone="error">{error}</Notice></div></div>;
  if (!auth) return <div className="login"><Loading /></div>;
  if (!auth.setup_required && !auth.authenticated) return <Navigate to="/login?next=%2Finstalar" replace />;
  if (auth.authenticated && auth.onboarding_done && step === 0) return <Navigate to="/" replace />;

  const hasAi = !!ai?.connections.some((c) => c.configured);
  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const canAdvance = step !== 1 || auth.authenticated;

  async function finish() {
    await completeSetup();
    navigate("/", { replace: true });
  }

  return (
    <div className="login">
      <div className="login-card setup-card">
        <div className="login-brand reveal">
          <span className="app-icon" aria-hidden="true">
            <BrandMark tone="ivory" />
          </span>
          <div className="brand-word">Lastro</div>
          <p className="muted small">Configuração inicial desta instalação.</p>
        </div>
        <ol className="setup-steps" aria-label="Etapas">
          {STEPS.map((label, i) => (
            <li key={label} aria-current={i === step ? "step" : undefined}>{i + 1}. {label}</li>
          ))}
        </ol>

        <section className="panel" aria-labelledby="setup-step-title">
          <div className="panel-head">
            <div>
              <div className="eyebrow">Etapa {step + 1} de {STEPS.length}</div>
              <h2 id="setup-step-title">{STEPS[step]}</h2>
            </div>
          </div>
          <div className="panel-body stack">
            {step === 0 && (
              <>
                <p>
                  O Lastro organiza sua vida financeira, calcula com um motor verificável e usa agentes de IA para explicar
                  e coordenar análises. Tudo roda nesta instalação, com os seus dados e as suas credenciais.
                </p>
                <div className="grid-2">
                  <div className="card stack-sm">
                    <strong>Funciona sem IA</strong>
                    <ul className="small">{WITHOUT_AI.map((t) => <li key={t}>{t}</li>)}</ul>
                  </div>
                  <div className="card stack-sm">
                    <strong>Depende de um modelo de IA</strong>
                    <ul className="small">{WITH_AI.map((t) => <li key={t}>{t}</li>)}</ul>
                  </div>
                </div>
                <Notice tone="info">
                  Quando você usa um provedor externo, ele recebe o contexto necessário para responder (por exemplo, o seu
                  retrato financeiro numa pergunta sobre reserva). Com um modelo local, nada sai da sua máquina.
                </Notice>
              </>
            )}
            {step === 1 && (auth.authenticated
              ? <Notice tone="success">Conta administrativa criada e sessão aberta.</Notice>
              : <PasswordStep onDone={refreshAuth} />)}
            {step === 2 && (
              <dl className="kv small">
                <dt>Idioma</dt><dd>Português (Brasil)</dd>
                <dt>Moeda</dt><dd>Real (BRL): o motor financeiro, os impostos e as fontes de dados são brasileiros</dd>
                <dt>Fuso horário</dt><dd>{region?.timezone ?? "…"} <span className="muted">(altere em <code className="tag">LASTRO_TZ</code> no .env)</span></dd>
              </dl>
            )}
            {step === 3 && (
              <>
                <p className="small">
                  Conecte pelo menos um provedor e use <strong>Testar conexão</strong> antes de continuar. Chaves e logins
                  ficam só no servidor; o navegador nunca recebe o segredo de volta.
                </p>
                <ProviderManager onChange={onProviders} />
              </>
            )}
            {step === 4 && (
              <>
                <p className="small">
                  Escolha qual conexão e qual modelo o Mentor usa. Os especialistas seguem a conexão padrão até você
                  mudar em Configurações.
                </p>
                <AgentModels only={["mentor"]} />
              </>
            )}
            {step === 5 && <DiagnosisStep />}
            {step === 6 && (
              <p>
                Pronto. No painel você acompanha seus dados; em <strong>Configurações</strong> dá para conectar outros
                provedores, escolher um modelo por agente e desconectar contas a qualquer momento.
              </p>
            )}
          </div>
          <div className="panel-foot">
            {step > 0 ? (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setStep(step - 1)}>Voltar</button>
            ) : <span />}
            {step < STEPS.length - 1 ? (
              <button type="button" className="btn btn-primary btn-sm" disabled={!canAdvance} onClick={next}>
                {step === 3 && !hasAi ? "Continuar sem IA" : "Continuar"}
                <Icon name="arrow" />
              </button>
            ) : (
              <button type="button" className="btn btn-primary btn-sm" onClick={() => void finish()}>
                Ir para o painel
                <Icon name="arrow" />
              </button>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
