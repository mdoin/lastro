// SPDX-License-Identifier: AGPL-3.0-or-later
/** Computadores dos agentes: cada agente tem o seu (tela, Chrome, terminal e arquivos). O dono vê ao vivo e pode
 * assumir o controle; enquanto isso o agente espera. A mesma tela aparece na conversa quando o agente pesquisa. */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { desligarComputador, getComputadores, type Computador, type Computadores } from "../api/computadores";
import { AgentAvatar } from "../components/AgentAvatar";
import { ComputerScreen, of } from "../components/ComputerScreen";
import { Icon } from "../components/Icon";
import { ErrorNotice, Loading, PageHeader } from "../components/ui";
import "../styles/computadores.css";

const POLL_MS = 5000;
const fail = (e: unknown) => ({ detail: e instanceof ApiError ? e.detail : "Não consegui falar com os computadores." });

function status(c: Computador) {
  if (!c.ligado) return "Desligado";
  if (c.controle === "dono") return "Você no controle";
  return c.agente_ativo ? "Usando agora" : "Ligado";
}

export function ComputadoresPage() {
  const [data, setData] = useState<Computadores | null>(null);
  const [error, setError] = useState<{ detail: string } | null>(null);
  const [open, setOpen] = useState<Computador | null>(null);

  const load = useCallback(() => getComputadores().then((d) => { setData(d); setError(null); }, (e) => setError(fail(e))), []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void load(); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  return (
    <>
      <PageHeader eyebrow="Sistema" title="Computadores dos agentes"
        lede={<>Cada agente tem o próprio computador, com navegador, terminal e arquivos, para pesquisar. Nenhum dado
          seu fica neles. Até {data?.limite ?? 3} ficam ligados ao mesmo tempo; os parados desligam sozinhos.</>} />
      <ErrorNotice error={error} onRetry={() => void load()} />
      {!data && !error && <Loading />}
      {data && (
        <ul className="pc-grid">
          {data.agentes.map((c) => (
            <li key={c.id}>
              <button type="button" className={`pc-card ${c.ligado ? "is-on" : ""}`} onClick={() => setOpen(c)}>
                <AgentAvatar id={c.id} size={40} state={c.agente_ativo ? "thinking" : "idle"} />
                <span className="pc-card-text">
                  <strong>Computador {of(c.nome)} {c.nome}</strong>
                  <span>{c.titulo}</span>
                </span>
                <span className={`pc-dot ${c.ligado ? "is-on" : ""}`}>{status(c)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && <Screen pc={open} onClose={() => { setOpen(null); void load(); }} />}
    </>
  );
}

function Screen({ pc, onClose }: { pc: Computador; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [error, setError] = useState<{ detail: string } | null>(null);
  const [full, setFull] = useState(false);
  const title = `Computador ${of(pc.nome)} ${pc.nome}`;

  useEffect(() => { dialog.current?.showModal(); }, []);
  const turnOff = async () => {
    try { await desligarComputador(pc.id); onClose(); } catch (e) { setError(fail(e)); }
  };

  return (
    <dialog ref={dialog} className={`pc-dialog ${full ? "is-full" : ""}`} onCancel={(e) => { e.preventDefault(); onClose(); }}
      aria-label={title}>
      <header className="pc-head">
        <AgentAvatar id={pc.id} size={36} />
        <div className="pc-head-text"><strong>{title}</strong><span>{pc.titulo}</span></div>
        <div className="pc-head-actions">
          <button type="button" className="btn btn-ghost" onClick={() => void turnOff()} title="Desligar o computador">
            <Icon name="stop" /><span className="visually-hidden">Desligar</span>
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => setFull(!full)} title={full ? "Reduzir" : "Tela cheia"}>
            <Icon name="panel" /><span className="visually-hidden">{full ? "Reduzir" : "Tela cheia"}</span>
          </button>
          <button type="button" className="btn btn-ghost" onClick={onClose} title="Fechar">
            <Icon name="x" /><span className="visually-hidden">Fechar</span>
          </button>
        </div>
      </header>
      <ErrorNotice error={error} />
      <ComputerScreen id={pc.id} nome={pc.nome} />
    </dialog>
  );
}
