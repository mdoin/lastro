import { useCallback, useEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  createConversation,
  deleteConversation,
  getConversations,
  getMessages,
  interruptConversation,
  streamMessage,
  streamPanel,
} from "../api/endpoints";
import type {
  AuditVerdict,
  BrowserFrame,
  ChatEvent,
  Conversation,
  Message,
  PanelEvent,
  PanelRole,
  ToolUse,
} from "../api/types";
import { BrowserView } from "../components/BrowserView";
import { BrandMark, Icon, type IconName } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { Badge, Card, Disclaimer, ErrorNotice, Loading, Notice, PageHeader, Segmented, Tag } from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDateTime, formatTime } from "../lib/dates";
import { AUDIT_VERDICT, PANEL_ROLE_LABEL, toolLabel } from "../lib/labels";
import { useAsync } from "../lib/useAsync";

type Mode = "chat" | "panel";

interface WaitState {
  kind: "queued" | "waiting_limit";
  position?: number;
  retryAt?: string | null;
  message?: string;
}

interface PendingReply {
  conversationId: string;
  text: string;
  tools: ToolUse[];
  wait: WaitState | null;
  error: string | null;
  interrupting: boolean;
}

interface AgentState {
  role: PanelRole;
  label: string;
  status: "waiting" | "running" | "done" | "error";
  text: string;
  tools: ToolUse[];
}

/** Linha do registro do painel: quem fez o quê, e quando (ms desde o início). */
interface LogEntry {
  /** Identificador estável (chave de renderização). */
  id: number;
  t: number;
  actor: string;
  color: string;
  text: string;
}

interface PanelRun {
  question: string;
  agents: AgentState[];
  synthesis: string;
  audit: { verdict: AuditVerdict; reasons: string[] } | null;
  wait: WaitState | null;
  error: string | null;
  finished: boolean;
  frame: BrowserFrame | null;
  /** Id da mensagem final persistida (evento done). */
  messageId: string | null;
  startedAt: number;
  endedAt: number | null;
  log: LogEntry[];
}

function useMediaQuery(q: string): boolean {
  const [match, setMatch] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const on = () => setMatch(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [q]);
  return match;
}

const KIND_LABEL: Record<Conversation["kind"], string> = { chat: "Conversa", routine: "Rotina", panel: "Painel" };

/** Identidade de cada especialista: ícone, função curta e cor (sempre com nome ao lado). */
const AGENT_META: Record<PanelRole | "coordenador" | "auditor", { icon: IconName; role: string; color: string }> = {
  diagnostico: { icon: "pulse", role: "situação", color: "var(--agent-diagnostico)" },
  simulacao: { icon: "bars", role: "cenários", color: "var(--agent-simulacao)" },
  riscos: { icon: "alert", role: "alertas", color: "var(--agent-riscos)" },
  educacao: { icon: "cap", role: "conceitos", color: "var(--agent-educacao)" },
  pesquisa: { icon: "globe", role: "fontes", color: "var(--agent-pesquisa)" },
  coordenador: { icon: "layers", role: "síntese", color: "var(--agent-coordenador)" },
  auditor: { icon: "shieldCheck", role: "revisão", color: "var(--agent-auditor)" },
};

const SUGGESTIONS = [
  "O que faço com o dinheiro disponível este mês?",
  "Explique minha reserva de emergência em termos simples.",
  "Vale mais quitar o cartão ou começar a investir?",
];

const MAX_LOG = 60;
let logSeq = 0;

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function seconds(ms: number): string {
  return `${(Math.max(0, ms) / 1000).toFixed(1).replace(".", ",")}s`;
}

export function MentorPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const app = useApp();
  const wide = useMediaQuery("(min-width: 1100px)");
  const coarse = useMediaQuery("(pointer: coarse)");

  const conversations = useAsync(getConversations, []);
  const messages = useAsync<Message[]>(
    () => (conversationId ? getMessages(conversationId) : Promise.resolve([])),
    [conversationId],
  );

  const [mode, setMode] = useState<Mode>("chat");
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<PendingReply | null>(null);
  const [panel, setPanel] = useState<PanelRun | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const keepPanelOnNav = useRef(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const current = conversations.data?.find((c) => c.id === conversationId) ?? null;

  // Sair da página derruba a conexão; o turno continua no servidor.
  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (keepPanelOnNav.current) {
      keepPanelOnNav.current = false;
      return;
    }
    if (!busy) {
      setPanel(null);
      setPending(null);
    }
    setNotice(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  useEffect(() => {
    const nearBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 320;
    if (nearBottom) endRef.current?.scrollIntoView({ block: "end" });
  }, [pending?.text, pending?.tools.length, panel?.synthesis, panel?.agents, panel?.log.length, messages.data?.length]);

  const handleWait = (ev: ChatEvent | PanelEvent): WaitState | null | undefined => {
    if (ev.event === "queued") return { kind: "queued", position: ev.data.position };
    if (ev.event === "waiting_limit") return { kind: "waiting_limit", retryAt: ev.data.retry_at, message: ev.data.message };
    return undefined;
  };

  const sendChat = useCallback(
    async (text: string) => {
      let id = conversationId;
      if (!id) {
        const conv = await createConversation(text.slice(0, 60));
        conversations.setData((prev) => [conv, ...(prev ?? [])]);
        id = conv.id;
        keepPanelOnNav.current = true;
        navigate(`/mentor/${conv.id}`, { replace: false });
      }
      const convId = id;
      const optimistic: Message = {
        id: `local-${Date.now()}`,
        role: "user",
        content: text,
        status: "ok",
        tools: [],
        created_at: new Date().toISOString(),
      };
      messages.setData((prev) => [...(prev ?? []), optimistic]);
      setPending({ conversationId: convId, text: "", tools: [], wait: null, error: null, interrupting: false });

      const ctrl = new AbortController();
      abortRef.current = ctrl;
      let gotDone = false;
      try {
        await streamMessage(
          convId,
          text,
          (ev) => {
            const wait = handleWait(ev);
            if (wait !== undefined) return setPending((p) => (p ? { ...p, wait } : p));
            switch (ev.event) {
              case "tool":
                setPending((p) => (p ? { ...p, wait: null, tools: [...p.tools, ev.data] } : p));
                break;
              case "delta":
                setPending((p) => (p ? { ...p, wait: null, text: p.text + ev.data.text } : p));
                break;
              case "done":
                gotDone = true;
                messages.setData((prev) => [...(prev ?? []), ev.data.message]);
                setPending(null);
                break;
              case "error":
                setPending((p) => (p ? { ...p, wait: null, error: ev.data.message } : p));
                break;
            }
          },
          ctrl.signal,
        );
      } catch (e) {
        const msg = e instanceof ApiError ? e.detail : "Falha ao enviar.";
        setPending((p) => (p ? { ...p, error: msg } : p));
      } finally {
        abortRef.current = null;
      }
      if (!ctrl.signal.aborted) {
        if (!gotDone) setNotice("A conexão terminou antes da resposta final. O mentor continua no servidor; recarregamos a conversa.");
        await messages.reload();
        if (gotDone) setPending(null);
        void conversations.reload();
        void app.refresh();
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [conversationId, navigate],
  );

  const sendPanel = useCallback(
    async (question: string) => {
      const startedAt = Date.now();
      setPanel({
        question,
        agents: [],
        synthesis: "",
        audit: null,
        wait: null,
        error: null,
        finished: false,
        frame: null,
        messageId: null,
        startedAt,
        endedAt: null,
        log: [{ id: ++logSeq, t: 0, actor: "Painel", color: "var(--faint)", text: "pergunta recebida" }],
      });
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      let doneConv: string | null = null;
      const log = (p: PanelRun, actor: string, color: string, text: string): LogEntry[] =>
        [...p.log, { id: ++logSeq, t: Date.now() - p.startedAt, actor, color, text }].slice(-MAX_LOG);
      const metaOf = (role: PanelRole) => AGENT_META[role] ?? AGENT_META.diagnostico;
      const updAgent = (role: PanelRole, fn: (a: AgentState) => AgentState, entry?: string) =>
        setPanel((p) => {
          if (!p) return p;
          const exists = p.agents.some((a) => a.role === role);
          const agents = exists
            ? p.agents.map((a) => (a.role === role ? fn(a) : a))
            : [...p.agents, fn({ role, label: PANEL_ROLE_LABEL[role] ?? role, status: "waiting", text: "", tools: [] })];
          const label = agents.find((a) => a.role === role)?.label ?? role;
          return { ...p, agents, wait: null, log: entry ? log(p, label, metaOf(role).color, entry) : p.log };
        });
      try {
        await streamPanel(
          question,
          current?.kind === "panel" ? current.id : null,
          (ev) => {
            const wait = handleWait(ev);
            if (wait !== undefined)
              return setPanel((p) => {
                if (!p) return p;
                if (!wait) return { ...p, wait };
                const text =
                  wait.kind === "queued"
                    ? `na fila${wait.position ? ` (posição ${wait.position})` : ""}`
                    : `limite da assinatura — ${wait.retryAt ? `retomo às ${formatTime(wait.retryAt)}` : "retomo assim que liberar"}`;
                return { ...p, wait, log: log(p, "Painel", "var(--warning)", text) };
              });
            switch (ev.event) {
              case "plan":
                setPanel((p) =>
                  p
                    ? {
                        ...p,
                        wait: null,
                        agents: ev.data.agents.map((a) => ({ role: a.role, label: a.label, status: "waiting", text: "", tools: [] })),
                        log: log(p, "Coordenador", AGENT_META.coordenador.color,
                          `montou o painel com ${plural(ev.data.agents.length, "especialista", "especialistas")}`),
                      }
                    : p,
                );
                break;
              case "agent_start":
                updAgent(ev.data.role, (a) => ({ ...a, status: "running" }), "começou a analisar");
                break;
              case "agent_tool":
                updAgent(
                  ev.data.role,
                  (a) => ({ ...a, status: "running", tools: [...a.tools, { name: ev.data.name, input: ev.data.input }] }),
                  toolLabel(ev.data.name).toLowerCase(),
                );
                break;
              case "agent_delta":
                updAgent(ev.data.role, (a) => ({ ...a, status: "running", text: a.text + ev.data.text }));
                break;
              case "agent_done":
                updAgent(
                  ev.data.role,
                  (a) => ({ ...a, status: ev.data.status === "ok" ? "done" : "error", text: ev.data.text || a.text }),
                  ev.data.status === "ok" ? "concluiu a análise" : "terminou com erro",
                );
                break;
              case "synthesis_delta":
                setPanel((p) =>
                  p
                    ? {
                        ...p,
                        wait: null,
                        synthesis: p.synthesis + ev.data.text,
                        log: p.synthesis ? p.log : log(p, "Coordenador", AGENT_META.coordenador.color, "consolidando a síntese"),
                      }
                    : p,
                );
                break;
              case "audit":
                setPanel((p) =>
                  p ? { ...p, audit: ev.data, log: log(p, "Auditor", AGENT_META.auditor.color, `veredito ${ev.data.verdict}`) } : p,
                );
                break;
              case "browser_frame":
                setPanel((p) => (p ? { ...p, frame: ev.data } : p));
                break;
              case "done":
                doneConv = ev.data.conversation_id;
                setPanel((p) =>
                  p
                    ? {
                        ...p,
                        finished: true,
                        endedAt: Date.now(),
                        messageId: ev.data.message.id,
                        synthesis: ev.data.message.content || p.synthesis,
                        log: log(p, "Painel", "var(--good)", "resposta final salva na conversa"),
                      }
                    : p,
                );
                break;
              case "error":
                setPanel((p) => (p ? { ...p, error: ev.data.message, log: log(p, "Painel", "var(--critical)", "erro no painel") } : p));
                break;
            }
          },
          ctrl.signal,
        );
      } catch (e) {
        setPanel((p) => (p ? { ...p, error: e instanceof ApiError ? e.detail : "Falha no painel." } : p));
      } finally {
        abortRef.current = null;
      }
      if (ctrl.signal.aborted) return;
      setPanel((p) => (p ? { ...p, finished: true, endedAt: p.endedAt ?? Date.now() } : p));
      await conversations.reload();
      void app.refresh();
      if (doneConv && doneConv !== conversationId) {
        keepPanelOnNav.current = true;
        navigate(`/mentor/${doneConv}`);
      } else {
        await messages.reload();
      }
      if (!doneConv) setNotice("O painel terminou sem resultado final. Verifique a lista de conversas em instantes.");
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [conversationId, current, navigate],
  );

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setNotice(null);
    setBusy(true);
    try {
      if (mode === "chat") await sendChat(text);
      else await sendPanel(text);
    } catch (err) {
      setNotice(err instanceof ApiError ? err.detail : "Não foi possível enviar.");
      setInput(text);
    } finally {
      setBusy(false);
    }
  }

  async function interrupt() {
    if (panel && !panel.finished) {
      // O contrato não tem rota para interromper um painel: só paramos de acompanhar.
      abortRef.current?.abort();
      setPanel((p) =>
        p
          ? {
              ...p,
              finished: true,
              endedAt: Date.now(),
              error: "Você parou de acompanhar o painel. Ele pode terminar no servidor e aparecer na lista de conversas.",
            }
          : p,
      );
      return;
    }
    const id = pending?.conversationId ?? conversationId;
    if (!id) {
      abortRef.current?.abort();
      return;
    }
    setPending((p) => (p ? { ...p, interrupting: true } : p));
    try {
      await interruptConversation(id);
    } catch (e) {
      setNotice(e instanceof ApiError ? e.detail : "Não foi possível interromper.");
    }
  }

  async function removeConversation(c: Conversation) {
    if (!window.confirm(`Excluir a conversa "${c.title || "sem título"}"?`)) return;
    try {
      await deleteConversation(c.id);
      conversations.setData((prev) => (prev ?? []).filter((x) => x.id !== c.id));
      if (c.id === conversationId) navigate("/mentor");
    } catch (e) {
      setNotice(e instanceof ApiError ? e.detail : "Não foi possível excluir.");
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !coarse && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  }

  function pick(text: string) {
    setInput(text);
    inputRef.current?.focus();
  }

  const mentor = app.status?.mentor;

  const list = (
    <Card
      className="flat"
      title="Conversas"
      aside={
        <Link className="btn btn-secondary btn-sm" to="/mentor" aria-label="Nova conversa">
          <Icon name="plus" />
          Nova
        </Link>
      }
    >
      {conversations.loading && !conversations.data && <Loading />}
      <ErrorNotice error={conversations.error} onRetry={conversations.reload} />
      {conversations.data && conversations.data.length === 0 && <p className="small muted">Nenhuma conversa ainda.</p>}
      <div className="conv-list" role="list">
        {conversations.data?.map((c) => (
          <div key={c.id} role="listitem" className="row" style={{ flexWrap: "nowrap", gap: 2 }}>
            <button type="button" style={{ flex: 1 }} aria-current={c.id === conversationId ? "true" : undefined}
              onClick={() => navigate(`/mentor/${c.id}`)}>
              <span className="conv-title">{c.title || "Sem título"}</span>
              <span className="conv-meta">
                {KIND_LABEL[c.kind]} · {formatDateTime(c.updated_at)}
              </span>
            </button>
            <button type="button" className="icon-btn"
              aria-label={`Excluir conversa ${c.title}`} onClick={() => void removeConversation(c)}>
              <Icon name="trash" />
            </button>
          </div>
        ))}
      </div>
    </Card>
  );

  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Mentor"
        title={current?.title || "Converse com o mentor"}
        lede="O mentor explica e organiza; os números vêm do motor financeiro. Ele não executa operações, não acessa contas e não decide por você."
      />

      {mentor && !mentor.available && <Notice tone="warning">O mentor está indisponível no servidor neste momento.</Notice>}
      {mentor && mentor.available && mentor.logged_in === false && (
        <Notice tone="warning">O mentor não está conectado à assinatura no servidor. Veja Configurações.</Notice>
      )}
      {mentor?.limit_until && (
        <Notice tone="warning">Limite da assinatura atingido — retomo às {formatTime(mentor.limit_until)}.</Notice>
      )}

      <div className="mentor">
        {wide ? (
          <aside aria-label="Lista de conversas">{list}</aside>
        ) : (
          <details>
            <summary>Conversas ({conversations.data?.length ?? 0})</summary>
            {list}
          </details>
        )}

        <section className="stack" aria-label="Conversa">
          <div className="thread" aria-live="off">
            {conversationId && messages.loading && !messages.data?.length && <Loading />}
            <ErrorNotice error={messages.error} onRetry={messages.reload} />
            {!conversationId && !pending && !panel && <Welcome onPick={pick} />}
            {messages.data?.map((m) => <MessageView key={m.id} m={m} />)}
            {pending && pending.conversationId === conversationId && <PendingView p={pending} />}
            {panel && (
              <PanelView
                run={panel}
                compact={!!panel.messageId && !!messages.data?.some((m) => m.id === panel.messageId)}
                onStop={busy && !panel.finished ? () => void interrupt() : undefined}
              />
            )}
            <div ref={endRef} />
          </div>

          {notice && (
            <Notice tone="warning">
              {notice}{" "}
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => void messages.reload()}>
                Atualizar
              </button>
            </Notice>
          )}

          <form className="composer" onSubmit={submit}>
            <label htmlFor="composer-text" className="visually-hidden">
              {mode === "chat" ? "Mensagem para o mentor" : "Pergunta para o painel de especialistas"}
            </label>
            <textarea
              id="composer-text"
              ref={inputRef}
              className="textarea"
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={mode === "chat" ? "Escreva sua pergunta…" : "Pergunta para o painel de especialistas…"}
              maxLength={8000}
            />
            <div className="composer-row">
              <Segmented<Mode>
                label="Modo de resposta"
                value={mode}
                onChange={setMode}
                options={[
                  { value: "chat", label: "Conversa" },
                  { value: "panel", label: "Painel de especialistas" },
                ]}
              />
              <div className="composer-actions">
                {!coarse && <span className="composer-hint">Enter envia · Shift+Enter quebra linha</span>}
                {busy && (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => void interrupt()}
                    disabled={pending?.interrupting} aria-label="Interromper resposta">
                    <Icon name="stop" />
                    <span className="btn-text">{pending?.interrupting ? "Interrompendo…" : "Interromper"}</span>
                  </button>
                )}
                <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !input.trim()}
                  aria-label={mode === "chat" ? "Enviar" : "Consultar painel"}>
                  <Icon name={mode === "chat" ? "arrowUp" : "panel"} />
                  <span className="btn-text">{mode === "chat" ? "Enviar" : "Consultar painel"}</span>
                </button>
              </div>
            </div>
          </form>

          <Disclaimer text={app.disclaimer}
            extra={<p>Respostas do mentor são educativas. Confira os números no motor e decida você.</p>} />
        </section>
      </div>
    </div>
  );
}

function Welcome({ onPick }: { onPick: (text: string) => void }) {
  const specialists: (keyof typeof AGENT_META)[] = ["diagnostico", "simulacao", "riscos", "educacao", "coordenador", "auditor"];
  return (
    <Card title="Por onde começar" eyebrow="Sugestões"
      footer={
        <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
          <span className="row" style={{ gap: 4, flexWrap: "nowrap" }} aria-hidden="true">
            {specialists.map((k) => (
              <span key={k} className="agent-chip" style={{ ["--c" as string]: AGENT_META[k].color } as CSSProperties}>
                <Icon name={AGENT_META[k].icon} />
              </span>
            ))}
          </span>
          <span>
            No modo Painel de especialistas, vários agentes analisam em paralelo, um Coordenador consolida e um Auditor revisa.
          </span>
        </span>
      }>
      <div className="suggestions">
        {SUGGESTIONS.map((s) => (
          <button key={s} type="button" className="suggestion" onClick={() => onPick(s)}>
            <span>{s}</span>
            <Icon name="arrowUpRight" />
          </button>
        ))}
      </div>
    </Card>
  );
}

function ToolChips({ tools }: { tools: ToolUse[] }) {
  if (!tools.length) return null;
  return (
    <div className="row" style={{ gap: 6 }} aria-label="Ferramentas consultadas">
      {tools.map((t, i) => (
        <span key={i} className="chip" title={t.name}>
          {toolLabel(t.name)}
        </span>
      ))}
    </div>
  );
}

function MentorAvatar() {
  return (
    <span className="msg-avatar" aria-hidden="true">
      <BrandMark />
    </span>
  );
}

function MessageView({ m }: { m: Message }) {
  if (m.role === "user") {
    return (
      <div className="msg user">
        <div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{m.content}</div>
      </div>
    );
  }
  return (
    <article className="msg assistant" aria-label="Resposta do mentor">
      <MentorAvatar />
      <div className="msg-who">
        Mentor <span className="msg-meta">{formatDateTime(m.created_at)}</span>
        {m.status === "interrupted" && <Badge tone="warning">Interrompida</Badge>}
        {m.status === "error" && <Badge tone="critical">Erro</Badge>}
      </div>
      <ToolChips tools={m.tools} />
      <Markdown text={m.content} />
    </article>
  );
}

function WaitView({ wait }: { wait: WaitState }) {
  if (wait.kind === "queued") {
    return (
      <p className="small muted" role="status">
        Na fila{wait.position ? ` (posição ${wait.position})` : ""}: outro turno está em andamento.
      </p>
    );
  }
  return (
    <Notice tone="warning">
      Limite da assinatura atingido — {wait.retryAt ? `retomo às ${formatTime(wait.retryAt)}` : "retomo assim que liberar"}.
      {wait.message ? ` ${wait.message}` : ""}
    </Notice>
  );
}

function PendingView({ p }: { p: PendingReply }) {
  return (
    <article className="msg assistant" aria-busy={!p.error} aria-label="Resposta em andamento">
      <MentorAvatar />
      <div className="msg-who">
        Mentor <span className="msg-meta">{p.text ? "escrevendo…" : "pensando…"}</span>
      </div>
      <ToolChips tools={p.tools} />
      {p.wait && <WaitView wait={p.wait} />}
      {p.text ? (
        <Markdown text={p.text} />
      ) : (
        !p.wait &&
        !p.error && (
          <span className="typing" role="status" aria-label="O mentor está pensando">
            <span />
            <span />
            <span />
          </span>
        )
      )}
      {p.error && <Notice tone="error">{p.error}</Notice>}
    </article>
  );
}

function AuditBox({ audit }: { audit: { verdict: AuditVerdict; reasons: string[] } }) {
  const verdict = AUDIT_VERDICT[audit.verdict];
  const tone = audit.verdict === "PASSA" ? "good" : audit.verdict === "BLOQUEAR" ? "critical" : "warning";
  return (
    <div className={`verdict ${tone}`} role={audit.verdict === "BLOQUEAR" ? "alert" : "status"}>
      <span className="verdict-mark" aria-hidden="true">
        <Icon name={audit.verdict === "PASSA" ? "shieldCheck" : "alert"} />
      </span>
      <div className="small">
        <strong>
          Auditor: {verdict.label}. {verdict.help}
        </strong>
        {audit.reasons.length > 0 && (
          <ul className="bullets" style={{ marginTop: 6 }}>
            {audit.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function AgentOutputs({ agents }: { agents: AgentState[] }) {
  return (
    <div className="agent-outputs">
      {agents.map((a) => (
        <article key={a.role} className="agent-out" aria-labelledby={`agent-${a.role}`}
          style={{ ["--c" as string]: (AGENT_META[a.role] ?? AGENT_META.diagnostico).color } as CSSProperties}>
          <div className="row between">
            <h3 id={`agent-${a.role}`}>{a.label}</h3>
            <span className="row tiny muted" style={{ gap: 6 }}>
              <span className={`status-dot ${a.status}`} aria-hidden="true" />
              {AGENT_STATUS[a.status]}
            </span>
          </div>
          <ToolChips tools={a.tools} />
          {a.text ? <Markdown text={a.text} /> : <p className="tiny muted">Sem texto ainda.</p>}
        </article>
      ))}
    </div>
  );
}

const AGENT_STATUS: Record<AgentState["status"], string> = {
  waiting: "Aguardando",
  running: "Analisando",
  done: "Concluído",
  error: "Com erro",
};

/** Cronômetro do painel: atualiza enquanto ele roda; congela no fim. */
function useElapsed(run: PanelRun): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (run.finished) return;
    const t = window.setInterval(() => setNow(Date.now()), 100);
    return () => window.clearInterval(t);
  }, [run.finished]);
  return (run.endedAt ?? now) - run.startedAt;
}

/** O painel de especialistas no formato "handoff": quem está trabalhando, progresso e registro. */
function Handoff({ run, onStop }: { run: PanelRun; onStop?: () => void }) {
  const elapsed = useElapsed(run);
  const specialists = run.agents;
  const doneCount = specialists.filter((a) => a.status === "done" || a.status === "error").length;
  const synthesizing = !!run.synthesis && !run.audit && !run.finished;
  const coordState: AgentState["status"] = run.audit || run.finished ? (run.synthesis ? "done" : "waiting") : synthesizing ? "running" : "waiting";
  const auditState: AgentState["status"] = run.audit ? (run.audit.verdict === "BLOQUEAR" ? "error" : "done") : "waiting";

  // Progresso: especialistas até 60%, síntese até 85%, auditoria 95%, fim 100%.
  const pct = run.finished && !run.error
    ? 100
    : run.audit
      ? 95
      : run.synthesis
        ? 75
        : specialists.length
          ? 8 + (doneCount / specialists.length) * 52
          : 4;
  const running = specialists.find((a) => a.status === "running");
  const actor = run.error
    ? { name: "Painel", color: "var(--critical)", text: "interrompido" }
    : run.finished
      ? { name: "Painel", color: "var(--good)", text: "concluído" }
      : run.wait
        ? { name: "Painel", color: "var(--warning)", text: run.wait.kind === "queued" ? "na fila" : "aguardando o limite da assinatura" }
        : synthesizing
          ? { name: "Coordenador", color: AGENT_META.coordenador.color, text: "consolidando a síntese" }
          : running
            ? { name: running.label, color: AGENT_META[running.role]?.color ?? "var(--series-1)", text: "analisando" }
            : { name: "Coordenador", color: AGENT_META.coordenador.color, text: "montando o painel" };
  const dot = run.error ? "error" : run.finished ? "done" : run.wait ? "warning" : "running";

  const tiles: { key: string; label: string; meta: (typeof AGENT_META)[keyof typeof AGENT_META]; status: AgentState["status"] }[] = [
    ...specialists.map((a) => ({ key: a.role, label: a.label, meta: AGENT_META[a.role] ?? AGENT_META.diagnostico, status: a.status })),
    { key: "coordenador", label: "Coordenador", meta: AGENT_META.coordenador, status: coordState },
    { key: "auditor", label: "Auditor", meta: AGENT_META.auditor, status: auditState },
  ];

  return (
    <section className="panel handoff" aria-label="Painel de especialistas">
      <div className="panel-head">
        <div className="row" style={{ gap: 10 }}>
          <h2>Painel de especialistas</h2>
          {specialists.length > 0 && <Tag>{plural(specialists.length, "especialista", "especialistas")}</Tag>}
        </div>
        <span className="row" style={{ gap: 9 }}>
          <span className="mono muted" aria-label={`Tempo decorrido: ${seconds(elapsed)}`}>{seconds(elapsed)}</span>
          <span className={`status-dot ${dot}`} aria-hidden="true" />
        </span>
      </div>
      <div className="panel-body">
        <div className="task-line">
          <span className="eyebrow">Pergunta</span>
          <span className="task-text">{run.question}</span>
        </div>
        <hr className="section-sep" />
        <ol className="agents" aria-label="Especialistas">
          {tiles.map((t) => (
            <li key={t.key} className={`agent ${t.status}`} data-agent={t.key}
              style={{ ["--c" as string]: t.meta.color } as CSSProperties}>
              <span className="agent-tile" aria-hidden="true">
                <Icon name={t.meta.icon} />
                {(t.status === "done" || t.status === "error") && (
                  <span className="agent-badge">
                    <Icon name={t.status === "error" ? "x" : "check"} />
                  </span>
                )}
              </span>
              <span className="agent-name">{t.label}</span>
              <span className="agent-role">{t.meta.role}</span>
              <span className="visually-hidden">: {AGENT_STATUS[t.status]}</span>
            </li>
          ))}
        </ol>
        <div className="handoff-track" aria-hidden="true" style={{ marginTop: 16 }}>
          <span style={{ width: `${pct}%` }} />
          <i style={{ left: `${pct}%`, ["--c" as string]: actor.color } as CSSProperties} />
        </div>
        <hr className="section-sep" />
        <div className="row between" style={{ marginBottom: 4 }}>
          <span className="eyebrow">Registro</span>
          <span className="tag plain">{plural(run.log.length, "evento", "eventos")}</span>
        </div>
        <ol className="log" aria-label="Registro do painel">
          {run.log.slice(-8).map((e) => (
            <li key={e.id}>
              <span className="log-t">{seconds(e.t)}</span>
              <span className="log-dot" style={{ ["--c" as string]: e.color } as CSSProperties} aria-hidden="true" />
              <span>
                <strong>{e.actor}</strong> {e.text}
              </span>
            </li>
          ))}
        </ol>
        {run.wait && <div style={{ marginTop: 12 }}><WaitView wait={run.wait} /></div>}
      </div>
      <div className="panel-foot">
        <span>
          <strong style={{ color: "var(--ink)" }}>{actor.name}</strong> · {actor.text}
        </span>
        {onStop && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={onStop}>
            <Icon name="pause" />
            Parar de acompanhar
          </button>
        )}
      </div>
    </section>
  );
}

function PanelView({ run, compact, onStop }: { run: PanelRun; compact: boolean; onStop?: () => void }) {
  const verdict = run.audit ? AUDIT_VERDICT[run.audit.verdict] : null;
  if (compact) {
    // A síntese já aparece como mensagem salva; aqui ficam o veredito e os bastidores.
    return (
      <section className="stack" aria-label="Bastidores do painel">
        <Handoff run={run} />
        {run.audit && <AuditBox audit={run.audit} />}
        {run.agents.length > 0 && (
          <details>
            <summary>Ver a análise de cada especialista ({run.agents.length})</summary>
            <AgentOutputs agents={run.agents} />
          </details>
        )}
        {run.error && <Notice tone="error">{run.error}</Notice>}
      </section>
    );
  }
  return (
    <section className="stack" aria-label="Painel de especialistas em andamento">
      <div className="msg user">
        <div style={{ whiteSpace: "pre-wrap" }}>{run.question}</div>
      </div>
      <Handoff run={run} onStop={onStop} />
      <BrowserView frame={run.frame} />
      {(run.synthesis || run.audit) && (
        <Card className="accent" eyebrow="Coordenador" title="Síntese"
          aside={
            verdict ? (
              <Badge tone={verdict.tone} icon={verdict.tone === "good" ? "shieldCheck" : undefined}>
                Auditor: {verdict.label}
              </Badge>
            ) : (
              <span className="tag">Auditor revisando…</span>
            )
          }>
          <div className="stack">
            {run.synthesis ? <Markdown text={run.synthesis} /> : <Loading label="Consolidando…" />}
            {run.audit && <AuditBox audit={run.audit} />}
          </div>
        </Card>
      )}
      {run.agents.some((a) => a.text) && (
        <details>
          <summary>Ver a análise de cada especialista ({run.agents.length})</summary>
          <AgentOutputs agents={run.agents} />
        </details>
      )}
      {run.error && <Notice tone="error">{run.error}</Notice>}
    </section>
  );
}
