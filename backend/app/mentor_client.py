"""Cliente do worker do mentor (socket Unix) usado pelo web app."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

STREAM_LIMIT = 4 * 1024 * 1024


class MentorClient:
    def __init__(self, socket_path: Path):
        self.socket_path = socket_path

    async def stream(self, request: dict) -> AsyncIterator[dict]:
        try:
            reader, writer = await asyncio.open_unix_connection(str(self.socket_path), limit=STREAM_LIMIT)
        except (FileNotFoundError, ConnectionRefusedError, PermissionError):
            yield {"type": "error", "kind": "network", "message": "O mentor está indisponível no momento."}
            return
        try:
            writer.write(json.dumps(request, ensure_ascii=False).encode() + b"\n")
            await writer.drain()
            async for line in reader:
                if line.strip():
                    yield json.loads(line)
        finally:
            writer.close()

    async def call(self, request: dict, timeout: float = 15) -> dict:
        async def last() -> dict:
            final = {"type": "error", "kind": "network", "message": "Sem resposta do mentor."}
            async for event in self.stream(request):
                final = event
            return final
        try:
            return await asyncio.wait_for(last(), timeout=timeout)
        except asyncio.TimeoutError:
            return {"type": "error", "kind": "timeout", "message": "O mentor demorou para responder."}
