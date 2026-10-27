# SPDX-License-Identifier: AGPL-3.0-or-later
"""Login do Claude Code num servidor sem navegador, pelo fluxo da própria Anthropic.

Desenho estudado no OpenBot (só ideias; nenhum código copiado): o worker roda `claude auth login --claudeai`
num terminal virtual (o CLI só mostra o campo de código num terminal), lê o link da página de login da
Anthropic na saída do CLI e o entrega à interface. A pessoa abre o link no próprio aparelho, entra na conta
Claude no site da Anthropic e cola de volta o código que a página mostra; o worker escreve esse código no
terminal do CLI, e quem conclui o OAuth e guarda a credencial é o CLI.

Regras:
- o código colado é segredo: só trafega no corpo da requisição em direção ao worker, nunca volta em resposta,
  nunca vai para log, e só caracteres imprimíveis sem espaço são aceitos (nada de quebras de linha injetadas);
- a saída do CLI também não vai para log nem para a interface (só o link https extraído dela);
- uma tentativa por vez, com prazo; Linux apenas (precisa de `pty`).
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
# Link aceito só depois do fim da linha: um pedaço de saída pode parar no meio do endereço.
LINK = re.compile(r"(https://[^\s\"'<>]+)\r?\n")
CODE = re.compile(r"^[\x21-\x7e]{4,512}$")
URL_WAIT_SECONDS = 30
TOTAL_SECONDS = 600
VERIFY_SECONDS = 90


def supported() -> bool:
    return sys.platform.startswith("linux")


class CodeLogin:
    """Uma tentativa de login. Estados: starting → waiting_code → verifying → done | failed | cancelled."""

    def __init__(self, argv: list[str], env: dict, *, allowed_hosts: tuple[str, ...] = ("claude.ai", "claude.com",
                                                                                        "anthropic.com")):
        self.argv, self.env, self.allowed_hosts = argv, env, allowed_hosts
        self.state = "starting"
        self.url: str | None = None
        self.error: str | None = None
        self.started = time.monotonic()
        self._proc: asyncio.subprocess.Process | None = None
        self._master: int | None = None
        self._buffer = ""
        self._url_ready = asyncio.Event()

    def public(self) -> dict:
        return {"state": self.state, "url": self.url, "error": self.error}

    def _host_ok(self, url: str) -> bool:
        host = re.sub(r"^https://", "", url).split("/", 1)[0].split(":", 1)[0].lower()
        return any(host == h or host.endswith("." + h) for h in self.allowed_hosts)

    def _on_output(self) -> None:
        try:
            chunk = os.read(self._master, 65536)
        except OSError:
            chunk = b""
        if not chunk:
            asyncio.get_running_loop().remove_reader(self._master)
            return
        self._buffer = (self._buffer + ANSI.sub("", chunk.decode("utf-8", "replace")))[-20000:]
        if self.url is None:
            for match in LINK.finditer(self._buffer):
                if self._host_ok(match.group(1)):
                    self.url = match.group(1)
                    self.state = "waiting_code"
                    self._url_ready.set()
                    break

    async def start(self) -> dict:
        if not supported():
            self.state, self.error = "failed", "Login por código só funciona com o worker em Linux. Use a API key ou o terminal."
            return self.public()
        import fcntl
        import pty
        import struct
        import termios

        master, slave = pty.openpty()
        # Terminal largo: o CLI não quebra o link em várias linhas.
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 4000, 0, 0))
        self._master = master
        try:
            self._proc = await asyncio.create_subprocess_exec(*self.argv, stdin=slave, stdout=slave, stderr=slave,
                                                              env=self.env, start_new_session=True)
        except OSError:
            os.close(master)
            self.state, self.error = "failed", "Não foi possível iniciar o CLI."
            return self.public()
        finally:
            os.close(slave)
        asyncio.get_running_loop().add_reader(master, self._on_output)
        asyncio.get_running_loop().create_task(self._deadline())
        try:
            await asyncio.wait_for(self._url_ready.wait(), timeout=URL_WAIT_SECONDS)
        except TimeoutError:
            await self._stop("failed", "O CLI não mostrou o link de login a tempo.")
        return self.public()

    async def submit(self, code: str) -> dict:
        code = (code or "").strip()
        if self.state != "waiting_code":
            return self.public()
        if not CODE.match(code):
            return {**self.public(), "error": "Código inválido: cole exatamente o código mostrado pela página."}
        self.state = "verifying"
        os.write(self._master, code.encode() + b"\r")
        try:
            returncode = await asyncio.wait_for(self._proc.wait(), timeout=VERIFY_SECONDS)
        except TimeoutError:
            await self._stop("failed", "O CLI não confirmou o login. Gere um novo link e tente de novo.")
            return self.public()
        if returncode == 0:
            await self._stop("done", None)
        else:
            await self._stop("failed", "O login não foi concluído (código expirado ou recusado).")
        return self.public()

    async def cancel(self) -> dict:
        if self.state in ("starting", "waiting_code", "verifying"):
            await self._stop("cancelled", None)
        return self.public()

    async def _deadline(self) -> None:
        await asyncio.sleep(TOTAL_SECONDS)
        if self.state in ("starting", "waiting_code", "verifying"):
            await self._stop("failed", "O prazo do login acabou.")

    async def _stop(self, state: str, error: str | None) -> None:
        self.state, self.error = state, error
        if self._proc and self._proc.returncode is None:
            self._proc.kill()
            await self._proc.wait()
        if self._master is not None:
            try:
                asyncio.get_running_loop().remove_reader(self._master)
                os.close(self._master)
            except (OSError, ValueError):
                pass
            self._master = None
        self._buffer = ""  # a saída pode conter dados da sessão: não fica em memória
