# SPDX-License-Identifier: AGPL-3.0-or-later
"""Barreiras técnicas contra execução financeira (seções 10.3 e 24.9).

Estes testes inspecionam o código e a API real, não o comportamento do modelo de IA.
"""
import ast
import re
from pathlib import Path

import pytest

from app.agent_api import LOOPBACK_HOSTS, create_app, serve

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FIXTURES = ROOT / "tests" / "fixtures_synthetic"

FORBIDDEN_ACTIONS = re.compile(
    r"place_?order|withdraw|transfer|change_?pix|pix_?key|add_?beneficiar|approve_?payment|"
    r"send_?order|submit_?order|execute_?trade|buy|sell|resgatar|transferir|comprar|vender",
    re.IGNORECASE,
)
# Clientes de rede de saída. A API só escuta; não chama ninguém.
FORBIDDEN_IMPORTS = {"requests", "httpx", "aiohttp", "urllib.request", "http.client", "smtplib",
                     "ftplib", "socket", "paramiko", "selenium", "playwright", "subprocess"}
# Exceções conscientes, uma por arquivo, revisadas (ver docs/SECURITY_MODEL.md §4).
IMPORT_ALLOWLIST = {
    "mentor/tools.py": {"httpx"},  # só loopback; garantido por test_mentor_tools_refuse_non_loopback
    "mentor/browser.py": {"playwright"},  # leitor: allowlist (testes abaixo); aba livre: rede só via research.pinned_request (test_free_browser)
    "mentor/worker.py": {"socket"},  # só as constantes de SO_PEERCRED do socket Unix já aberto; nenhuma conexão
    "integrations/collector.py": {"httpx"},  # só APIs oficiais do catálogo; serviço próprio, fora do web e do worker
    "crypto/sources.py": {"httpx"},  # só data-api.binance.vision, api.coingecko.com e api.llama.fi; sem redirecionar
    # só GET em https público, IP conferido e fixado (sem loopback/privado/metadados), só na sessão de pesquisa sem
    # dados do dono; garantido por tests/integration/test_research.py
    "mentor/research.py": {"httpx", "socket"},
    "ledger/ocr.py": {"subprocess"},  # só o binário local tesseract, argumentos fixos, stdin, prazo; sem shell nem rede
}


def backend_modules():
    return sorted(p for p in BACKEND.rglob("*.py") if ".venv" not in p.parts)


def test_only_get_routes_exist():
    app = create_app(token="x" * 40, data_dir=FIXTURES)
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        assert methods <= {"GET", "HEAD"}, f"{route.path} expõe {methods}"


def test_no_route_path_or_name_suggests_transaction():
    app = create_app(token="x" * 40, data_dir=FIXTURES)
    for route in app.routes:
        assert not FORBIDDEN_ACTIONS.search(route.path), route.path
        assert not FORBIDDEN_ACTIONS.search(getattr(route, "name", "") or ""), route.name


@pytest.mark.parametrize("module", backend_modules(), ids=lambda p: str(p.relative_to(BACKEND)))
def test_no_transactional_functions_or_classes(module):
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert not FORBIDDEN_ACTIONS.search(node.name), f"{module}: {node.name}"


@pytest.mark.parametrize("module", backend_modules(), ids=lambda p: str(p.relative_to(BACKEND)))
def test_backend_has_no_outbound_network_or_shell_clients(module):
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported |= {node.module} | {f"{node.module}.{a.name}" for a in node.names}
    allowed = IMPORT_ALLOWLIST.get(module.relative_to(BACKEND).as_posix(), set())
    bad = {name for name in imported for f in FORBIDDEN_IMPORTS - allowed if name == f or name.startswith(f + ".")}
    assert not bad, f"{module} importa {bad}"


def test_mentor_tools_refuse_non_loopback(monkeypatch):
    from mentor.tools import api_url

    monkeypatch.setenv("MPA_AGENT_API_URL", "https://exemplo.com")
    with pytest.raises(RuntimeError, match="loopback"):
        api_url()


def test_mentor_tools_are_read_only():
    from mentor.tools import TOOLS

    assert {t.name for t in TOOLS} == {"situacao_atual", "diagnostico", "projecao", "metas", "premissas",
                                       "decisoes", "reunioes_anteriores", "mercado_cripto", "sem_novidade"}
    from providers.claude_code import sdk_tool

    for t in TOOLS:
        annotations = sdk_tool(t).annotations  # o que o Claude Code enxerga
        assert annotations.read_only_hint is True and annotations.destructive_hint is False
        assert not FORBIDDEN_ACTIONS.search(t.name)


def test_mentor_has_no_native_tools_and_ignores_disk_config(tmp_path):
    from mentor.session import mentor_options
    opts = mentor_options(workdir=tmp_path)
    assert opts.tools == []
    assert opts.allowed_tools == []  # nada é pré-aprovado; toda chamada passa pelo can_use_tool
    assert opts.strict_mcp_config is True and opts.setting_sources == []
    assert set(opts.mcp_servers) == {"patrimonio"}
    assert opts.permission_mode not in ("bypassPermissions", "acceptEdits")


@pytest.mark.parametrize("tool_name", ["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch",
                                       "CronCreate", "Task", "mcp__outro__transferir"])
def test_mentor_permission_gate_denies_everything_else(tool_name):
    """Só as ferramentas de leitura passam; qualquer outra é negada."""
    import asyncio

    from claude_agent_sdk import PermissionResultDeny

    from mentor.session import only_mentor_tools

    assert isinstance(asyncio.run(only_mentor_tools(tool_name, {}, None)), PermissionResultDeny)


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete", "options"])
@pytest.mark.parametrize("path", ["/v1/health", "/v1/projection", "/v1/transfer", "/v1/orders"])
def test_non_get_methods_are_refused_even_with_valid_token(client, auth, method, path):
    response = client.request(method.upper(), path, headers=auth, json={"amount": "1000"})
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"


def test_generic_approval_does_not_unlock_execution(client, auth):
    """Nem uma 'aprovação genérica' cria caminho de execução: a rota simplesmente não existe."""
    headers = {**auth, "X-User-Approval": "aprovado"}
    assert client.post("/v1/orders", headers=headers, json={"confirm": True}).status_code == 405
    assert client.get("/v1/orders/execute", headers=headers).status_code == 404


def test_requires_token(client):
    assert client.get("/v1/health").status_code == 401
    assert client.get("/v1/health", headers={"Authorization": "Bearer errado"}).status_code == 401


def test_refuses_weak_token():
    with pytest.raises(RuntimeError):
        create_app(token="curto", data_dir=FIXTURES)


def test_refuses_non_loopback_bind():
    assert "0.0.0.0" not in LOOPBACK_HOSTS
    with pytest.raises(RuntimeError, match="loopback"):
        serve(host="0.0.0.0")


def test_refuses_non_synthetic_data(tmp_path, auth):
    from fastapi.testclient import TestClient

    (tmp_path / "personas.json").write_text('{"synthetic": false, "as_of": "2026-10-26", "personas": []}')
    client = TestClient(create_app(token="t" * 40, data_dir=tmp_path))
    response = client.get("/v1/personas", headers=auth)
    assert response.status_code == 403


def test_no_interactive_docs_or_schema_exposed(client, auth):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path, headers=auth).status_code == 404


def test_mentor_permission_gate_allows_only_read_tools():
    import asyncio

    from claude_agent_sdk import PermissionResultAllow

    from mentor.session import only_mentor_tools
    from mentor.tools import TOOL_NAMES

    for name in TOOL_NAMES:
        assert isinstance(asyncio.run(only_mentor_tools(name, {}, None)), PermissionResultAllow)


# ---------- navegador de pesquisa ----------

@pytest.mark.parametrize("url", [
    "https://www.bcb.gov.br/controleinflacao/taxaselic",
    "https://sidra.ibge.gov.br/tabela/1737",
    "https://www.tesourodireto.com.br/titulos/precos-e-taxas.htm",
    "https://www.fgc.org.br/garantia-fgc/sobre-a-garantia-fgc",
    "https://gov.br/receitafederal",
])
def test_browser_allows_official_sources(url):
    from mentor.browser import validate_url

    assert validate_url(url)


@pytest.mark.parametrize("url", [
    "http://www.bcb.gov.br/",                      # sem TLS
    "https://bcb.gov.br.evil.com/",                # sufixo falso
    "https://evilgov.br/",                         # não é subdomínio de gov.br
    "https://user:pass@www.bcb.gov.br/",           # credenciais na URL
    "https://www.bcb.gov.br:8443/",                # porta estranha
    "https://200.218.208.1/",                      # IP literal
    "https://www.minhacorretora.com.br/login",     # corretora/banco nunca
    "file:///etc/passwd",
    "javascript:alert(1)",
])
def test_browser_blocks_everything_else(url):
    from mentor.browser import BlockedURL, validate_url

    with pytest.raises(BlockedURL):
        validate_url(url)


def test_browser_page_requests_cannot_leave_allowlist_or_submit_forms():
    from mentor.browser import request_allowed

    assert request_allowed("https://www.bcb.gov.br/app.js", "GET")
    assert request_allowed("data:image/png;base64,AAAA", "GET")
    assert not request_allowed("https://www.google-analytics.com/collect?x=1", "GET")  # exfiltração por subrecurso
    assert not request_allowed("https://attacker.example/?dados=segredo", "GET")
    assert not request_allowed("https://www.bcb.gov.br/form", "POST")                 # formulário
    assert not request_allowed("http://www.bcb.gov.br/", "GET")


def test_browser_tool_name_is_gated_and_read_only():
    import asyncio

    from mentor.browser import ResearchBrowser
    from mentor.tools import TOOL_NAMES, browser_tool

    assert "mcp__patrimonio__ler_pagina_oficial" in TOOL_NAMES
    tool_obj = browser_tool(ResearchBrowser("/nao/existe"))
    from providers.claude_code import sdk_tool

    annotations = sdk_tool(tool_obj).annotations
    assert annotations.read_only_hint is True and annotations.destructive_hint is False
    assert tool_obj.open_world and annotations.open_world_hint is True
    blocked = asyncio.run(tool_obj.handler({"url": "https://attacker.example/"}))
    assert blocked["is_error"] and "Bloqueado" in blocked["content"][0]["text"]


# ---------- capacidades por papel ----------

def test_owner_data_and_open_browser_never_share_a_session():
    import asyncio

    from claude_agent_sdk import PermissionResultAllow

    from mentor.browser import ResearchBrowser
    from mentor.session import ROLES, mentor_options
    from mentor.tools import ROLE_CAPABILITIES

    browser_name, data_name = "mcp__patrimonio__ler_pagina_oficial", "mcp__patrimonio__situacao_atual"
    browser = ResearchBrowser("/nao/existe")
    for role in ROLES:
        options = mentor_options(role=role, workdir=Path("/tmp"), browser=browser)
        allowed = {name for name in ("mcp__patrimonio__" + n for n in (
            "situacao_atual", "diagnostico", "projecao", "metas", "premissas", "decisoes", "sem_novidade",
            "ler_pagina_oficial")) if isinstance(asyncio.run(options.can_use_tool(name, {}, None)), PermissionResultAllow)}
        caps = ROLE_CAPABILITIES[role]
        if caps.browser == "research":
            assert browser_name in allowed and data_name not in allowed, role  # allowlist inteira, sem dados do dono
        elif role in ("coordenador", "mentor"):
            assert browser_name in allowed and data_name in allowed  # chat: navegador restrito (testado abaixo)
            assert caps.browser == "owner"
        else:
            assert browser_name not in allowed, role  # rotinas e demais especialistas não navegam
        assert ("mcp__patrimonio__sem_novidade" in allowed) == (role == "rotina"), role


def test_chat_browser_is_restricted_to_exact_hosts_without_query():
    import asyncio

    from mentor.browser import ResearchBrowser
    from mentor.tools import browser_tool

    tool_obj = browser_tool(ResearchBrowser("/nao/existe"), owner_context=True)
    for url in ("https://www.bcb.gov.br/x?renda=9999.00", "https://r9999-00-d1111-00.gov.br/"):
        result = asyncio.run(tool_obj.handler({"url": url}))
        assert result["is_error"] and "Bloqueado" in result["content"][0]["text"], url
