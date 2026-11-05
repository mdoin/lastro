// SPDX-License-Identifier: AGPL-3.0-or-later
/** Computadores dos agentes: cada agente tem o seu (tela, Chrome, terminal e arquivos). O dono vê ao vivo e pode
 * assumir o controle; enquanto isso o agente espera. */
import { useCallback, useEffect, useRef, useState } from "react";
import RFB from "@novnc/novnc";
import { ApiError } from "../api/client";
import {
  controlarComputador, desligarComputador, getComputadores, ligarComputador, telaUrl, type Computador, type Computadores,
} from "../api/computadores";
import { AgentAvatar } from "../components/AgentAvatar";
import { Icon } from "../components/Icon";
import { ErrorNotice, Loading, PageHeader } from "../components/ui";
import "../styles/computadores.css";

const POLL_MS = 5000;
// Concordância do "do/da" com o nome do agente.
const FEMININE = new Set(["Mila", "Lia", "Vera", "Nina", "Cora"]);
const of = (nome: string) => (FEMININE.has(nome) ? "da" : "do");
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
      {open && data && (
        <Screen pc={data.agentes.find((a) => a.id === open.id) ?? open} ip={data.ip_saida}
          onClose={() => { setOpen(null); void load(); }} onChange={() => void load()} />
      )}
    </>
  );
}

function Screen({ pc, ip, onClose, onChange }: { pc: Computador; ip: string; onClose: () => void; onChange: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const target = useRef<HTMLDivElement>(null);
  const rfb = useRef<RFB | null>(null);
  const [state, setState] = useState<"ligando" | "conectado" | "caiu">("ligando");
  const [error, setError] = useState<{ detail: string } | null>(null);
  const [full, setFull] = useState(false);
  const dono = pc.controle === "dono";

  useEffect(() => { dialog.current?.showModal(); }, []);

  useEffect(() => {
    let cancelled = false;
    ligarComputador(pc.id).then(() => {
      if (cancelled || !target.current) return;
      const client = new RFB(target.current, telaUrl(pc.id), { wsProtocols: ["binary"] });
      client.scaleViewport = true;
      client.resizeSession = false;
      client.viewOnly = true;
      client.addEventListener("connect", () => setState("conectado"));
      client.addEventListener("disconnect", () => setState("caiu"));
      rfb.current = client;
      onChange();
    }, (e) => { if (!cancelled) { setError(fail(e)); setState("caiu"); } });
    return () => { cancelled = true; rfb.current?.disconnect(); rfb.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reconecta só ao trocar de computador
  }, [pc.id]);

  useEffect(() => {
    if (!rfb.current) return;
    rfb.current.viewOnly = !dono;
    if (dono) rfb.current.focus();
  }, [dono, state]);

  const control = async (next: boolean) => {
    try { await controlarComputador(pc.id, next); onChange(); } catch (e) { setError(fail(e)); }
  };
  const close = () => {
    if (dono) void controlarComputador(pc.id, false);
    onClose();
  };
  const turnOff = async () => {
    try { await desligarComputador(pc.id); onClose(); } catch (e) { setError(fail(e)); }
  };
  const art = of(pc.nome);

  return (
    <dialog ref={dialog} className={`pc-dialog ${full ? "is-full" : ""}`} onCancel={(e) => { e.preventDefault(); close(); }}
      aria-label={`Computador ${art} ${pc.nome}`}>
      <header className="pc-head">
        <AgentAvatar id={pc.id} size={36} state={pc.agente_ativo ? "thinking" : "idle"} />
        <div className="pc-head-text">
          <strong>Computador {art} {pc.nome}</strong>
          <span>{dono ? <>Você no controle · {art === "da" ? "a" : "o"} {pc.nome} espera</>
            : <>{art === "da" ? "A" : "O"} {pc.nome} no controle · você assiste</>}</span>
        </div>
        <div className="pc-head-actions">
          <button type="button" className="btn btn-primary" onClick={() => void control(!dono)} disabled={state !== "conectado"}>
            <Icon name={dono ? "check" : "monitor"} /> {dono ? "Devolver" : "Assumir"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => void turnOff()} title="Desligar o computador">
            <Icon name="stop" /><span className="visually-hidden">Desligar</span>
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => setFull(!full)} title={full ? "Reduzir" : "Tela cheia"}>
            <Icon name="panel" /><span className="visually-hidden">{full ? "Reduzir" : "Tela cheia"}</span>
          </button>
          <button type="button" className="btn btn-ghost" onClick={close} title="Fechar">
            <Icon name="x" /><span className="visually-hidden">Fechar</span>
          </button>
        </div>
      </header>
      <ErrorNotice error={error} />
      <div className={`pc-screen ${dono ? "is-owner" : ""}`}>
        <div ref={target} className="pc-vnc" />
        {state !== "conectado" && (
          <div className="pc-overlay">{state === "ligando" ? <Loading label="Ligando o computador…" /> : "A tela caiu. Feche e abra de novo."}</div>
        )}
      </div>
      <footer className="pc-foot">
        <span><Icon name="info" /> Os programas do computador {art} {pc.nome} veem a tela e o que você digita.</span>
        {ip && <span>IP de saída <strong>{ip}</strong></span>}
      </footer>
    </dialog>
  );
}
