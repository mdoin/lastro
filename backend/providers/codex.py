# SPDX-License-Identifier: AGPL-3.0-or-later
"""Codex: o executável oficial da OpenAI (`codex app-server`), com o login do próprio Codex.

Desenho estudado no OpenBot (só ideias; nenhum código copiado): um processo `codex app-server` por conexão,
falando JSON por linha em stdio; quem autentica é o Codex (conta do ChatGPT por device code, ou API key), e a
credencial fica no `CODEX_HOME` do worker, fora do alcance do web app. O Lastro nunca lê esse arquivo.

Isolamento (o app-server tem ferramentas nativas que o Lastro não quer):
- recursos nativos desligados na linha de comando (`shell_tool`, `unified_exec`, apps, plugins, imagens,
  subagentes, busca na web) e sandbox `read-only`;
- política de aprovação `on-request`: tudo que ainda pedir aprovação é recusado (deny por padrão), e qualquer
  pedido do servidor que o Lastro não conhece recebe erro;
- as ferramentas do Lastro entram como ferramentas dinâmicas da thread e passam pela mesma barreira
  (`toolspec.run_tool`) dos outros provedores;
- ambiente mínimo para o processo (nada de tokens do Lastro) e diretório de trabalho vazio.
Integração marcada como experimental: depende de campos `experimentalApi` do app-server.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import shutil
from pathlib import Path

from .base import AgentSession, Emit, Provider, ProviderCapabilities, ProviderError, SessionSpec, TurnOutcome
from .loop import QUIET_TOOL, finalize_quiet
from .toolspec import by_name, run_tool

log = logging.getLogger("lastro.providers.codex")

DISABLED_FEATURES = ("shell_tool", "unified_exec", "apps", "plugins", "image_generation", "multi_agent",
                     "view_image", "skill_search")
CONFIG = ('web_search="disabled"', 'sandbox_mode="read-only"', 'approval_policy="on-request"',
          "analytics.enabled=false")
APPROVALS = {"item/commandExecution/requestApproval": {"decision": "decline"},
             "item/fileChange/requestApproval": {"decision": "decline"},
             "execCommandApproval": {"decision": {"denied": {"rejection": "Lastro: só ferramentas de leitura."}}},
             "applyPatchApproval": {"decision": {"denied": {"rejection": "Lastro: só ferramentas de leitura."}}}}
ENV_KEEP = ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "SYSTEMROOT", "TEMP", "TMP")
LIMIT_ERRORS = {"usageLimitExceeded", "rateLimitExceeded", "sessionBudgetExceeded"}
NETWORK_ERRORS = {"serverOverloaded", "internalServerError", "httpConnectionFailed", "responseStreamConnectionFailed",
                  "responseStreamDisconnected", "responseTooManyFailedAttempts"}


def cli_path() -> str | None:
    return os.environ.get("LASTRO_CODEX_PATH") or shutil.which("codex")


def codex_home() -> Path:
    return Path(os.environ.get("LASTRO_CODEX_HOME") or Path.home() / "codex")


def _error_kind(info) -> str:
    key = next(iter(info), "") if isinstance(info, dict) else (info or "")
    if key in LIMIT_ERRORS:
        return "rate_limit"
    if key == "unauthorized":
        return "auth"
    if key in NETWORK_ERRORS:
        return "network"
    return "internal"


class AppServer:
    """Um processo `codex app-server` e o roteamento das mensagens dele."""

    def __init__(self, argv: list[str], env: dict, tool_handler):
        self.argv, self.env, self.tool_handler = argv, env, tool_handler
        self.proc: asyncio.subprocess.Process | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self.threads: dict[str, asyncio.Queue] = {}
        self.logins: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._reader: asyncio.Task | None = None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def ensure(self) -> None:
        async with self._lock:
            if self.alive:
                return
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *self.argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, env=self.env, limit=16 * 1024 * 1024)
            except OSError:
                raise ProviderError("not_configured", "Não foi possível iniciar o Codex (verifique LASTRO_CODEX_PATH).") from None
            self._reader = asyncio.get_running_loop().create_task(self._read())
            await self.request("initialize", {"clientInfo": {"name": "lastro", "title": "Lastro", "version": "0.3.0"},
                                              "capabilities": {"experimentalApi": True, "requestAttestation": False}},
                               started=True)
            self._send({"method": "initialized"})

    def _send(self, message: dict) -> None:
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")

    async def request(self, method: str, params: dict, *, timeout: float = 60, started: bool = False) -> dict:
        if not started:
            await self.ensure()
        request_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._send({"id": request_id, "method": method, "params": params})
        await self.proc.stdin.drain()
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    async def _read(self) -> None:
        try:
            async for line in self.proc.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(message)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ProviderError("network", "O Codex encerrou."))
            for queue in self.threads.values():
                queue.put_nowait({"method": "lastro/closed", "params": {}})

    async def _dispatch(self, message: dict) -> None:
        if "id" in message and ("result" in message or "error" in message) and "method" not in message:
            future = self._pending.get(message["id"])
            if future and not future.done():
                if "error" in message:
                    detail = str((message["error"] or {}).get("message", ""))[:200]
                    future.set_exception(ProviderError("internal", f"Codex recusou a requisição: {detail}"))
                else:
                    future.set_result(message["result"] or {})
            return
        method, params = message.get("method"), message.get("params") or {}
        if "id" in message:  # pedido do servidor: deny por padrão
            asyncio.get_running_loop().create_task(self._answer(message["id"], method, params))
            return
        if method == "account/login/completed":
            future = self.logins.pop(params.get("loginId") or "", None)
            if future and not future.done():
                future.set_result(params)
            return
        queue = self.threads.get(params.get("threadId") or "")
        if queue is not None:
            queue.put_nowait(message)

    async def _answer(self, request_id, method: str, params: dict) -> None:
        if method == "item/tool/call":
            result = await self.tool_handler(params)
            self._send({"id": request_id, "result": result})
        elif method in APPROVALS:
            log.info("Codex pediu %s; recusado", method)
            self._send({"id": request_id, "result": APPROVALS[method]})
        else:
            log.info("Codex pediu %s; sem suporte no Lastro", method)
            self._send({"id": request_id, "error": {"code": -32601, "message": "Não suportado pelo Lastro."}})
        await self.proc.stdin.drain()

    async def close(self) -> None:
        if self.alive:
            self.proc.stdin.close()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except TimeoutError:
                self.proc.kill()


class CodexSession(AgentSession):
    def __init__(self, provider: "CodexProvider", spec: SessionSpec, thread_id: str):
        self.provider, self.spec = provider, spec
        self.native_id = thread_id
        self.granted = by_name(spec.tools)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.emit: Emit | None = None
        self.outcome: TurnOutcome | None = None
        self.turn_id: str | None = None

    async def handle_tool(self, params: dict) -> dict:
        name = params.get("tool") or ""
        args = params.get("arguments")
        shown = args if isinstance(args, dict) else {}
        if self.outcome is not None:
            self.outcome.tools.append({"name": name, "input": shown})
            self.outcome.quiet = self.outcome.quiet or name == QUIET_TOOL
        if self.emit:
            await self.emit({"type": "tool", "name": name, "input": shown})
        text, is_error = await run_tool(self.granted, name, args if args is not None else {})
        return {"contentItems": [{"type": "inputText", "text": text}], "success": not is_error}

    async def send(self, prompt: str, emit: Emit) -> TurnOutcome:
        out = self.outcome = TurnOutcome(session_id=self.native_id)
        self.emit = emit
        texts: dict[str, str] = {}
        order: list[str] = []
        try:
            started = await self.provider.server.request("turn/start", {
                "threadId": self.native_id, "input": [{"type": "text", "text": prompt, "text_elements": []}],
                **({"effort": self.spec.effort} if self.provider.send_effort else {})})
            self.turn_id = (started.get("turn") or {}).get("id")
            while True:
                message = await self.queue.get()
                method, params = message.get("method"), message.get("params") or {}
                if method == "item/agentMessage/delta":
                    item = params.get("itemId") or ""
                    if item not in texts:
                        texts[item] = ""
                        order.append(item)
                    texts[item] += params.get("delta", "")
                    await emit({"type": "delta", "text": params.get("delta", "")})
                elif method == "thread/tokenUsage/updated":
                    last = (params.get("tokenUsage") or {}).get("last") or {}
                    out.add_usage(input_tokens=last.get("inputTokens", 0), output_tokens=last.get("outputTokens", 0))
                elif method == "error" and not params.get("willRetry"):
                    error = params.get("error") or {}
                    out.error_kind = _error_kind(error.get("codexErrorInfo"))
                    out.error_message = str(error.get("message", ""))[:300]
                elif method == "turn/completed":
                    turn = params.get("turn") or {}
                    if turn.get("status") == "interrupted":
                        out.status = "interrupted"
                    elif turn.get("status") == "failed":
                        error = turn.get("error") or {}
                        out.status = "error"
                        out.error_kind = out.error_kind or _error_kind(error.get("codexErrorInfo"))
                        out.error_message = out.error_message or str(error.get("message", ""))[:300]
                    break
                elif method == "lastro/closed":
                    out.status, out.error_kind = "error", "network"
                    break
        except ProviderError as exc:
            out.status, out.error_kind, out.error_message = "error", exc.kind, exc.message
        finally:
            self.emit, self.turn_id, self.outcome = None, None, None
        # A última mensagem é a resposta; as anteriores, narração entre ferramentas.
        final = texts[order[-1]] if order else ""
        out.text = (final if final.strip() else "\n\n".join(texts[i] for i in order[:-1])).strip()
        if out.error_kind and out.status == "ok":
            out.status = "error"
        finalize_quiet(out)
        return out

    async def interrupt(self) -> None:
        if self.turn_id:
            await self.provider.server.request("turn/interrupt", {"threadId": self.native_id, "turnId": self.turn_id})

    async def close(self) -> None:
        self.provider.sessions.pop(self.native_id, None)
        self.provider.server.threads.pop(self.native_id, None)


class CodexProvider(Provider):
    type = "codex"
    label = "Codex (executável oficial, conta ChatGPT ou API key)"
    capabilities = ProviderCapabilities(
        cancel=True, native_resume=False, external_login=True, api_key=True, experimental=True,
        notes="Roda o `codex app-server` oficial; login pelo próprio Codex (device code do ChatGPT ou API key). "
              "Ferramentas nativas desligadas; aprovações sempre recusadas.")
    settings_schema = {"model": "modelo (vazio = padrão do Codex)", "effort": "enviar esforço de raciocínio? (sim/não)"}

    def __init__(self, connection):
        super().__init__(connection)
        self.sessions: dict[str, CodexSession] = {}
        self.server = AppServer(self._argv(), self._env(), self._on_tool_call)

    @property
    def send_effort(self) -> bool:
        return str(self.connection.settings.get("effort", "")).lower() in ("1", "true", "sim", "yes")

    def _argv(self) -> list[str]:
        argv = [cli_path() or "codex", "app-server", "--listen", "stdio://"]
        for feature in DISABLED_FEATURES:
            argv += ["--disable", feature]
        for item in CONFIG:
            argv += ["-c", item]
        return argv

    def _env(self) -> dict:
        home = codex_home()
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
        return {**env, "HOME": str(Path.home()), "CODEX_HOME": str(home)}

    def is_configured(self) -> bool:
        return cli_path() is not None

    async def _on_tool_call(self, params: dict) -> dict:
        session = self.sessions.get(params.get("threadId") or "")
        if session is None:
            return {"contentItems": [{"type": "inputText", "text": "Sessão encerrada."}], "success": False}
        return await session.handle_tool(params)

    async def open(self, spec: SessionSpec) -> CodexSession:
        if not self.is_configured():
            raise ProviderError("not_configured", "O Codex não está instalado neste worker.")
        tools = [{"type": "function", "name": t.name, "description": t.description, "inputSchema": t.input_schema}
                 for t in spec.tools]
        result = await self.server.request("thread/start", {
            "model": spec.model or self.default_model or None, "cwd": str(spec.workdir),
            "approvalPolicy": "on-request", "sandbox": "read-only", "developerInstructions": spec.system_prompt,
            "ephemeral": True, "dynamicTools": tools})
        thread_id = (result.get("thread") or {}).get("id")
        if not thread_id:
            raise ProviderError("internal", "O Codex não abriu a conversa.")
        session = CodexSession(self, spec, thread_id)
        self.sessions[thread_id] = session
        self.server.threads[thread_id] = session.queue
        return session

    async def list_models(self) -> list[dict]:
        result = await self.server.request("model/list", {})
        return [{"id": m.get("model") or m.get("id"), "label": m.get("displayName") or m.get("id")}
                for m in result.get("data", []) if not m.get("hidden")]

    async def account(self) -> dict:
        result = await self.server.request("account/read", {})
        account = result.get("account") or {}
        return {"logged_in": bool(account), "type": account.get("type"), "plan": account.get("planType")}

    async def test(self) -> dict:
        info = await self.account()
        if info["logged_in"]:
            return {"ok": True, "detail": f"Codex conectado ({info.get('plan') or info.get('type')})."}
        return {"ok": False, "detail": "Codex sem login."}

    async def login_device_code(self) -> dict:
        """Device code oficial do ChatGPT: a pessoa confirma o código na página da OpenAI."""
        result = await self.server.request("account/login/start", {"type": "chatgptDeviceCode"})
        login_id = result.get("loginId") or ""
        self.server.logins[login_id] = asyncio.get_running_loop().create_future()
        return {"login_id": login_id, "url": result.get("verificationUrl"), "code": result.get("userCode")}

    async def login_wait(self, login_id: str, timeout: float = 900) -> dict:
        future = self.server.logins.get(login_id)
        if future is None:
            return {"ok": False, "detail": "Login inexistente ou já concluído."}
        try:
            done = await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except TimeoutError:
            return {"ok": False, "detail": "Ainda aguardando a confirmação."}
        return {"ok": bool(done.get("success")), "detail": "Conectado." if done.get("success") else "Login não concluído."}

    async def login_api_key(self, api_key: str) -> dict:
        await self.server.request("account/login/start", {"type": "apiKey", "apiKey": api_key})
        return await self.test()

    async def revoke(self) -> bool:
        await self.server.request("account/logout", {})
        return True

    async def close(self) -> None:
        await self.server.close()
