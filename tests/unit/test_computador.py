import asyncio
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "controle", Path(__file__).resolve().parents[2] / "deploy" / "computador" / "controle.py")
controle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controle)


class FakeDocker:
    def __init__(self):
        self.calls = []

    async def __call__(self, *args, timeout=60):
        self.calls.append(args)
        if args[:2] == ("inspect", "-f"):
            return 0, "true"
        return 0, ""


def make(now):
    ctl = controle.Controller(run=FakeDocker(), clock=lambda: now[0])
    return ctl


def test_nome_invalido_recusado():
    ctl = make([0.0])
    for bad in ("../x", "Teo", "a", "teo;rm", ""):
        assert asyncio.run(ctl.handle({"op": "ligar", "agente": bad}))["ok"] is False
    assert not ctl.run.calls


def test_limite_desliga_o_ocioso_mais_antigo_e_respeita_tela_aberta():
    now = [0.0]
    ctl = make(now)
    for i, agent in enumerate(("lia", "caio", "vera")):
        now[0] = float(i)
        asyncio.run(ctl.turn_on(agent))
    ctl.pipes["lia"] = 1  # dono olhando a tela da Lia: não pode ser desligado
    now[0] = 10.0
    asyncio.run(ctl.turn_on("rui"))
    assert set(ctl.used) == {"lia", "vera", "rui"}
    assert ("stop", "-t", "5", "lastro-pc-caio") in ctl.run.calls


def test_dono_no_controle_bloqueia_terminal_do_agente_e_ocioso_desliga():
    now = [0.0]
    ctl = make(now)
    asyncio.run(ctl.handle({"op": "controle", "agente": "teo", "dono": True}))
    assert asyncio.run(ctl.handle({"op": "executar", "agente": "teo", "comando": "ls"}))["ok"] is False
    asyncio.run(ctl.handle({"op": "controle", "agente": "teo", "dono": False}))
    assert asyncio.run(ctl.handle({"op": "executar", "agente": "teo", "comando": "ls"}))["ok"] is True
    now[0] = controle.IDLE_SECONDS + 1
    asyncio.run(ctl.reap())
    assert "teo" not in ctl.used


def test_gateway_recriado_volta_para_as_redes_dos_ligados():
    ctl = make([0.0])
    asyncio.run(ctl.turn_on("lia"))
    ctl.run.calls.clear()
    ctl.run = FakeDockerGatewayDown(ctl.run.calls)
    asyncio.run(ctl.turn_on("caio"))
    assert ("network", "connect", "--alias", "saida", "lastro-pc-lia", "lastro-saida") in ctl.run.calls


class FakeDockerGatewayDown(FakeDocker):
    def __init__(self, calls):
        self.calls = calls

    async def __call__(self, *args, timeout=60):
        self.calls.append(args)
        return (1, "") if args[:2] == ("inspect", "-f") else (0, "")
