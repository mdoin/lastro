// SPDX-License-Identifier: AGPL-3.0-or-later
/** Navegador do agente (Carreira): ver e controlar o Chrome do aplicador para entrar em contas e resolver CAPTCHA. */
import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type FormEvent, type KeyboardEvent, type MouseEvent, type PointerEvent, type WheelEvent } from "react";
import { ApiError } from "../api/client";
import { browserAction, getBrowserFrame, type BrowserAction, type BrowserFrame } from "../api/carreira";
import { ErrorNotice, PageHeader } from "../components/ui";
import "../styles/carreira.css";

const POLL_MS = 1500;
// Teclas de controle: vão como evento de tecla (não produzem texto). O resto digitável passa pela composição/input.
const CONTROL_KEYS = new Set(["Enter", "Backspace", "Tab", "Escape", "Delete", "Insert", "Home", "End", "PageUp",
  "PageDown", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);
const DRAG_THRESHOLD = 6;

const fail = (e: unknown) => ({ detail: e instanceof ApiError ? e.detail : "Não consegui falar com o navegador do agente." });

export function AgentBrowserPage() {
  const [frame, setFrame] = useState<BrowserFrame | null>(null);
  const [error, setError] = useState<{ detail: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [focused, setFocused] = useState(false);
  const [text, setText] = useState("");
  // ?abrir= vem da Central de Contas (endereço oficial da plataforma): só preenche, quem abre é o dono
  const [url, setUrl] = useState(() => new URLSearchParams(window.location.search).get("abrir") ?? "");
  const capture = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);

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

  // Converte a posição do ponteiro na imagem para as coordenadas do viewport do Chromium.
  const toViewport = (e: { clientX: number; clientY: number }, el: HTMLElement) => {
    const box = el.getBoundingClientRect();
    return {
      x: Math.round(((e.clientX - box.left) / box.width) * (frame?.largura ?? 1280)),
      y: Math.round(((e.clientY - box.top) / box.height) * (frame?.altura ?? 900)),
    };
  };

  const onPointerDown = (e: PointerEvent<HTMLTextAreaElement>) => {
    capture.current?.focus();
    drag.current = { ...toViewport(e, e.currentTarget), moved: false };
  };
  const onPointerMove = (e: PointerEvent<HTMLTextAreaElement>) => {
    if (drag.current && (Math.abs(e.movementX) > 0 || Math.abs(e.movementY) > 0)) {
      const d = toViewport(e, e.currentTarget);
      if (Math.abs(d.x - drag.current.x) + Math.abs(d.y - drag.current.y) > DRAG_THRESHOLD) drag.current.moved = true;
    }
  };
  const onPointerUp = (e: PointerEvent<HTMLTextAreaElement>) => {
    const start = drag.current; drag.current = null;
    if (!start) return;
    const end = toViewport(e, e.currentTarget);
    if (start.moved) void run({ acao: "arrastar", x: start.x, y: start.y, x2: end.x, y2: end.y });
    else void run({ acao: "clicar", x: end.x, y: end.y });
  };
  const onDoubleClick = (e: MouseEvent<HTMLTextAreaElement>) => {
    drag.current = null;
    void run({ acao: "duplo", ...toViewport(e, e.currentTarget) });
  };
  const onWheel = (e: WheelEvent<HTMLTextAreaElement>) => {
    void run({ acao: "rolar", dy: Math.max(-3000, Math.min(Math.round(e.deltaY), 3000)) });
  };

  // Texto digitado chega sempre vazio e é esvaziado a cada envio, para o teclado nunca duplicar caracteres.
  const flush = (ta: HTMLTextAreaElement) => {
    const value = ta.value;
    ta.value = "";
    if (value) void run({ acao: "inserir", texto: value });
  };
  const onInput = (e: FormEvent<HTMLTextAreaElement>) => { if (!composing.current) flush(e.currentTarget); };
  const onCompositionEnd = (e: FormEvent<HTMLTextAreaElement>) => { composing.current = false; flush(e.currentTarget); };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (composing.current) return;                       // durante acento/IME, deixa a composição terminar
    const combo = e.ctrlKey || e.metaKey || e.altKey;
    if (combo && (e.key === "v" || e.key === "V")) return; // colar: tratado por onPaste (área de transferência local)
    if (combo || CONTROL_KEYS.has(e.key)) {
      e.preventDefault();                                // Tab/Enter não mexem na nossa página; viram tecla no Chromium
      void run({ acao: "teclar", key: e.key, ctrl: e.ctrlKey, alt: e.altKey, shift: e.shiftKey, meta: e.metaKey });
    }
    // caractere digitável sem modificador: não envia aqui; vai pelo input/composição (acentos, celular)
  };
  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const value = e.clipboardData.getData("text");
    e.preventDefault();
    if (value) void run({ acao: "inserir", texto: value.slice(0, 2000) });
  };

  const typeText = (e: FormEvent) => { e.preventDefault(); if (text) void run({ acao: "inserir", texto: text }).then(() => setText("")); };
  const go = (e: FormEvent) => { e.preventDefault(); if (url.trim()) void run({ acao: "abrir", url: url.trim() }); };

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Carreira" title="Navegador do agente"
        lede="O mesmo navegador que o agente usa nas candidaturas. Clique na tela e digite direto pelo teclado; entre nas suas contas e resolva verificações. O que você logar aqui fica salvo para ele."
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
          <div className="agent-browser-screen-wrap" data-focused={focused || undefined}>
            {frame.imagem && (
              <img className="agent-browser-screen" src={`data:image/jpeg;base64,${frame.imagem}`}
                alt={`Tela do navegador do agente: ${frame.titulo || frame.url || ""}`} draggable={false} data-busy={busy || undefined} />
            )}
            {/* Captura transparente sobre a imagem: foca com o clique (abre o teclado no celular), recebe teclas,
                acentos, composição e colar, sem a caixa auxiliar. */}
            <textarea ref={capture} className="agent-browser-capture" aria-label="Controle do navegador do agente"
              value="" autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
              onChange={() => undefined} onInput={onInput}
              onCompositionStart={() => { composing.current = true; }} onCompositionEnd={onCompositionEnd}
              onKeyDown={onKeyDown} onPaste={onPaste} onWheel={onWheel}
              onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onDoubleClick={onDoubleClick}
              onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} />
          </div>
          <p className="tiny muted">{focused ? "Teclado ativo: digite direto. Enter, Tab, setas, Ctrl+A/C/V e colar funcionam." : "Clique na tela para ativar o teclado."}</p>
          <details className="agent-browser-fallback">
            <summary className="small">Caixa de digitação (reserva)</summary>
            <form className="agent-browser-bar" onSubmit={typeText}>
              <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Digite e envie se o teclado direto falhar"
                aria-label="Texto para digitar" autoComplete="off" />
              <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !text}>Digitar</button>
            </form>
          </details>
          <p className="tiny muted">O navegador fecha sozinho depois de 10 minutos sem uso. O que você digita aqui não fica registrado no Lastro.</p>
        </div>
      )}
    </div>
  );
}
