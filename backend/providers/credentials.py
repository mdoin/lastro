# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conexões de IA desta instalação, guardadas só no worker.

Arquivo JSON gravado de forma atômica com permissão 0600 no volume do worker (`LASTRO_PROVIDERS_FILE`). O web
app, que tem o banco, nunca recebe o segredo de volta: só a visão pública (`public_view`). Credenciais de login
dos executáveis oficiais (Claude Code, Codex) nem passam por aqui: ficam com o próprio CLI.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .base import Connection

VERSION = 1


def mask(value: str | None) -> str | None:
    if not value:
        return None
    return f"…{value[-4:]}" if len(value) >= 16 else "configurada"


class ConnectionStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": VERSION, "connections": {}, "default": None}
        data.setdefault("connections", {})
        data.setdefault("default", None)
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".providers-", suffix=".tmp")
        try:
            os.chmod(tmp, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def list(self) -> list[Connection]:
        return [Connection(**raw) for raw in self._read()["connections"].values()]

    def get(self, conn_id: str) -> Connection | None:
        raw = self._read()["connections"].get(conn_id)
        return Connection(**raw) if raw else None

    def default_id(self) -> str | None:
        return self._read()["default"]

    def save(self, conn: Connection, *, make_default: bool = False) -> None:
        with self._lock:
            data = self._read()
            data["connections"][conn.id] = {"id": conn.id, "type": conn.type, "label": conn.label,
                                            "settings": conn.settings, "secret": conn.secret,
                                            "created_at": conn.created_at}
            if make_default or not data["default"]:
                data["default"] = conn.id
            self._write(data)

    def delete(self, conn_id: str) -> bool:
        with self._lock:
            data = self._read()
            found = data["connections"].pop(conn_id, None) is not None
            if data["default"] == conn_id:
                data["default"] = next(iter(data["connections"]), None)
            self._write(data)
            return found

    def set_default(self, conn_id: str) -> None:
        with self._lock:
            data = self._read()
            if conn_id not in data["connections"]:
                raise KeyError(conn_id)
            data["default"] = conn_id
            self._write(data)


def public_view(conn: Connection, provider, *, default_id: str | None) -> dict:
    """O que pode sair do worker: nunca o segredo, só se existe e os 4 últimos caracteres da chave."""
    return {"id": conn.id, "type": conn.type, "label": conn.label or provider.label,
            "settings": dict(conn.settings), "has_secret": bool(conn.secret),
            "secret_hint": mask(conn.secret.get("api_key")), "configured": provider.is_configured(),
            "capabilities": provider.effective_capabilities().public(), "default": conn.id == default_id}
