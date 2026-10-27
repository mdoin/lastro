# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prova de conceito do mentor: uma conversa de várias mensagens, com streaming.

Roda como o usuário `mentor` (que tem o login do Claude), por exemplo:
  sudo -u mentor -H env MPA_AGENT_API_TOKEN_FILE=/etc/meu-patrimonio/mentor-token \
    /opt/meu-patrimonio/.venv/bin/python /opt/meu-patrimonio/scripts/mentor_poc.py "pergunta 1" "pergunta 2"
"""
import asyncio
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, ToolUseBlock  # noqa: E402
from claude_agent_sdk.types import StreamEvent  # noqa: E402

from mentor.session import mentor_options  # noqa: E402


async def main(questions):
    workdir = Path.home() / "work"
    workdir.mkdir(exist_ok=True)
    options = mentor_options(workdir=workdir, session_id=str(uuid.uuid4()))
    async with ClaudeSDKClient(options=options) as client:
        for question in questions:
            print(f"\n>>> {question}\n")
            started = time.monotonic()
            first_token = None
            await client.query(question)
            async for message in client.receive_response():
                if isinstance(message, StreamEvent):
                    delta = message.event.get("delta", {}) if message.event.get("type") == "content_block_delta" else {}
                    if delta.get("type") == "text_delta":
                        first_token = first_token or time.monotonic() - started
                        print(delta["text"], end="", flush=True)
                elif isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            print(f"\n[ferramenta] {block.name} {block.input}", flush=True)
                elif isinstance(message, ResultMessage):
                    print(f"\n\n[fim] {message.subtype} · {time.monotonic() - started:.1f}s"
                          f" · primeiro texto em {first_token or 0:.1f}s · erro={message.is_error}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["Olá! Quem é você e o que consegue fazer?"]))
