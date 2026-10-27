// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { getAuthState, login } from "../api/endpoints";
import type { AuthState } from "../api/types";
import { BrandMark, Icon } from "../components/Icon";
import { Loading, Notice, SourceNotice } from "../components/ui";
import { safeNext } from "../lib/safeNext";

export function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [state, setState] = useState<AuthState | null>(null);
  const [stateError, setStateError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const next = safeNext(params.get("next"));

  useEffect(() => {
    getAuthState()
      .then((s) => {
        if (s.authenticated) navigate(next, { replace: true });
        else if (s.setup_required) navigate("/instalar", { replace: true });
        else setState(s);
      })
      .catch((e) => setStateError(e instanceof ApiError ? e.detail : "Servidor indisponível."));
  }, [navigate, next]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password) return;
    setBusy(true);
    setError(null);
    try {
      await login(password);
      setPassword("");
      navigate(next, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError("Senha incorreta.");
      else if (err instanceof ApiError && err.status === 429)
        setError(err.detail || "Muitas tentativas. Aguarde alguns minutos antes de tentar de novo.");
      else setError(err instanceof ApiError ? err.detail : "Não foi possível entrar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="login-card">
        <div className="login-brand reveal">
          <span className="app-icon" aria-hidden="true">
            <BrandMark tone="ivory" />
          </span>
          <div className="brand-word">Lastro</div>
          <p className="muted small">Seu mentor financeiro pessoal. Privado, no seu servidor.</p>
        </div>

        {stateError && <Notice tone="error">{stateError}</Notice>}
        {!state && !stateError && <Loading />}

        {state && !state.setup_required && (
          <form className="panel" onSubmit={submit} noValidate aria-labelledby="login-title">
            <div className="panel-head">
              <div>
                <div className="eyebrow">Acesso privado</div>
                <h2 id="login-title">Entrar</h2>
              </div>
              <Icon name="lock" style={{ width: 18, height: 18, color: "var(--muted)" }} />
            </div>
            <div className="panel-body stack">
              <div className="field">
                <label htmlFor="password">Senha</label>
                <input
                  id="password"
                  className="input"
                  type="password"
                  autoComplete="current-password"
                  autoFocus
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-invalid={error ? true : undefined}
                  aria-describedby={error ? "login-error" : undefined}
                  required
                />
              </div>
              {error && (
                <p id="login-error" className="error small" role="alert" style={{ color: "var(--critical-ink)" }}>
                  {error}
                </p>
              )}
              <button type="submit" className="btn btn-primary" disabled={busy || !password}>
                <Icon name="arrow" />
                {busy ? "Entrando…" : "Entrar"}
              </button>
            </div>
            <div className="panel-foot">
              <span>Sessão protegida por cookie que scripts não leem.</span>
            </div>
          </form>
        )}

        <p className="tiny muted" style={{ textAlign: "center" }}>
          O Lastro não movimenta dinheiro, não envia ordens e não pede senhas de banco.
        </p>
        {state && <SourceNotice url={state.source_url} license={state.license} />}
      </div>
    </div>
  );
}
