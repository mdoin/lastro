// SPDX-License-Identifier: AGPL-3.0-or-later
/** Galeria de desenvolvimento dos mascotes (só existe em `npm run dev`; fora do build de produção). */
import { AgentAvatar, type AvatarState } from "../components/AgentAvatar";
import { MASCOTS } from "../components/mascots";
import { EXPRESSION_LABEL, type Expression } from "../lib/expressions";

const SIZES = [24, 32, 48, 64, 96];

function Strip({ tone, state = "idle" }: { tone: "light" | "dark"; state?: AvatarState }) {
  return (
    <div data-theme={tone} className={`mascot-strip ${tone}`}>
      {Object.values(MASCOTS).map((m) => (
        <figure key={m.id}>
          <div className="mascot-sizes">
            {SIZES.map((s) => (
              <AgentAvatar key={s} id={m.id} size={s} state={state} />
            ))}
          </div>
          <figcaption>{m.name}</figcaption>
        </figure>
      ))}
    </div>
  );
}

export function MascotGallery() {
  return (
    <main className="mascot-gallery">
      <h1>Mascotes do Lastro · galeria de desenvolvimento</h1>
      <p>Lado a lado em 24, 32, 48, 64 e 96 px, sobre fundo claro e escuro.</p>
      <Strip tone="light" />
      <Strip tone="dark" />
      <h2>Lado a lado (96 px)</h2>
      <div data-theme="light" className="mascot-strip light lineup">
        {Object.values(MASCOTS).map((m) => (
          <AgentAvatar key={m.id} id={m.id} size={96} />
        ))}
      </div>
      <div data-theme="dark" className="mascot-strip dark lineup">
        {Object.values(MASCOTS).map((m) => (
          <AgentAvatar key={m.id} id={m.id} size={96} />
        ))}
      </div>
      <h2>Expressões na reunião (72 px)</h2>
      <div data-theme="light" className="mascot-strip light expr-grid">
        <span />
        {(Object.keys(EXPRESSION_LABEL) as Expression[]).map((e) => <b key={e} className="expr-head">{EXPRESSION_LABEL[e]}</b>)}
        {Object.values(MASCOTS).flatMap((m) => [
          <b key={`${m.id}-n`} className="expr-head">{m.name}</b>,
          ...(Object.keys(EXPRESSION_LABEL) as Expression[]).map((e) => <AgentAvatar key={`${m.id}-${e}`} id={m.id} size={72} expression={e} />),
        ])}
      </div>
      <h2>Estados: pensando e começando a responder; e id desconhecido</h2>
      <div className="mascot-strip light lineup">
        <AgentAvatar id="analista" size={64} state="thinking" />
        <AgentAvatar id="economista" size={64} state="speaking" />
        <AgentAvatar id="lastro" size={64} />
        <AgentAvatar id="desconhecido" label="Agente Novo" size={64} />
      </div>
      <style>{`
        .mascot-gallery { padding: 24px; display: grid; gap: 16px; font-family: var(--font-sans); }
        .mascot-strip { display: flex; flex-wrap: wrap; gap: 20px; padding: 20px; border-radius: 14px; }
        .mascot-strip.light { background: #f4f4f2; color: #121211; --mascot-outline: initial; }
        .mascot-strip.dark { background: #121211; color: #f4f4f2; --mascot-outline: #d8d4ca; }
        .mascot-strip.dark .agent-avatar { --mascot-outline: #d8d4ca; }
        .mascot-strip.light .agent-avatar { --mascot-outline: initial; }
        .mascot-strip figure { margin: 0; display: grid; gap: 6px; justify-items: center; }
        .mascot-sizes { display: flex; align-items: flex-end; gap: 10px; }
        .lineup { align-items: flex-end; }
        .expr-grid { display: grid; grid-template-columns: 120px repeat(12, 72px); gap: 8px; align-items: center; }
        .expr-head { font-size: 11px; }
      `}</style>
    </main>
  );
}
