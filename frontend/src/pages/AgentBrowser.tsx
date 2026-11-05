// SPDX-License-Identifier: AGPL-3.0-or-later
/** Navegador do agente (Carreira): ver e controlar o Chrome do aplicador para entrar em contas e resolver CAPTCHA. */
import { useCallback, useEffect, useRef, useState, type FormEvent, type MouseEvent } from "react";
import { ApiError } from "../api/client";
import { browserAction, getBrowserFrame, type BrowserAction, type BrowserFrame, type BrowserKey } from "../api/carreira";
import { ErrorNotice, PageHeader } from "../components/ui";
import "../styles/carreira.css";

const POLL_MS = 1500;
const KEYS: { key: BrowserKey; label: string }[] = [
  { key: "Enter", label: "Enter" }, { key: "Backspace", label: "Apagar" }, { key: "Tab", label: "Tab" },
  { key: "Escape", label: "Esc" },
];

const fail = (e: unknown) => ({ detail: e instanceof ApiError ? e.detail : "Não consegui falar com o navegador do agente." });

export function AgentBrowserPage() {
  const [frame, setFrame] = useState<BrowserFrame | null>(null);
  const [error, setError] = useState<{ detail: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const img = useRef<HTMLImageElement>(null);

  const run = useCallback(async (body: BrowserAction) => {
    setBusy(true);
    try {
      const next = await browserAction(body);
      setFrame(next);
      setError(null);
      if (next.url && body.acao !== "abrir") setUrl(next.url);
    } catch (e) { setError(fail(e)); } finally { setBusy(false); }
  }, []);

  useEffect(() => { void getBrowserFrame().then(setFrame, (e) => setError(fail(e))); }, []);
  useEffect(() => {
    if (!frame?.ativo) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && !busy) void getBrowserFrame().then(setFrame, () => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [frame?.ativo, busy]);

  const click = (e: MouseEvent<HTMLImageElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const x = Math.round(((e.clientX - box.left) / box.width) * (frame?.largura ?? 1280));
    const y = Math.round(((e.clientY - box.top) / box.height) * (frame?.altura ?? 900));
    void run({ acao: "clicar", x, y });
  };
  const typeText = (e: FormEvent) => {
    e.preventDefault();
    if (!text) return;
    void run({ acao: "digitar", texto: text }).then(() => setText(""));
  };
  const go = (e: FormEvent) => { e.preventDefault(); if (url.trim()) void run({ acao: "abrir", url: url.trim() }); };

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Carreira" title="Navegador do agente"
        lede="O mesmo navegador que o agente usa nas candidaturas. Entre nas suas contas (Google, Indeed, LinkedIn, Gupy) e resolva verificações: o que você logar aqui fica salvo para ele."
        actions={frame?.ativo
          ? <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void run({ acao: "encerrar" })}>Encerrar</button>
          : <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void run({ acao: "iniciar" })}>Abrir navegador</button>} />
      <ErrorNotice error={error} />
      {frame?.erro && <p className="small" role="alert">{frame.erro}</p>}
      {frame?.ativo && (
        <div className="agent-browser stack">
          <form className="agent-browser-bar" onSubmit={go}>
            <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void run({ acao: "voltar" })} aria-label="Voltar">←</button>
            <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Endereço (ex.: indeed.com.br)" aria-label="Endereço" inputMode="url" />
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>Ir</button>
          </form>
          {frame.imagem && (
            <img ref={img} className="agent-browser-screen" src={`data:image/jpeg;base64,${frame.imagem}`}
              alt={`Tela do navegador do agente: ${frame.titulo || frame.url || ""}`} onClick={click} data-busy={busy || undefined} />
          )}
          <form className="agent-browser-bar" onSubmit={typeText}>
            <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Toque num campo da tela e digite aqui"
              aria-label="Texto para digitar" autoComplete="off" />
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !text}>Digitar</button>
          </form>
          <div className="agent-browser-keys">
            {KEYS.map((k) => <button key={k.key} type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void run({ acao: "tecla", tecla: k.key })}>{k.label}</button>)}
            <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void run({ acao: "rolar", dy: -600 })}>Rolar ↑</button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void run({ acao: "rolar", dy: 600 })}>Rolar ↓</button>
          </div>
          <p className="tiny muted">O navegador fecha sozinho depois de 10 minutos sem uso. O que você digita aqui não fica registrado no Lastro.</p>
        </div>
      )}
    </div>
  );
}
