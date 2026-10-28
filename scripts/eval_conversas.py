# SPDX-License-Identifier: AGPL-3.0-or-later
"""Avaliação comportamental da equipe com o modelo de verdade (docs/CONVERSAS.md, "Identidade comportamental").

Uso: uv run python scripts/eval_conversas.py [--saida relatorio.md] [--cenario 3]

Roda cada cenário num banco temporário, com o orquestrador e o worker reais e o provedor configurado nesta
máquina (por padrão, o Claude Code instalado). Grava as falas publicadas e as medidas de homogeneidade de
team.voice (pares parecidos, aberturas e esqueletos repetidos, autoapresentação, concordância vazia) e quantos
agentes ficaram em silêncio. Não usa modelo para julgar: a leitura das falas é humana, o relatório só ajuda.
Rodar no commit anterior e no atual dá o comparativo antes/depois.
"""
import argparse
import asyncio
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import db, store  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from mentor.worker import MentorWorker  # noqa: E402
from team import voice  # noqa: E402
from team.agents import get  # noqa: E402

EVERYONE = ("planejador", "analista", "economista", "riscos", "comportamental", "cripto", "mila", "auditor")
# (título, sala, participantes, histórico prévio [(papel, agente, texto, dias atrás)], mensagens da pessoa)
SCENARIOS = [
    ("Cumprimento ao grupo", "group", EVERYONE, [], ["Oi, pessoal!"]),
    ("Cansaço", "group", EVERYONE, [], ["Tô cansada hoje, semana puxada."]),
    ("Valorant e eleição (o caso relatado)", "group", EVERYONE, [],
     ["Pessoal, passei o dia jogando Valorant pra não pensar na eleição kkk", "@mila @teo, vocês ficaram quietos hein"]),
    ("Notícia econômica", "group", EVERYONE, [], ["Gente, viram que o desemprego caiu? kkk finalmente uma boa"]),
    ("Piada", "group", EVERYONE, [], ["Pessoal, meu cofrinho tem mais teia de aranha que moeda kkk"]),
    ("Pergunta de investimento", "direct:analista", (), [], ["Tesouro Selic ou CDB de liquidez diária para a reserva?"]),
    ("Chamando a Nina", "group", EVERYONE, [], ["@nina, às vezes compro coisa só pra me animar, é normal?"]),
    ("Questionando o Rui", "group", EVERYONE, [], ["@rui, você não acha que exagera nos riscos às vezes?"]),
    ("Discordância", "group", ("analista", "riscos"), [],
     ["@caio e @rui, bitcoin numa fatia pequena da carteira faz sentido?"]),
    ("Nada a acrescentar", "group", EVERYONE, [], ["Valeu, pessoal, era só isso!"]),
    ("Volta a uma conversa antiga", "direct:planejador", (),
     [("user", None, "Minha reserva hoje é de R$ 9.000,00.", 12),
      ("assistant", "planejador", "Anotado: com seus gastos, isso cobre pouco mais de 2 meses.", 12)],
     ["Voltei! Lembra da reserva?"]),
    ("Reconhecer um erro", "group", ("planejador",),
     [("assistant", "planejador", "Reserva de 3 meses serve para todo mundo.", 1)],
     ["@lia, você disse 3 meses e eu li que o ideal costuma ser 6. Quem tá certo?"]),
]
SNAP = {"as_of": "2026-10-20", "net_monthly_income": "6000.00", "essential_expenses": "3000.00",
        "variable_expenses": "1000.00", "liquid_reserve": "9000.00", "available_this_month": "1500.00", "debts": []}


def worker_stream(worker: MentorWorker):
    async def stream(request: dict):
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(worker.ephemeral(request, queue.put))
        while True:
            event = await queue.get()
            yield event
            if event.get("type") in ("done", "error"):
                break
        await task
    return stream


async def drain(o: Orchestrator):
    while True:
        o.dispatch()
        if not o.active:
            return
        await asyncio.gather(*list(o.active.values()), return_exceptions=True)


async def run_scenario(workdir: Path, worker: MentorWorker, scenario) -> list[str]:
    title, room, participants, history, texts = scenario
    conn = db.connect(workdir / f"{abs(hash(title))}.db")
    db.migrate(conn)
    store.create_snapshot(conn, SNAP)
    store.set_profile(conn, store.OWNER, nome="Ana", tratamento="pode ser informal")
    if room.startswith("direct:"):
        conv = store.create_conversation(conn, title, channel="direct", agent_id=room.split(":")[1])
    else:
        conv = store.create_conversation(conn, title, channel="group")
        for a in ("mentor", *participants):
            store.add_participant(conn, conv["id"], a)
    for role, agent, content, days in history:
        m = store.add_message(conn, conv["id"], role, content, agent_id=agent)
        when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn.execute("UPDATE messages SET created_at = ? WHERE id = ?", (when, m["id"]))
    conn.commit()
    o = Orchestrator(conn, worker_stream(worker), today=date.today, semantic_audit="off")
    lines = [f"## {title}", ""]
    for text in texts:
        o.submit(store.get_conversation(conn, conv["id"]), text)
        before = {m["id"] for m in store.list_messages(conn, conv["id"])}
        await drain(o)
        said = [m for m in store.list_messages(conn, conv["id"])
                if m["id"] not in before and m["role"] == "assistant" and m["kind"] != "notice"]
        steps = [s for r in store.list_runs(conn, conv["id"], limit=1) for s in store.list_steps(conn, r["id"])]
        quiet = len([s for s in steps if s["kind"] == "reply"]) - len(said)
        lines += [f"**Pessoa:** {text}", ""]
        lines += [f"**{get(m['agent_id']).name}:** {m['content'].strip()}  " for m in said if m["agent_id"]]
        h = voice.homogeneity([m["content"] for m in said if m["status"] == "ok"])
        failed = sum(m["status"] != "ok" for m in said)
        lines += ["", f"_medidas: {h} · silêncios/falas retidas: {quiet}"
                      + (f" · falhas do provedor: {failed}" if failed else "") + "_", ""]
    conn.close()
    return lines


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--saida", type=Path)
    parser.add_argument("--cenario", type=int, action="append", help="número do cenário (1–12); repetível")
    args = parser.parse_args()
    chosen = [SCENARIOS[i - 1] for i in args.cenario] if args.cenario else SCENARIOS
    with tempfile.TemporaryDirectory() as tmp:
        worker = MentorWorker(Path(tmp))
        report = ["# Avaliação comportamental da equipe", "", f"Gerado em {datetime.now():%Y-%m-%d %H:%M}.", ""]
        for scenario in chosen:
            report += await run_scenario(Path(tmp), worker, scenario)
    text = "\n".join(report) + "\n"
    if args.saida:
        args.saida.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
