// SPDX-License-Identifier: AGPL-3.0-or-later
/** Confirmação discreta do que o Lastro reconheceu numa mensagem: desfazer o que foi registrado, completar só o
 * que falta e confirmar ou descartar pendências. Decisões vão para o Diário (a pessoa confirma lá). */
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { captureAction, type Capture } from "../api/ledger";
import { maybeMask } from "../lib/privacy";
import { Icon } from "./Icon";
import "../styles/inbox.css";

export function CaptureNotice({ captures, masked = false }: { captures: Capture[]; masked?: boolean }) {
  const [state, setState] = useState<Record<string, Capture["status"]>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  async function act(c: Capture, action: "desfazer" | "confirmar" | "descartar") {
    setError(null);
    try {
      const amount = values[c.id];
      const out = await captureAction(c.id, action, amount ? { amount } : {});
      setState((s) => ({ ...s, [c.id]: out.status }));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Não foi possível concluir.");
    }
  }

  return (
    <div className="capture-notice" role="note" aria-label="Registros reconhecidos na sua mensagem">
      <ul>
        {captures.map((c) => {
          const status = state[c.id] ?? c.status;
          return (
            <li key={c.id}>
              <Icon name={status === "registrado" ? "check" : status === "pendente" ? "info" : "x"} />
              <span>
                {status === "registrado" ? "Registrado: " : status === "pendente" ? "Para revisar: " : status === "desfeito" ? "Desfeito: " : "Descartado: "}
                {maybeMask(c.label, masked)}
                {c.date_assumed && status !== "desfeito" && <span className="tiny muted"> (data da mensagem)</span>}
                {status === "pendente" && c.missing.length > 0 && <span className="tiny muted"> — falta: {c.missing.join(", ")}</span>}
              </span>
              {status === "registrado" && <button type="button" className="btn btn-ghost btn-sm" onClick={() => void act(c, "desfazer")}>Desfazer</button>}
              {status === "pendente" && c.target_kind === "diario" && <Link className="btn btn-ghost btn-sm" to="/diario">Registrar no Diário</Link>}
              {status === "pendente" && c.target_kind !== "diario" && (
                <>
                  {c.missing.includes("valor") && (
                    <>
                      <label className="visually-hidden" htmlFor={`cap-${c.id}`}>Valor</label>
                      <input id={`cap-${c.id}`} className="input" inputMode="decimal" placeholder="valor (ex.: 120,50)"
                        value={values[c.id] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [c.id]: e.target.value }))} />
                    </>
                  )}
                  <button type="button" className="btn btn-primary btn-sm" onClick={() => void act(c, "confirmar")}>Confirmar</button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => void act(c, "descartar")}>Descartar</button>
                </>
              )}
            </li>
          );
        })}
      </ul>
      {error && <p className="tiny" role="alert">{error}</p>}
      <p className="tiny muted">Tudo fica na <Link to="/caixa">Caixa de entrada</Link>, com a origem de cada registro. Seus retratos financeiros não mudam.</p>
    </div>
  );
}
