# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turnos do chat e do painel rodando em segundo plano.

O turno pertence ao servidor, não à conexão do navegador: se a aba fechar, a
resposta continua e é salva. Quem estiver ouvindo recebe todos os eventos desde
o início (replay) e depois os novos, até o fim.
"""

import asyncio
import logging
import sqlite3
from dataclasses import dataclass, field

from . import store
from .mentor_client import MentorClient

log = logging.getLogger("lastro.turns")
HISTORY_FOR_HANDOFF = 20


@dataclass
class Turn:
    conversation_id: str
    events: list = field(default_factory=list)
    finished: bool = False
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def publish(self, event: dict) -> None:
        async with self.changed:
            self.events.append(event)
            self.changed.notify_all()

    async def close(self) -> None:
        async with self.changed:
            self.finished = True
            self.changed.notify_all()

    async def subscribe(self):
        index = 0
        while True:
            async with self.changed:
                await self.changed.wait_for(lambda: index < len(self.events) or self.finished)
                pending, done = self.events[index:], self.finished
            for event in pending:
                yield event
            index += len(pending)
            if done and index >= len(self.events):
                return


class ConversationBusy(Exception):
    pass


class TurnManager:
    def __init__(self, conn: sqlite3.Connection, mentor: MentorClient):
        self.conn, self.mentor = conn, mentor
        self.active: dict[str, Turn] = {}
        self._tasks: set[asyncio.Task] = set()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def start_chat(self, conv_id: str, text: str) -> Turn:
        if conv_id in self.active:
            raise ConversationBusy()
        conv = store.get_conversation(self.conn, conv_id)
        history = store.list_messages(self.conn, conv_id)[-HISTORY_FOR_HANDOFF:]
        store.add_message(self.conn, conv_id, "user", text)
        turn = Turn(conv_id)
        self.active[conv_id] = turn
        request = {"op": "turn", "conversation_id": conv_id, "text": text,
                   "session_id": conv.get("claude_session_id"), "session_connection": conv.get("session_connection"),
                   "history": [{"role": m["role"], "content": m["content"]} for m in history],
                   **store.ai_route(self.conn, "mentor")}
        self._spawn(self._run_chat(turn, request))
        return turn

    async def _run_chat(self, turn: Turn, request: dict) -> None:
        text, tools = "", []
        try:
            async for event in self.mentor.stream(request):
                kind = event.get("type")
                if kind == "delta":
                    text += event["text"]
                elif kind == "tool":
                    tools.append({"name": event["name"], "input": event.get("input", {})})
                if kind == "done":
                    if event.get("session_id"):
                        store.set_provider_session(self.conn, turn.conversation_id, event["session_id"],
                                                   event.get("connection"))
                    status = "interrupted" if event.get("status") == "interrupted" else "ok"
                    message = store.add_message(self.conn, turn.conversation_id, "assistant",
                                                event.get("text") or text, status=status, tools=event.get("tools") or tools)
                    await turn.publish({"type": "done", "message": message})
                    return
                if kind == "error":
                    content = (event.get("partial_text") or text).strip()
                    store.add_message(self.conn, turn.conversation_id, "assistant",
                                      (content + "\n\n" if content else "") + f"_{event.get('message')}_",
                                      status="error", tools=tools)
                    await turn.publish({"type": "error", "kind": event.get("kind", "internal"), "message": event.get("message")})
                    return
                await turn.publish(event)
            await turn.publish({"type": "error", "kind": "network", "message": "A conexão com o mentor caiu."})
        except Exception:  # noqa: BLE001
            log.exception("turno do chat falhou")
            await turn.publish({"type": "error", "kind": "internal", "message": "Erro interno ao falar com o mentor."})
        finally:
            self.active.pop(turn.conversation_id, None)
            await turn.close()

    def start_panel(self, question: str, conv_id: str | None) -> Turn:
        if conv_id is None:
            conv_id = store.create_conversation(self.conn, f"Painel: {question[:60]}", kind="panel")["id"]
        if conv_id in self.active:
            raise ConversationBusy()
        store.add_message(self.conn, conv_id, "user", question)
        turn = Turn(conv_id)
        self.active[conv_id] = turn
        self._spawn(self._run_panel(turn, {"op": "panel", "question": question, **store.ai_route(self.conn, "mentor")}))
        return turn

    async def _run_panel(self, turn: Turn, request: dict) -> None:
        try:
            async for event in self.mentor.stream(request):
                kind = event.get("type")
                if kind == "done":
                    audit = event.get("audit") or {}
                    footer = ""
                    if audit:
                        reasons = "\n".join(f"- {r}" for r in audit.get("reasons", []))
                        footer = f"\n\n---\n**Parecer do Auditor: {audit.get('verdict')}**\n{reasons}"
                    message = store.add_message(self.conn, turn.conversation_id, "assistant", (event.get("text") or "") + footer,
                                                tools=[{"name": f"painel:{r}", "input": {}} for r in (event.get("reports") or {})],
                                                audit=audit or None)
                    await turn.publish({"type": "done", "message": message, "conversation_id": turn.conversation_id})
                    return
                if kind == "error":
                    store.add_message(self.conn, turn.conversation_id, "assistant", f"_{event.get('message')}_", status="error")
                    await turn.publish({"type": "error", "kind": event.get("kind", "internal"), "message": event.get("message")})
                    return
                await turn.publish(event)
            await turn.publish({"type": "error", "kind": "network", "message": "A conexão com o mentor caiu."})
        except Exception:  # noqa: BLE001
            log.exception("painel falhou")
            await turn.publish({"type": "error", "kind": "internal", "message": "Erro interno no painel."})
        finally:
            self.active.pop(turn.conversation_id, None)
            await turn.close()

    async def interrupt(self, conv_id: str) -> None:
        await self.mentor.call({"op": "interrupt", "conversation_id": conv_id}, timeout=5)

    async def routine_executor(self, run: dict, routine: dict) -> tuple[str, str]:
        """Executa uma rotina no mentor e devolve (status, texto) para o agendador."""
        if routine["use_panel"]:
            request = {"op": "panel", "question": routine["instruction"]}
        else:
            request = {"op": "ephemeral", "role": "rotina", "text": f"Rotina: {routine['name']}\n\n{routine['instruction']}"}
        request.update(store.ai_route(self.conn, "mentor"))
        final = {}
        async for event in self.mentor.stream(request):
            final = event
        if final.get("type") == "done":
            return ("quiet" if final.get("quiet") else "succeeded"), final.get("text") or ""
        return "failed", final.get("message") or "A rotina não terminou."
