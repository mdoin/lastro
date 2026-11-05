// SPDX-License-Identifier: AGPL-3.0-or-later
/** Tela ao vivo do computador de um agente (noVNC): só assistir, ou assumir o controle enquanto o agente espera. */
import { useEffect, useRef, useState } from "react";
import RFB from "@novnc/novnc";
import { ApiError } from "../api/client";
import { controlarComputador, getComputadores, ligarComputador, telaUrl } from "../api/computadores";
import { Icon } from "./Icon";
import { ErrorNotice, Loading } from "./ui";
import "../styles/computadores.css";

// Concordância do "do/da" com o nome do agente.
const FEMININE = new Set(["Mila", "Lia", "Vera", "Nina", "Cora"]);
export const of = (nome: string) => (FEMININE.has(nome) ? "da" : "do");
const fail = (e: unknown) => ({ detail: e instanceof ApiError ? e.detail : "Não consegui falar com o computador." });

/** Os computadores existem nesta instalação? (sem o controlador, a conversa mostra os quadros do navegador). */
export function useComputersAvailable() {
  const [ok, setOk] = useState(false);
  useEffect(() => { void getComputadores().then(() => setOk(true), () => setOk(false)); }, []);
  return ok;
}

export function ComputerScreen({ id, nome, compact = false }: { id: string; nome: string; compact?: boolean }) {
  const target = useRef<HTMLDivElement>(null);
  const rfb = useRef<RFB | null>(null);
  const owner = useRef(false);
  const [state, setState] = useState<"ligando" | "conectado" | "caiu">("ligando");
  const [dono, setDono] = useState(false);
  const [ip, setIp] = useState("");
  const [error, setError] = useState<{ detail: string } | null>(null);
  const art = of(nome);

  useEffect(() => {
    let cancelled = false;
    ligarComputador(id).then(() => {
      if (cancelled || !target.current) return;
      const client = new RFB(target.current, telaUrl(id), { wsProtocols: ["binary"] });
      client.scaleViewport = true;
      client.resizeSession = false;
      client.viewOnly = true;
      client.addEventListener("connect", () => setState("conectado"));
      client.addEventListener("disconnect", () => setState("caiu"));
      rfb.current = client;
      void getComputadores().then((d) => {
        if (cancelled) return;
        setIp(d.ip_saida);
        const mine = d.agentes.find((a) => a.id === id);
        owner.current = mine?.controle === "dono";
        setDono(owner.current);
      }, () => undefined);
    }, (e) => { if (!cancelled) { setError(fail(e)); setState("caiu"); } });
    return () => {
      cancelled = true;
      rfb.current?.disconnect();
      rfb.current = null;
      if (owner.current) void controlarComputador(id, false); // saiu da tela: devolve ao agente
    };
  }, [id]);

  useEffect(() => {
    if (!rfb.current) return;
    rfb.current.viewOnly = !dono;
    if (dono) rfb.current.focus();
  }, [dono, state]);

  const control = async (next: boolean) => {
    try { await controlarComputador(id, next); owner.current = next; setDono(next); } catch (e) { setError(fail(e)); }
  };

  return (
    <div className={`pc-live ${compact ? "is-compact" : ""}`}>
      <div className="pc-bar">
        <span className="pc-bar-text">{dono ? <>Você no controle · {art === "da" ? "a" : "o"} {nome} espera</>
          : <>{art === "da" ? "A" : "O"} {nome} no controle · você assiste</>}</span>
        <button type="button" className={`btn ${compact ? "btn-secondary btn-sm" : "btn-primary"}`}
          onClick={() => void control(!dono)} disabled={state !== "conectado"}>
          <Icon name={dono ? "check" : "monitor"} /> {dono ? "Devolver" : "Assumir"}
        </button>
      </div>
      <ErrorNotice error={error} />
      <div className={`pc-screen ${dono ? "is-owner" : ""}`}>
        <div ref={target} className="pc-vnc" />
        {state !== "conectado" && (
          <div className="pc-overlay">{state === "ligando" ? <Loading label="Ligando o computador…" /> : "A tela caiu. Feche e abra de novo."}</div>
        )}
      </div>
      <div className="pc-foot">
        <span><Icon name="info" /> Os programas do computador {art} {nome} veem a tela e o que você digita.</span>
        {ip && <span>IP de saída <strong>{ip}</strong></span>}
      </div>
    </div>
  );
}
