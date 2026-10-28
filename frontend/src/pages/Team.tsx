// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  addFact,
  addParticipant,
  cancelRun,
  closeRun,
  createTeamConversation,
  decideFact,
  deleteNote,
  deleteTeamConversation,
  draftFromMessage,
  getAgents,
  getTeamConversation,
  getTeamConversations,
  getTeamMemory,
  getTeamMessages,
  getTeamRuns,
  putProfile,
  removeParticipant,
  renameTeamConversation,
  sendTeamMessage,
  teamStreamUrl,
} from "../api/endpoints";
import { ACCEPT, uploadDocument } from "../api/ledger";
import { getRadarLink } from "../api/radar";
import type { Agent, RunStep, TeamConversation, TeamEvent, TeamMessage, TeamRun } from "../api/types";
import { AgentAvatar, type AvatarState } from "../components/AgentAvatar";
import { CaptureNotice } from "../components/CaptureNotice";
import { AgentPanel, CouncilMeeting, STANCE_LABEL, VerdictView } from "../components/Council";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { Badge, ErrorNotice, Loading, Notice, Segmented } from "../components/ui";
import { formatDate, formatDateTime } from "../lib/dates";
import { MODE_LABEL, researchLabel, seats, threadBlocks, type ThreadBlock } from "../lib/council";
import { applyMention, filterCandidates, linkMentions, mentionAt, splitMentions, type MentionQuery } from "../lib/mentions";
import { canRecord, visibleAudit } from "../lib/messageControls";
import { maybeMask } from "../lib/privacy";
import { useAsync } from "../lib/useAsync";
import "../styles/team.css";
import "../styles/council.css";

const ACTIVE: TeamRun["status"][] = ["queued", "running"];
const VERDICT_TONE = { PASSA: "good", "PASSA COM RESSALVAS": "warning", REPROVA: "critical", REVISAR: "warning", BLOQUEAR: "critical" } as const;

type AgentMap = Record<string, Agent>;

interface Live {
  runs: Record<string, TeamRun>;
  steps: Record<string, Record<string, Partial<RunStep> & { agent_id: string; text?: string; wait?: string; tool?: string; frame?: { image: string; url: string } }>>;
}

/** Prévia de uma linha: sem marcação de Markdown. */
const plain = (text?: string) => (text ?? "").replace(/[*_#>`]+/g, "").trim();

const newId = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);

function agentName(agents: AgentMap, id: string | null | undefined): string {
  if (!id) return "Você";
  if (id === "lastro") return "Lastro";
  return agents[id]?.name ?? "Agente";
}

/** Mascote do agente (o nome sempre aparece ao lado, então o avatar é decorativo para leitores de tela). */
function Avatar({ id, agents, size = 32, state }: { id: string; agents: AgentMap; size?: number; state?: AvatarState }) {
  return <AgentAvatar id={id} size={size} state={state} decorative className="team-avatar" label={agents[id]?.name} />;
}

function convLabel(c: TeamConversation, agents: AgentMap): string {
  if (c.channel === "direct") return agentName(agents, c.agent_id);
  return c.title;
}

// ---------------------------------------------------------------- página

export function TeamPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const agentsQ = useAsync(getAgents, []);
  const convs = useAsync(getTeamConversations, []);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const agents = useMemo<AgentMap>(() => Object.fromEntries((agentsQ.data ?? []).map((a) => [a.id, a])), [agentsQ.data]);

  async function openDirect(agentId: string) {
    const existing = convs.data?.find((c) => c.channel === "direct" && c.agent_id === agentId);
    if (existing) return navigate(`/mentor/${existing.id}`);
    const conv = await createTeamConversation({ channel: "direct", agent_id: agentId });
    convs.setData((prev) => [conv, ...(prev ?? [])]);
    navigate(`/mentor/${conv.id}`);
  }

  async function create(channel: "group" | "council", title?: string, participants?: string[]) {
    const conv = await createTeamConversation({ channel, title, participants });
    convs.setData((prev) => [conv, ...(prev ?? [])]);
    navigate(`/mentor/${conv.id}`);
  }

  return (
    <div className="team" data-view={conversationId ? "chat" : "list"}>
      <aside className="team-list" aria-label="Mentor e especialistas">
        <TeamList
          agents={agentsQ.data ?? []}
          agentMap={agents}
          convs={convs.data ?? []}
          loading={convs.loading && !convs.data}
          current={conversationId}
          onDirect={(id) => void openDirect(id)}
          onCreate={(ch, t, p) => void create(ch, t, p)}
          onMemory={() => setMemoryOpen(true)}
        />
        <ErrorNotice error={convs.error ?? agentsQ.error} onRetry={convs.reload} />
      </aside>
      <section className="team-chat" aria-label="Conversa">
        {conversationId ? (
          <ChatView
            key={conversationId}
            id={conversationId}
            agents={agents}
            onDirect={(agent) => void openDirect(agent)}
            onChanged={() => void convs.reload()}
            onDeleted={() => {
              void convs.reload();
              navigate("/mentor");
            }}
          />
        ) : (
          <div className="team-empty">
            <Avatar id="mentor" agents={agents} size={48} />
            <h2>Sua equipe financeira</h2>
            <p className="muted">
              Converse com o Mentor ou direto com um especialista, monte grupos e convoque o Conselho do Lastro.
              Ninguém aqui movimenta dinheiro nem decide por você.
            </p>
            <button type="button" className="btn btn-primary" onClick={() => void openDirect("mentor")}>
              <Icon name="chat" /> Conversar com o Bento
            </button>
          </div>
        )}
      </section>
      {memoryOpen && <MemorySheet agents={agents} onClose={() => setMemoryOpen(false)} />}
    </div>
  );
}

// ---------------------------------------------------------------- lista

function TeamList(props: {
  agents: Agent[];
  agentMap: AgentMap;
  convs: TeamConversation[];
  loading: boolean;
  current: string | undefined;
  onDirect: (id: string) => void;
  onCreate: (channel: "group" | "council", title?: string, participants?: string[]) => void;
  onMemory: () => void;
}) {
  const { agents, agentMap, convs, current } = props;
  const [newGroup, setNewGroup] = useState(false);
  const [filter, setFilter] = useState("");
  const latestDirect = (id: string) => convs.find((c) => c.channel === "direct" && c.agent_id === id);
  const groups = convs.filter((c) => c.channel === "group");
  const councils = convs.filter((c) => c.channel === "council");
  const history = convs.filter((c) => c.title.toLowerCase().includes(filter.toLowerCase()) ||
    (c.last_message ?? "").toLowerCase().includes(filter.toLowerCase()));

  const row = (c: TeamConversation, icon: string, label: string) => (
    <Link key={c.id} to={`/mentor/${c.id}`} className="team-row" aria-current={c.id === current ? "true" : undefined}>
      <Avatar id={icon} agents={agentMap} />
      <span className="team-row-text">
        <span className="team-row-title">{label}</span>
        <span className="team-row-sub">{plain(c.last_message) || "Sem mensagens ainda"}</span>
      </span>
      <span className="team-row-time">{formatDate(c.updated_at)}</span>
    </Link>
  );

  return (
    <div className="team-list-inner">
      <div className="team-list-head">
        <h1>Mentor e especialistas</h1>
        <button type="button" className="icon-btn" onClick={props.onMemory} aria-label="Memória financeira e fontes">
          <Icon name="book" />
        </button>
      </div>

      <div className="team-section">
        {agents.map((a) => {
          const conv = latestDirect(a.id);
          return (
            <button key={a.id} type="button" className="team-row" onClick={() => props.onDirect(a.id)}
              aria-current={conv && conv.id === current ? "true" : undefined}>
              <Avatar id={a.id} agents={agentMap} />
              <span className="team-row-text">
                <span className="team-row-title">{a.name}</span>
                <span className="team-row-sub">{plain(conv?.last_message) || a.title}</span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="team-section">
        <div className="team-section-head">
          <span className="eyebrow">Grupos</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setNewGroup((v) => !v)} aria-expanded={newGroup}>
            <Icon name="plus" /> Novo grupo
          </button>
        </div>
        {newGroup && (
          <NewGroupForm agents={agents.filter((a) => a.kind !== "coordinator")} onCancel={() => setNewGroup(false)}
            onCreate={(t, p) => { setNewGroup(false); props.onCreate("group", t, p); }} />
        )}
        {groups.map((c) => row(c, "mentor", c.title))}
        {!groups.length && !newGroup && <p className="tiny muted team-hint">Junte especialistas numa conversa e use @menções.</p>}
      </div>

      <div className="team-section">
        <div className="team-section-head">
          <span className="eyebrow">Conselho do Lastro</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => props.onCreate("council")}>
            <Icon name="plus" /> Nova reunião
          </button>
        </div>
        {councils.map((c) => row(c, "auditor", c.title))}
      </div>

      <details className="team-section">
        <summary className="eyebrow">Histórico ({convs.length})</summary>
        <label className="visually-hidden" htmlFor="team-filter">Filtrar conversas</label>
        <input id="team-filter" className="input" placeholder="Filtrar…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        {props.loading && <Loading />}
        {history.map((c) => row(c, c.channel === "direct" ? c.agent_id ?? "mentor" : "mentor",
          `${convLabel(c, agentMap)}${c.channel === "routine" ? " · rotina" : ""}`))}
      </details>
    </div>
  );
}

function NewGroupForm({ agents, onCreate, onCancel }: { agents: Agent[]; onCreate: (title: string, ids: string[]) => void; onCancel: () => void }) {
  const [title, setTitle] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  return (
    <form className="team-newgroup" onSubmit={(e) => { e.preventDefault(); if (picked.length) onCreate(title.trim() || "Novo grupo", picked); }}>
      <label className="small" htmlFor="group-title">Nome do grupo</label>
      <input id="group-title" className="input" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} placeholder="Ex.: Aposentadoria" />
      <fieldset>
        <legend className="small">Participantes (o Mentor sempre participa)</legend>
        {agents.map((a) => (
          <label key={a.id} className="team-check">
            <input type="checkbox" checked={picked.includes(a.id)}
              onChange={(e) => setPicked((p) => (e.target.checked ? [...p, a.id] : p.filter((x) => x !== a.id)))} />
            {a.name} <span className="muted tiny">{a.title}</span>
          </label>
        ))}
      </fieldset>
      <div className="row">
        <button type="submit" className="btn btn-primary btn-sm" disabled={!picked.length}>Criar grupo</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancelar</button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- conversa

function ChatView({ id, agents, onDirect, onChanged, onDeleted }: {
  id: string; agents: AgentMap; onDirect: (agent: string) => void; onChanged: () => void; onDeleted: () => void;
}) {
  const conv = useAsync(() => getTeamConversation(id), [id]);
  const messages = useAsync(() => getTeamMessages(id), [id]);
  const runsQ = useAsync(() => getTeamRuns(id), [id]);
  const [live, setLive] = useState<Live>({ runs: {}, steps: {} });
  const [replyTo, setReplyTo] = useState<TeamMessage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState(false);
  const [panel, setPanel] = useState<{ run: string; agent: string } | null>(null);
  const [params, setParams] = useSearchParams();
  // Modo apresentação: só muda a tela (esconde navegação e controles, mascara valores). Nada é gravado.
  const presenting = params.get("apresentacao") === "1";
  const masked = presenting && params.get("mascarar") !== "0";
  const navigate = useNavigate();
  const endRef = useRef<HTMLDivElement>(null);
  const c = conv.data;

  const upsert = useCallback((m: TeamMessage) => {
    messages.setData((prev) => {
      const list = prev ?? [];
      return list.some((x) => x.id === m.id) ? list.map((x) => (x.id === m.id ? m : x)) : [...list, m];
    });
  }, [messages]);

  // Fluxo ao vivo. O EventSource reconecta sozinho; cada reconexão traz um "snapshot" e recarregamos as mensagens.
  useEffect(() => {
    const es = new EventSource(teamStreamUrl(id));
    es.onmessage = () => undefined;
    const on = (type: TeamEvent["type"], fn: (ev: TeamEvent) => void) =>
      es.addEventListener(type, (e) => fn({ type, ...JSON.parse((e as MessageEvent).data) } as TeamEvent));
    on("snapshot", (ev) => {
      if (ev.type !== "snapshot") return;
      void messages.reload();
      const runs = Object.fromEntries(ev.runs.map((r) => [r.id, r]));
      const steps: Live["steps"] = {};
      for (const r of ev.runs) {
        steps[r.id] = {};
        for (const s of r.steps ?? []) if (s.status === "running") steps[r.id]![s.step_key] = { ...s, text: ev.partials[r.id]?.[s.step_key]?.text ?? "" };
      }
      setLive({ runs, steps });
    });
    on("message", (ev) => ev.type === "message" && upsert(ev.message));
    on("run", (ev) => {
      if (ev.type !== "run") return;
      setLive((l) => {
        const runs = { ...l.runs, [ev.run.id]: ev.run };
        const steps = { ...l.steps };
        if (!ACTIVE.includes(ev.run.status)) delete steps[ev.run.id];
        return { runs, steps };
      });
      if (!ACTIVE.includes(ev.run.status)) { void runsQ.reload(); onChanged(); }
    });
    const stepUpdate = (ev: TeamEvent) => {
      if (ev.type !== "step" && ev.type !== "delta" && ev.type !== "tool" && ev.type !== "wait" && ev.type !== "frame") return;
      setLive((l) => {
        const run = { ...(l.steps[ev.run_id] ?? {}) };
        const cur = run[ev.step_key] ?? { agent_id: ev.agent_id, text: "" };
        if (ev.type === "step") {
          if (ev.status === "running" || ev.status === "retrying") run[ev.step_key] = { ...cur, status: ev.status, kind: ev.kind ?? cur.kind, text: "" };
          else delete run[ev.step_key];
        } else if (ev.type === "delta") run[ev.step_key] = { ...cur, text: (cur.text ?? "") + ev.text, wait: undefined };
        else if (ev.type === "tool") run[ev.step_key] = { ...cur, tool: ev.name };
        else if (ev.type === "frame") run[ev.step_key] = { ...cur, frame: { image: ev.image, url: ev.url } };
        else if (ev.type === "wait") run[ev.step_key] = { ...cur, wait: ev.kind === "waiting_limit" ? ev.message ?? "Aguardando limite de uso." : "Na fila do serviço…" };
        return { ...l, steps: { ...l.steps, [ev.run_id]: run } };
      });
      if (ev.type === "step") void runsQ.reload();
    };
    (["step", "delta", "tool", "wait", "frame"] as const).forEach((t) => on(t, stepUpdate));
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    document.documentElement.toggleAttribute("data-presentation", presenting);
    return () => document.documentElement.removeAttribute("data-presentation");
  }, [presenting]);

  const setPresentation = (on: boolean, mask = true) => setParams((p) => {
    const next = new URLSearchParams(p);
    if (on) { next.set("apresentacao", "1"); next.set("mascarar", mask ? "1" : "0"); } else { next.delete("apresentacao"); next.delete("mascarar"); }
    return next;
  }, { replace: true });

  const msgs = messages.data ?? [];
  const activeRuns = Object.values(live.runs).filter((r) => ACTIVE.includes(r.status));
  const allRuns = useMemo(() => {
    const known = (runsQ.data ?? []).map((r) => ({ ...r, ...(live.runs[r.id] ?? {}), steps: r.steps }));
    return [...known, ...Object.values(live.runs).filter((r) => !known.some((k) => k.id === r.id))];
  }, [runsQ.data, live.runs]);
  const blocks = useMemo(() => threadBlocks(msgs, allRuns), [msgs, allRuns]);
  const roomRuns = new Set(blocks.flatMap((b) => (b.kind === "council" ? [b.run.id] : [])));
  // Na sala do Conselho o andamento aparece nos lugares de cada participante; aqui só o resto.
  const working = Object.entries(live.steps).filter(([rid]) => !roomRuns.has(rid)).flatMap(([, s]) => Object.entries(s));

  useEffect(() => {
    const nearBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 320;
    if (nearBottom) endRef.current?.scrollIntoView({ block: "end" });
  }, [msgs.length, working.length, working.map(([, s]) => s.text?.length ?? 0).join()]);

  async function saveName(nome: string) {
    try {
      await putProfile({ nome });
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Não foi possível salvar o nome.");
      throw e;
    }
  }

  async function send(text: string, reply?: string) {
    setError(null);
    try {
      const out = await sendTeamMessage(id, { text, client_id: newId(), ...(reply ? { reply_to_id: reply } : {}) });
      upsert(out.message);
      out.notices.forEach(upsert);
      if (out.run) setLive((l) => ({ ...l, runs: { ...l.runs, [out.run!.id]: out.run! } }));
      setReplyTo(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Não foi possível enviar.");
      throw e;
    }
  }

  async function record(messageId: string) {
    try {
      const draft = await draftFromMessage(messageId);
      navigate(`/diario?rascunho=${encodeURIComponent(draft.id)}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Não foi possível preparar o rascunho.");
    }
  }

  async function stop() {
    for (const r of activeRuns) {
      try {
        const updated = await cancelRun(r.id);
        setLive((l) => ({ ...l, runs: { ...l.runs, [updated.id]: updated } }));
      } catch (e) {
        setError(e instanceof ApiError ? e.detail : "Não foi possível interromper.");
      }
    }
  }

  async function closeMeeting() {
    for (const r of activeRuns.filter((x) => x.kind === "council")) {
      try {
        const updated = await closeRun(r.id);
        setLive((l) => ({ ...l, runs: { ...l.runs, [updated.id]: updated } }));
      } catch (e) {
        setError(e instanceof ApiError ? e.detail : "Não foi possível encerrar a deliberação.");
      }
    }
  }

  async function remove() {
    if (!c || !window.confirm(`Apagar a conversa "${convLabel(c, agents)}"? As mensagens serão removidas.`)) return;
    try {
      await deleteTeamConversation(id);
      onDeleted();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Não foi possível apagar.");
    }
  }

  if (conv.error) return <ErrorNotice error={conv.error} onRetry={conv.reload} />;
  if (!c) return <Loading />;

  const people = c.participants.filter((p) => p !== "mentor" || c.channel !== "direct");
  const panelBlock = panel ? blocks.find((b): b is Extract<ThreadBlock, { kind: "council" }> => b.kind === "council" && b.run.id === panel.run) : undefined;
  const panelSeats = panelBlock ? seats({ run: panelBlock.run, steps: panelBlock.run.steps ?? [], live: live.steps[panelBlock.run.id] ?? {}, messages: panelBlock.messages }) : [];
  const panelSeat = panelSeats.find((st) => st.agent === panel?.agent);
  const canCouncil = c.channel === "group" || (c.channel === "direct" && c.agent_id === "mentor");
  const byId = Object.fromEntries(msgs.map((m) => [m.id, m]));
  // Oferta do Bento ainda em aberto: a última, sem mensagem da pessoa depois dela.
  const lastUser = msgs.reduce((at, m, i) => (m.role === "user" ? i : at), -1);
  const offerAt = msgs.reduce((at, m, i) => (m.meta?.council_offer ? i : at), -1);
  const openOffer = offerAt > lastUser ? msgs[offerAt]!.id : undefined;

  return (
    <div className="team-thread">
      <header className="team-chat-head">
        <Link to="/mentor" className="icon-btn team-back" aria-label="Voltar para a lista"><Icon name="chevronRight" style={{ transform: "rotate(180deg)" }} /></Link>
        <Avatar id={c.channel === "direct" ? c.agent_id ?? "mentor" : "mentor"} agents={agents} size={38} />
        <div className="team-chat-title">
          <h2>{convLabel(c, agents)}</h2>
          <p className="tiny muted">
            {c.channel === "direct" ? agents[c.agent_id ?? "mentor"]?.title
              : c.channel === "council" ? "Reunião estruturada: especialistas, síntese e auditoria"
              : people.map((p) => agentName(agents, p)).join(", ")}
          </p>
        </div>
        {c.channel === "group" && (
          <button type="button" className="icon-btn" aria-label="Participantes e nome do grupo" aria-expanded={settings} onClick={() => setSettings((v) => !v)}>
            <Icon name="settings" />
          </button>
        )}
        <button type="button" className="icon-btn" aria-pressed={presenting} onClick={() => setPresentation(!presenting)}
          aria-label={presenting ? "Sair do modo apresentação" : "Modo apresentação"} title={presenting ? "Sair do modo apresentação" : "Modo apresentação"}>
          <Icon name={presenting ? "x" : "monitor"} />
        </button>
        <button type="button" className="icon-btn team-hide-presenting" aria-label="Apagar conversa" onClick={() => void remove()}><Icon name="trash" /></button>
      </header>

      {presenting && (
        <div className="presentation-bar" role="region" aria-label="Modo apresentação">
          <span className="small"><strong>Modo apresentação.</strong> Só a tela muda; nada do que está guardado é alterado.</span>
          <label className="team-check small">
            <input type="checkbox" role="switch" checked={masked} onChange={(e) => setPresentation(true, e.target.checked)} /> Mascarar valores
          </label>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPresentation(false)}>Sair</button>
        </div>
      )}

      <RadarLink conversationId={c.id} />

      {settings && c.channel === "group" && (
        <GroupSettings conv={c} agents={agents} onChange={(next) => { conv.setData(next); onChanged(); }} />
      )}

      <div className="thread team-messages" aria-live="polite" aria-relevant="additions">
        {messages.loading && !msgs.length && <Loading />}
        <ErrorNotice error={messages.error} onRetry={messages.reload} />
        {!msgs.length && !messages.loading && <Intro conv={c} agents={agents} onPick={(t) => void send(t).catch(() => undefined)} />}
        {blocks.map((b) => {
          const item = (m: TeamMessage) => (
            <MessageItem key={m.id} m={m} agents={agents} masked={masked} quoted={m.reply_to_id && m.role === "user" ? byId[m.reply_to_id] : undefined}
              onMention={presenting ? undefined : onDirect}
              onConvene={!presenting && m.id === openOffer ? () => void send("Sim, pode reunir os especialistas.").catch(() => undefined) : undefined}
              onSaveName={presenting ? undefined : saveName}
              onReply={c.channel === "routine" || presenting ? undefined : () => setReplyTo(m)}
              onRecord={!presenting && canRecord(m) ? () => void record(m.id) : undefined}
              onRetry={!presenting && m.status === "error" && m.reply_to_id && byId[m.reply_to_id] ? () => void send(byId[m.reply_to_id!]!.content).catch(() => undefined) : undefined} />
          );
          if (b.kind === "message") return presenting && b.message.kind === "notice" ? null : item(b.message);
          const open = (agent: string) => setPanel({ run: b.run.id, agent });
          return (
            <div key={b.run.id} className="council-block">
              <CouncilMeeting run={b.run} question={b.question} messages={b.messages} live={live.steps[b.run.id] ?? {}} agents={agents}
                masked={masked} presenting={presenting} onOpen={open} selected={panel?.run === b.run.id ? panel.agent : null}
                renderVerdict={(synthesis, participants) => (synthesis.meta?.verdict ? (
                  <VerdictView message={synthesis} verdict={synthesis.meta.verdict} agents={agents} masked={masked} onOpen={open} participants={participants}
                    footer={presenting ? undefined : <MessageFoot m={synthesis} name={agentName(agents, "mentor")} onReply={() => setReplyTo(synthesis)}
                      onRecord={synthesis.status === "ok" ? () => void record(synthesis.id) : undefined} />} />
                ) : item(synthesis))} />
              {!presenting && b.messages.some((m) => m.step_key !== "conselho:sintese") && (
                <details className="council-transcript">
                  <summary className="small">Registro técnico da reunião ({b.messages.filter((m) => m.step_key !== "conselho:sintese").length} mensagens: mapa de posições, auditoria e pareceres completos)</summary>
                  {b.messages.filter((m) => m.step_key !== "conselho:sintese").map(item)}
                </details>
              )}
            </div>
          );
        })}
        {working.map(([key, s]) => {
          // Pesquisa: o rótulo vem da ferramenta que está rodando; o texto da sessão de pesquisa é material interno.
          const searching = researchLabel(key, s);
          const name = agentName(agents, s.agent_id);
          return (
            <article key={key} className={`msg assistant team-typing${searching ? " is-research" : ""}`}
              aria-label={searching ? `${name} está ${searching}` : `${name} está respondendo`}>
              <Avatar id={s.agent_id} agents={agents} state={s.text && !searching ? "speaking" : "thinking"} />
              <div className="msg-who">{name} <span className="msg-meta">{searching ? `${searching}…` : s.text ? "escrevendo…" : s.status === "retrying" ? "tentando de novo…" : "pensando…"}</span></div>
              {s.wait && <p className="tiny muted" role="status">{s.wait}</p>}
              {searching ? <p className="team-research-state small" role="status"><Icon name="search" /> {name} está {searching}…</p>
                : s.text ? <Markdown text={s.text} /> : <span className="typing" role="status"><span /><span /><span /></span>}
              {searching && s.frame && (
                <figure className="team-browser">
                  <img src={`data:image/jpeg;base64,${s.frame.image}`} alt={`Tela do navegador de ${name}`} />
                  <figcaption className="tiny muted">{s.frame.url.replace(/^https?:\/\//, "").split("/")[0]}</figcaption>
                </figure>
              )}
            </article>
          );
        })}
        {activeRuns.some((r) => !roomRuns.has(r.id)) && !working.length && <p className="tiny muted team-queued" role="status">Na fila… a equipe já vai responder.</p>}
        <div ref={endRef} />
      </div>

      {error && <Notice tone="warning" title="Atenção.">{error}</Notice>}

      {panelSeat && panelBlock && (
        <AgentPanel seat={panelSeat} seats={panelSeats} agents={agents} masked={masked} onClose={() => setPanel(null)}
          messages={panelBlock.messages}
          onSelect={(agent) => setPanel({ run: panelBlock.run.id, agent })}
          onReply={presenting || c.channel === "routine" ? undefined : (m) => { setReplyTo(m); setPanel(null); }}
          onAsk={presenting || c.channel === "routine" ? undefined : (agent, text) => send(`@${agents[agent]?.handle ?? agent} ${text}`)}
          auditBadge={(m) => (m.audit ? <AuditBadge audit={m.audit} /> : null)} />
      )}

      {presenting ? null : c.channel === "routine" ? (
        <p className="small muted">Conversa de rotina: só leitura.</p>
      ) : (
        <Composer conv={c} agents={agents} replyTo={replyTo} onCancelReply={() => setReplyTo(null)}
          busy={activeRuns.length > 0} canCouncil={canCouncil} onStop={() => void stop()}
          meeting={activeRuns.some((r) => roomRuns.has(r.id)) ? "active" : blocks.some((b) => b.kind === "council") ? "done" : "none"}
          onCloseMeeting={() => void closeMeeting()}
          onSend={(text) => send(text, replyTo?.id)} />
      )}
    </div>
  );
}

function Intro({ conv, agents, onPick }: { conv: TeamConversation; agents: AgentMap; onPick: (t: string) => void }) {
  const agent = conv.channel === "direct" ? agents[conv.agent_id ?? "mentor"] : undefined;
  const examples = agent?.examples ?? (conv.channel === "council"
    ? ["Quero investir R$ 1.000 por mês durante dez anos. Analisem meu planejamento."]
    : ["@vera, o que você acha do cenário de juros?", "O que vocês acham da minha reserva de emergência?"]);
  return (
    <div className="team-intro">
      <p className="small muted">{agent?.summary ?? (conv.channel === "council"
        ? "Apresente uma decisão: Lia, Caio e Vera analisam em paralelo (Téo entra quando o tema é cripto); Rui e Nina avaliam o que eles disseram; o Bento consolida e a Cora verifica. Toque em qualquer participante para ver o parecer."
        : "Converse à vontade: fale com todos ou chame alguém com @. Para uma análise formal, peça ao Bento para reunir o Conselho.")}</p>
      {agent && <p className="tiny muted">Ferramentas: {agent.tools.join(" · ") || "nenhuma"}</p>}
      <div className="suggestions">
        {examples.map((e) => <button key={e} type="button" className="suggestion" onClick={() => onPick(e)}>{e}</button>)}
      </div>
    </div>
  );
}

/** Texto da pessoa com as @menções a agentes coloridas e clicáveis (abrem a conversa individual). */
function MentionText({ text, agents, onMention }: { text: string; agents: AgentMap; onMention?: (id: string) => void }) {
  return (
    <>
      {splitMentions(text, Object.values(agents)).map((p, i) => (typeof p === "string" ? p : (
        <button key={i} type="button" className="mention-chip" style={{ ["--agent" as string]: p.color }} disabled={!onMention}
          onClick={() => onMention?.(p.id)} aria-label={`${p.name}: abrir conversa individual`}>
          <span aria-hidden="true">@</span>{p.name}
        </button>
      )))}
    </>
  );
}

function MessageItem({ m, agents, quoted, onReply, onRetry, onRecord, onMention, onConvene, onSaveName, masked = false }: {
  m: TeamMessage; agents: AgentMap; quoted?: TeamMessage | undefined; onReply?: () => void; onRetry?: () => void;
  onRecord?: () => void; onMention?: (id: string) => void; onConvene?: () => void;
  onSaveName?: (nome: string) => Promise<void>; masked?: boolean;
}) {
  const [saved, setSaved] = useState(false);
  if (m.kind === "notice" && m.meta?.captures?.length) return <CaptureNotice captures={m.meta.captures} masked={masked} />;
  const suggestion = m.meta?.profile_suggestion;
  if (m.kind === "notice" && suggestion && onSaveName) {
    return (
      <p className="team-notice" role="note">
        {saved ? `Salvo: a equipe vai chamar você de “${suggestion.nome}”.` : m.content}
        {!saved && <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onSaveName(suggestion.nome).then(() => setSaved(true), () => undefined)}>Salvar no perfil</button>}
      </p>
    );
  }
  if (m.kind === "notice") return <p className="team-notice" role="note">{maybeMask(m.content, masked)}</p>;
  if (m.role === "user") {
    return (
      <div className="msg user">
        {quoted && <blockquote className="team-quote">{agentName(agents, quoted.agent_id)}: {quoted.content.slice(0, 140)}</blockquote>}
        <div style={{ whiteSpace: "pre-wrap" }}><MentionText text={maybeMask(m.content, masked)} agents={agents} onMention={onMention} /></div>
      </div>
    );
  }
  const name = agentName(agents, m.agent_id);
  const isMap = m.step_key === "conselho:posicoes";
  const tag = isMap ? "mapa de posições" : m.step_key?.startsWith("conselho:contestacao:") ? "contestação" : "parecer";
  const stance = m.meta?.opinion?.stance;
  // A seção "## Divergências" da síntese vira um destaque próprio (e sai do corpo para não repetir).
  const content = maybeMask(m.content, masked);
  const [before, rest] = m.kind === "message" ? content.split(/##\s*Diverg[^\n]*\n?/i, 2) : [content, undefined];
  const divergences = rest?.split(/\n##\s/)[0]?.trim();
  const linked = (t: string) => linkMentions(t, Object.values(agents));
  const body = <Markdown text={linked(divergences ? `${before ?? ""}${rest!.slice(rest!.indexOf(divergences) + divergences.length)}` : content)} />;
  const respondsTo = m.meta?.chat?.responds_to;
  // menções no texto do agente são links "#agente-<id>": o clique abre a conversa individual com quem foi citado
  const openMention = (e: React.MouseEvent) => {
    const link = (e.target as HTMLElement).closest<HTMLAnchorElement>('a[href^="#agente-"]');
    if (!link) return;
    e.preventDefault();
    onMention?.(link.getAttribute("href")!.slice(8));
  };
  return (
    <article className={`msg assistant${m.status === "error" ? " team-error" : ""}`} aria-label={`Mensagem de ${name}`} onClick={openMention}>
      <Avatar id={m.agent_id ?? "mentor"} agents={agents} />
      <div className="msg-who">
        {name}
        {m.kind === "analysis" && <span className="tag plain">{tag}</span>}
        {stance && <span className="tag plain">posição: {STANCE_LABEL[stance] ?? stance}</span>}
        <span className="msg-meta">{formatDateTime(m.created_at)}</span>
      </div>
      {respondsTo && (
        <p className="team-reacts tiny">↳ respondendo a <MentionText text={`@${agents[respondsTo]?.handle ?? respondsTo}`} agents={agents} onMention={onMention} /></p>
      )}
      {m.kind === "analysis" && !isMap ? (
        <details className="team-analysis"><summary>Ver análise de {name}</summary>{body}</details>
      ) : body}
      {divergences && (
        <div className="team-divergences"><span className="eyebrow">Divergências</span><Markdown text={divergences} /></div>
      )}
      {onConvene && (
        <div className="team-offer">
          <button type="button" className="btn btn-primary btn-sm" onClick={onConvene}><Icon name="layers" /> Reunir os especialistas</button>
          <span className="tiny muted">Abre uma reunião do Conselho com este assunto. Se preferir só conversar, é só seguir escrevendo.</span>
        </div>
      )}
      {/* papo não ganha selo de auditoria limpo; ressalva ou reprovação continuam visíveis (lib/messageControls) */}
      <MessageFoot m={{ ...m, audit: visibleAudit(m) }} name={name} onRetry={onRetry}
        onReply={onReply} onRecord={onRecord} />
    </article>
  );
}

const SOURCE_KIND: Record<string, string> = {
  web: "web", pagina: "página oficial", mercado: "mercado", dados: "seus dados", memoria: "memória", motor: "cálculo",
  especialista: "especialista", diario: "diário",
};

/** Data de publicação como veio (ISO, "20261026T230000Z" do GDELT ou texto livre): mostra o que der para ler. */
function formatPublished(value: string): string {
  const compact = /^(\d{4})(\d{2})(\d{2})T/.exec(value);
  const iso = compact ? `${compact[1]}-${compact[2]}-${compact[3]}` : value.slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? formatDate(iso) : value.slice(0, 30);
}

function MessageFoot({ m, name, onRetry, onReply, onRecord }: {
  m: TeamMessage; name: string; onRetry?: () => void; onReply?: () => void; onRecord?: () => void;
}) {
  const web = m.sources.filter((s) => s.kind === "web");
  const lastFetch = web.map((s) => s.fetched_at ?? "").sort().at(-1);
  return (
      <div className="team-msg-foot">
        {m.audit && <AuditBadge audit={m.audit} />}
        {web.length > 0 && (
          <span className="team-verified tiny" title="Fontes consultadas pelas ferramentas de pesquisa nesta resposta">
            <Icon name="search" /> Consultou {web.length} fonte{web.length > 1 ? "s" : ""} na internet
            {lastFetch && <> · {formatDateTime(lastFetch)}</>}
          </span>
        )}
        {m.sources.length > 0 && (
          <details className="team-sources">
            <summary>Ver fontes ({m.sources.length})</summary>
            <ul>
              {m.sources.map((s, i) => (
                <li key={i}>
                  <span className="tag plain">{SOURCE_KIND[s.kind] ?? s.kind}</span>{" "}
                  {s.url?.startsWith("https://") || s.url?.startsWith("http://")
                    ? <a href={s.url} target="_blank" rel="noreferrer noopener nofollow">{s.label}</a> : s.label}
                  {s.official && <Badge tone="good">fonte oficial</Badge>}
                  {s.kind === "web" && s.source && <span className="tiny muted"> · {s.source}</span>}
                  {s.published_at && <span className="tiny muted"> · publicado {formatPublished(s.published_at)}</span>}
                  {s.reference_date && <span className="tiny muted"> · ref. {formatDate(s.reference_date)}</span>}
                  {s.fetched_at && <span className="tiny muted"> · {s.kind === "web" ? "consultado" : "coletado"} {formatDateTime(s.fetched_at)}</span>}
                  {s.validity === "resultado de busca" && <Badge tone="neutral">só resultado de busca</Badge>}
                  {(s.validity === "desatualizado" || s.validity === "indisponivel") && <Badge tone="warning">{s.validity}</Badge>}
                </li>
              ))}
            </ul>
          </details>
        )}
        {onRetry && <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}><Icon name="refresh" /> Tentar de novo</button>}
        {onReply && <button type="button" className="btn btn-ghost btn-sm" onClick={onReply} aria-label={`Responder a ${name}`}><Icon name="arrow" /> Responder</button>}
        {onRecord && <button type="button" className="btn btn-ghost btn-sm" onClick={onRecord}><Icon name="book" /> Registrar no Diário</button>}
      </div>
  );
}

function AuditBadge({ audit }: { audit: NonNullable<TeamMessage["audit"]> }) {
  const tone = VERDICT_TONE[audit.verdict as keyof typeof VERDICT_TONE] ?? "neutral";
  return (
    <details className="team-audit">
      <summary><Badge tone={tone} icon="shieldCheck">Auditoria: {audit.verdict}</Badge></summary>
      {audit.reasons.length ? <ul className="bullets small">{audit.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        : <p className="small muted">Sem achados. {audit.checked_numbers ? `${audit.checked_numbers} número(s) conferido(s).` : ""}</p>}
    </details>
  );
}

function GroupSettings({ conv, agents, onChange }: { conv: TeamConversation; agents: AgentMap; onChange: (c: TeamConversation) => void }) {
  const [error, setError] = useState<string | null>(null);
  const others = Object.values(agents).filter((a) => !conv.participants.includes(a.id));
  const run = async (fn: () => Promise<TeamConversation>) => {
    try { onChange(await fn()); setError(null); } catch (e) { setError(e instanceof ApiError ? e.detail : "Falhou."); }
  };
  return (
    <div className="team-settings">
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => {
        const t = window.prompt("Nome do grupo", conv.title);
        if (t?.trim()) void run(() => renameTeamConversation(conv.id, t.trim()));
      }}><Icon name="edit" /> Renomear</button>
      <div className="team-chips">
        {conv.participants.map((p) => (
          <span key={p} className="chip">{agentName(agents, p)}
            {p !== "mentor" && <button type="button" className="icon-btn" aria-label={`Remover ${agentName(agents, p)}`} onClick={() => void run(() => removeParticipant(conv.id, p).then(() => getTeamConversation(conv.id)))}><Icon name="x" /></button>}
          </span>
        ))}
        {others.map((a) => (
          <button key={a.id} type="button" className="btn btn-ghost btn-sm" onClick={() => void run(() => addParticipant(conv.id, a.id))}>
            <Icon name="plus" /> {a.name}
          </button>
        ))}
      </div>
      {error && <p className="small" role="alert">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- campo de mensagem

function Composer({ conv, agents, replyTo, onCancelReply, busy, canCouncil, onStop, onSend, meeting = "none", onCloseMeeting }: {
  conv: TeamConversation; agents: AgentMap; replyTo: TeamMessage | null; onCancelReply: () => void; busy: boolean;
  canCouncil: boolean; onStop: () => void; onSend: (text: string) => Promise<void>;
  meeting?: "none" | "active" | "done"; onCloseMeeting?: () => void;
}) {
  const [text, setText] = useState("");
  const [council, setCouncil] = useState(false);
  const [mode, setMode] = useState<"rapida" | "completo" | "debate">("completo");
  const isCouncil = conv.channel === "council";
  const [mention, setMention] = useState<MentionQuery | null>(null);
  const [active, setActive] = useState(0);
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Documento pela conversa: vai para a Caixa de entrada e a Mila responde aqui com os números da leitura.
  async function attach(files: FileList) {
    setUploading(true);
    setUploadError(null);
    try {
      for (const f of Array.from(files)) await uploadDocument(f, conv.id);
    } catch (e) {
      setUploadError(e instanceof ApiError ? e.detail : "Não foi possível enviar o arquivo.");
    } finally {
      setUploading(false);
    }
  }
  const candidates = useMemo(() => {
    if (!mention || (conv.channel !== "group" && conv.channel !== "council")) return [];
    const pool = isCouncil ? Object.values(agents) : conv.participants.map((p) => agents[p]);
    return filterCandidates(pool.filter((a): a is Agent => !!a), mention.query);
  }, [mention, conv, agents]);

  useEffect(() => { if (replyTo) ref.current?.focus(); }, [replyTo]);

  const track = (value: string, caret: number) => { setMention(mentionAt(value, caret)); setActive(0); };

  function pick(a: Agent) {
    if (!mention) return;
    const next = applyMention(text, mention, a.handle);
    setText(next.text);
    setMention(null);
    requestAnimationFrame(() => ref.current?.setSelectionRange(next.caret, next.caret));
    ref.current?.focus();
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const body = text.trim();
    if (!body || sending) return;
    setSending(true);
    try {
      // Na Sala do Conselho: durante a reunião a mensagem vira intervenção; depois, @menção vira pergunta direta;
      // o modo escolhido só vale para uma nova pergunta ao Conselho.
      const prefix = council ? "/conselho " : isCouncil && meeting !== "active" && !body.startsWith("/") && !/(^|\s)@\w/.test(body) && mode !== "completo" ? `/${mode} ` : "";
      await onSend(prefix + body);
      setText("");
      setCouncil(false);
    } catch {
      /* erro já exibido; o texto fica no campo para tentar de novo */
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (candidates.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => (i + 1) % candidates.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => (i - 1 + candidates.length) % candidates.length); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pick(candidates[active]!); return; }
      if (e.key === "Escape") { setMention(null); return; }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void submit(); }
  }

  const placeholder = conv.channel === "group" ? "Mensagem para o grupo — use @ para chamar um especialista"
    : isCouncil && meeting === "active" ? "Intervenha na reunião: pergunte a alguém com @ (ex.: @rui, por que discorda do Caio?)"
    : isCouncil && meeting === "done" ? "Pergunte a um especialista com @, ou apresente uma nova questão ao Conselho"
    : conv.channel === "council" ? "Apresente a decisão para o Conselho"
    : `Mensagem para ${agentName(agents, conv.agent_id)}`;

  return (
    <form className="composer team-composer" onSubmit={(e) => void submit(e)}>
      {replyTo && (
        <div className="team-replying">
          <span className="tiny">Respondendo a <strong>{agentName(agents, replyTo.agent_id)}</strong>: {replyTo.content.slice(0, 90)}…</span>
          <button type="button" className="icon-btn" aria-label="Cancelar resposta" onClick={onCancelReply}><Icon name="x" /></button>
        </div>
      )}
      {candidates.length > 0 && (
        <ul className="team-mentions" role="listbox" aria-label="Especialistas">
          {candidates.map((a, i) => (
            <li key={a.id} role="option" aria-selected={i === active}>
              <button type="button" onMouseDown={(e) => { e.preventDefault(); pick(a); }}>
                <Avatar id={a.id} agents={agents} size={24} /> <strong>@{a.handle}</strong> <span className="tiny muted">{a.title}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {isCouncil && meeting !== "active" && (
        <div className="council-modes">
          <Segmented label="Modo da próxima reunião" value={mode} onChange={setMode}
            options={[{ value: "rapida", label: MODE_LABEL.rapida! }, { value: "completo", label: MODE_LABEL.completo! }, { value: "debate", label: MODE_LABEL.debate! }]} />
          {meeting === "done" && (
            <span className="row" style={{ gap: 6 }}>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onSend("/rodada")}>Nova rodada</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onSend("/revisar")}>Revisar veredito</button>
            </span>
          )}
          {mode === "debate" && <span className="tiny muted">Debate: escreva a hipótese e cite quem examina (ex.: @caio @rui); os papéis a favor e contra são de análise, não crenças.</span>}
        </div>
      )}
      {uploadError && <p className="tiny" role="alert">{uploadError}</p>}
      <label htmlFor="team-text" className="visually-hidden">{placeholder}</label>
      <textarea id="team-text" ref={ref} className="textarea" rows={2} value={text} placeholder={placeholder} maxLength={20000}
        aria-autocomplete="list" aria-expanded={candidates.length > 0}
        onChange={(e) => { setText(e.target.value); track(e.target.value, e.target.selectionStart); }}
        onSelect={(e) => track(e.currentTarget.value, e.currentTarget.selectionStart)}
        onKeyDown={onKeyDown} />
      <div className="composer-row">
        <span className="row" style={{ gap: 8 }}>
          <button type="button" className="icon-btn" aria-label="Anexar extrato, fatura ou comprovante" title="Anexar documento"
            onClick={() => fileRef.current?.click()} disabled={uploading}>
            <Icon name={uploading ? "refresh" : "inbox"} />
          </button>
          <input ref={fileRef} type="file" multiple accept={ACCEPT} className="visually-hidden" tabIndex={-1}
            onChange={(e) => { if (e.target.files?.length) void attach(e.target.files); e.target.value = ""; }} />
        {canCouncil ? (
          <label className="team-check small">
            <input type="checkbox" role="switch" checked={council} onChange={(e) => setCouncil(e.target.checked)} /> Convocar o Conselho
          </label>
        ) : null}
        </span>
        <div className="composer-actions">
          {meeting === "active" && onCloseMeeting && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={onCloseMeeting} title="A fala em curso termina e o Bento dá o veredito">
              <Icon name="check" /><span className="btn-text">Encerrar deliberação</span>
            </button>
          )}
          {busy && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={onStop} aria-label="Interromper execução">
              <Icon name="stop" /><span className="btn-text">Interromper</span>
            </button>
          )}
          <button type="submit" className="btn btn-primary btn-sm" disabled={!text.trim() || sending} aria-label="Enviar">
            <Icon name="arrowUp" /><span className="btn-text">Enviar</span>
          </button>
        </div>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- memória

function MemorySheet({ agents, onClose }: { agents: AgentMap; onClose: () => void }) {
  const mem = useAsync(getTeamMemory, []);
  const [form, setForm] = useState({ key: "", value: "" });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); setError(null); await mem.reload(); } catch (e) { setError(e instanceof ApiError ? e.detail : "Falhou."); }
  };
  const facts = mem.data?.facts ?? [];
  return (
    <>
      <button type="button" className="scrim" aria-label="Fechar" onClick={onClose} />
      <div className="team-sheet" role="dialog" aria-modal="true" aria-label="Memória financeira e fontes">
        <div className="row between"><h2>Memória e fontes</h2><button type="button" className="icon-btn" aria-label="Fechar" onClick={onClose}><Icon name="x" /></button></div>
        {mem.loading && !mem.data && <Loading />}
        <ErrorNotice error={mem.error} onRetry={mem.reload} />
        {error && <p className="small" role="alert">{error}</p>}

        <h3 className="eyebrow">Propostas dos agentes (pendentes)</h3>
        {facts.filter((f) => f.status === "proposed").map((f) => (
          <div key={f.id} className="team-fact">
            <span><strong>{f.key}</strong>: {f.value} <span className="tiny muted">— {f.source.replace("agente:", "")}, {f.note}</span></span>
            <span className="row">
              <button type="button" className="btn btn-primary btn-sm" onClick={() => void act(() => decideFact(f.id, "confirm"))}>Confirmar</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => void act(() => decideFact(f.id, "reject"))}>Descartar</button>
            </span>
          </div>
        ))}
        {!facts.some((f) => f.status === "proposed") && <p className="tiny muted">Nenhuma proposta pendente. Agentes só propõem; quem confirma é você.</p>}

        <h3 className="eyebrow">Fatos confirmados</h3>
        <ul className="team-list-plain">
          {facts.filter((f) => f.status === "confirmed").map((f) => (
            <li key={f.id}><strong>{f.key}</strong>: {f.value} <span className="tiny muted">· fonte {f.source} · {formatDate(f.as_of)}</span></li>
          ))}
        </ul>
        <form className="row" onSubmit={(e) => { e.preventDefault(); void act(() => addFact(form)).then(() => setForm({ key: "", value: "" })); }}>
          <label className="visually-hidden" htmlFor="fact-key">Chave</label>
          <input id="fact-key" className="input" placeholder="chave (ex.: horizonte_meses)" value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} />
          <label className="visually-hidden" htmlFor="fact-value">Valor</label>
          <input id="fact-value" className="input" placeholder="valor" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
          <button type="submit" className="btn btn-secondary btn-sm" disabled={!form.key || !form.value}>Registrar</button>
        </form>
        <details>
          <summary className="small">Histórico de alterações ({facts.filter((f) => f.status !== "confirmed" && f.status !== "proposed").length})</summary>
          <ul className="team-list-plain tiny">
            {facts.filter((f) => f.status === "superseded" || f.status === "rejected").map((f) => (
              <li key={f.id}>{f.key} = {f.value} · {f.status === "superseded" ? "substituído" : "descartado"} · {f.source} · {formatDateTime(f.created_at)}</li>
            ))}
          </ul>
        </details>

        <h3 className="eyebrow">Anotações dos agentes</h3>
        <ul className="team-list-plain">
          {(mem.data?.notes ?? []).map((n) => (
            <li key={n.id} className="team-fact">
              <span><strong>{agentName(agents, n.agent_id)}</strong> <span className="tiny muted">({n.scope === "private" ? "conversa individual" : "só naquela conversa"})</span>: {n.content}</span>
              <button type="button" className="icon-btn" aria-label="Apagar anotação" onClick={() => void act(() => deleteNote(n.id))}><Icon name="trash" /></button>
            </li>
          ))}
        </ul>

        <h3 className="eyebrow">Dados externos</h3>
        <div className="team-market" role="table" aria-label="Séries externas">
          {(mem.data?.market ?? []).map((s) => (
            <div key={s.series_id} role="row">
              <span role="cell">{s.label}<br /><span className="tiny muted">{s.source}</span></span>
              <span role="cell" className="mono">{s.value ? `${s.value} ${s.unit}` : "—"}</span>
              <span role="cell" className="tiny">{s.reference_date ? `ref. ${formatDate(s.reference_date)}` : ""}</span>
              <span role="cell"><Badge tone={s.validity === "valido" ? "good" : s.validity === "desatualizado" ? "warning" : "neutral"}>{s.validity}</Badge></span>
            </div>
          ))}
        </div>
        <p className="tiny muted">Séries históricas coletadas de fontes oficiais, não cotações em tempo real. Ainda não conectadas: {(mem.data?.not_connected ?? []).join(", ")}.</p>
      </div>
    </>
  );
}

/** Conversa aberta a partir do Diário de Oportunidades: mantém o caminho de volta ao registro original. */
function RadarLink({ conversationId }: { conversationId: string }) {
  const link = useAsync(() => getRadarLink(conversationId), [conversationId]);
  if (!link.data?.opportunity_id) return null;
  return (
    <Link to={`/oportunidades/${link.data.opportunity_id}`} className="radar-backlink">
      <Icon name="book" />
      <span>
        Ligada ao Diário de oportunidades: <strong>{link.data.asset_label}</strong>
      </span>
      <Icon name="arrow" />
    </Link>
  );
}
