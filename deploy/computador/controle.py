# SPDX-License-Identifier: AGPL-3.0-or-later
"""Controlador dos computadores dos agentes (docs/COMPUTADORES.md). Roda como root (fala com o Docker); só a
biblioteca padrão. Escuta num socket Unix 0660 root:lastro-sock (web e worker do mentor).

Protocolo: uma linha JSON por pedido, uma linha JSON de resposta. Em `conectar`, depois da resposta {"ok": true} o
socket vira um cano de bytes para a tela (VNC) ou para o DevTools do Chrome dentro do container.
"""

import asyncio
import json
import os
import re
import time

SOCKET = os.environ.get("LASTRO_PC_SOCKET", "/run/lastro-computadores/controle.sock")
GROUP = os.environ.get("LASTRO_SOCKET_GROUP", "lastro-sock")
IMAGE = os.environ.get("LASTRO_PC_IMAGE", "lastro-computador:1")
GATEWAY_IMAGE = os.environ.get("LASTRO_PC_GATEWAY_IMAGE", "lastro-saida:1")
MAX_ON = int(os.environ.get("LASTRO_PC_MAX", "3"))
IDLE_SECONDS = int(os.environ.get("LASTRO_PC_IDLE", "900"))
GATEWAY, OUT_NET = "lastro-saida", "lastro-pc-saida"
PORTS = {"tela": 5900, "chrome": 9222}
NAME = re.compile(r"[a-z]{2,20}")
MAX_OUTPUT = 20000


def container(agent: str) -> str:
    return f"lastro-pc-{agent}"


async def docker(*args: str, timeout: float = 60) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec("docker", *args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return 124, "tempo esgotado"
    return proc.returncode, out.decode(errors="replace")


class Controller:
    def __init__(self, run=docker, clock=time.monotonic):
        self.run, self.clock = run, clock
        self.used: dict[str, float] = {}   # agente ligado -> último uso
        self.agent_used: dict[str, float] = {}
        self.pipes: dict[str, int] = {}
        self.owner: set[str] = set()       # agentes cujo computador o dono assumiu
        self.ip, self.ip_at = "", 0.0
        self.lock = asyncio.Lock()

    async def sync(self) -> None:
        """Lê do Docker quais computadores estão ligados (o controlador pode ter reiniciado)."""
        code, out = await self.run("ps", "--filter", "name=^lastro-pc-", "--format", "{{.Names}}")
        if code == 0:
            on = {n.removeprefix("lastro-pc-") for n in out.split()}
            self.used = {a: self.used.get(a, self.clock()) for a in on}

    async def gateway(self) -> None:
        code, out = await self.run("inspect", "-f", "{{.State.Running}}", GATEWAY)
        if code == 0 and out.strip() == "true":
            return
        await self.run("network", "create", OUT_NET)
        await self.run("rm", "-f", GATEWAY)
        code, out = await self.run("run", "-d", "--name", GATEWAY, "--network", OUT_NET, "--restart", "unless-stopped",
                                   "--cap-drop", "ALL", "--cap-add", "NET_ADMIN", "--cap-add", "SETUID",
                                   "--cap-add", "SETGID", "--memory", "128m", GATEWAY_IMAGE)
        if code != 0:
            raise RuntimeError(f"gateway de saída não subiu: {out.strip()[:200]}")
        for agent in self.used:  # gateway novo: os computadores já ligados voltam a ter saída
            await self.run("network", "connect", "--alias", "saida", container(agent), GATEWAY)
        self.ip_at = 0.0

    async def egress_ip(self) -> str:
        if self.clock() - self.ip_at > 600 or not self.ip:
            code, out = await self.run("exec", GATEWAY, "curl", "-s", "-m", "10", "https://api.ipify.org", timeout=15)
            self.ip = out.strip() if code == 0 and re.fullmatch(r"[0-9a-f.:]{3,45}", out.strip()) else ""
            self.ip_at = self.clock()
        return self.ip

    async def turn_on(self, agent: str) -> None:
        async with self.lock:
            if agent in self.used:
                self.used[agent] = self.clock()
                return
            if len(self.used) >= MAX_ON:
                idle = [a for a in self.used if not self.pipes.get(a)]
                if not idle:
                    raise RuntimeError(f"Já há {MAX_ON} computadores em uso; tente daqui a pouco.")
                await self.turn_off(min(idle, key=self.used.get))
            await self.gateway()
            net = container(agent)
            await self.run("network", "create", "--internal", net)
            await self.run("network", "connect", "--alias", "saida", net, GATEWAY)
            await self.run("rm", "-f", net)
            code, out = await self.run(
                "run", "-d", "--rm", "--name", net, "--hostname", agent, "--network", net,
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "1200m",
                "--pids-limit", "512", "--shm-size", "256m", "-v", f"{net}:/home/agente", IMAGE)
            if code != 0:
                raise RuntimeError(f"o computador não ligou: {out.strip()[:200]}")
            self.used[agent] = self.clock()
        await self.wait_ready(agent)

    async def wait_ready(self, agent: str) -> None:
        for _ in range(30):
            code, _out = await self.run("exec", container(agent), "curl", "-s", "-m", "2", "--noproxy", "*",
                                        "http://127.0.0.1:9222/json/version", timeout=5)
            if code == 0:
                return
            await asyncio.sleep(1)

    async def turn_off(self, agent: str) -> None:
        self.used.pop(agent, None)
        self.owner.discard(agent)
        await self.run("stop", "-t", "5", container(agent), timeout=30)

    async def reap(self) -> None:
        now = self.clock()
        for agent in [a for a, t in self.used.items() if not self.pipes.get(a) and now - t > IDLE_SECONDS]:
            await self.turn_off(agent)

    async def execute(self, agent: str, command: str, seconds: int) -> dict:
        self.agent_used[agent] = self.clock()
        await self.turn_on(agent)
        code, out = await self.run("exec", "-u", "agente", "-w", "/home/agente", container(agent),
                                   "timeout", "-k", "5", str(seconds), "bash", "-lc", command, timeout=seconds + 15)
        self.used[agent] = self.clock()
        return {"codigo": code, "saida": out[-MAX_OUTPUT:], "truncado": len(out) > MAX_OUTPUT}

    async def status(self) -> dict:
        now = self.clock()
        return {"ip_saida": await self.egress_ip() if self.used else self.ip, "limite": MAX_ON,
                "computadores": {a: {"controle": "dono" if a in self.owner else "agente",
                                     "agente_ativo": now - self.agent_used.get(a, -1e9) < 60}
                                 for a in self.used}}

    async def handle(self, req: dict) -> dict:
        op, agent = req.get("op"), str(req.get("agente", ""))
        if op == "estado":
            return {"ok": True, **await self.status()}
        if not NAME.fullmatch(agent):
            return {"ok": False, "erro": "agente inválido"}
        if op == "ligar":
            await self.turn_on(agent)
            return {"ok": True}
        if op == "desligar":
            await self.turn_off(agent)
            return {"ok": True}
        if op == "controle":
            (self.owner.add if req.get("dono") else self.owner.discard)(agent)
            return {"ok": True}
        if op == "executar":
            if agent in self.owner:
                return {"ok": False, "erro": "o dono está usando este computador agora"}
            seconds = max(1, min(int(req.get("prazo") or 60), 300))
            return {"ok": True, **await self.execute(agent, str(req.get("comando", ""))[:8000], seconds)}
        return {"ok": False, "erro": "operação desconhecida"}

    async def pipe(self, agent: str, port: int, reader, writer) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", container(agent), "socat", "STDIO", f"TCP:127.0.0.1:{port}",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self.pipes[agent] = self.pipes.get(agent, 0) + 1

        async def pump(src, dst):
            try:
                while data := await src.read(65536):
                    dst.write(data)
                    await dst.drain()
                    self.used[agent] = self.clock()
            except (ConnectionError, OSError):
                pass
            finally:
                try:
                    dst.close()
                except Exception:  # noqa: BLE001
                    pass

        try:
            await asyncio.wait([asyncio.ensure_future(pump(reader, proc.stdin)),
                                asyncio.ensure_future(pump(proc.stdout, writer))],
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            self.pipes[agent] -= 1
            if proc.returncode is None:
                proc.kill()
            writer.close()

    async def client(self, reader, writer) -> None:
        try:
            req = json.loads(await asyncio.wait_for(reader.readline(), 10))
            if req.get("op") == "conectar":
                agent, port = str(req.get("agente", "")), PORTS.get(req.get("porta"))
                if not NAME.fullmatch(agent) or port is None:
                    raise ValueError("pedido inválido")
                if port == PORTS["chrome"]:
                    if agent in self.owner:
                        raise ValueError("o dono está usando este computador agora")
                    self.agent_used[agent] = self.clock()
                await self.turn_on(agent)
                writer.write(b'{"ok": true}\n')
                await writer.drain()
                await self.pipe(agent, port, reader, writer)
                return
            resp = await self.handle(req)
        except Exception as exc:  # noqa: BLE001 — erro vira resposta, o controlador segue de pé
            resp = {"ok": False, "erro": str(exc)[:300] or type(exc).__name__}
        try:
            writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()


async def main() -> None:
    import grp

    ctl = Controller()
    await ctl.sync()
    if os.path.exists(SOCKET):
        os.unlink(SOCKET)
    server = await asyncio.start_unix_server(ctl.client, SOCKET)
    os.chown(SOCKET, 0, grp.getgrnam(GROUP).gr_gid)
    os.chmod(SOCKET, 0o660)
    async with server:
        while True:
            await asyncio.sleep(60)
            await ctl.reap()


if __name__ == "__main__":
    asyncio.run(main())
