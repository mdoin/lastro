# SPDX-License-Identifier: AGPL-3.0-or-later
"""Instalação self-hosted: o compose.yaml e o Dockerfile mantêm a separação de privilégios.

Testes estáticos (rodam sem Docker). O CI também roda `docker compose config` e constrói a imagem.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
APP_SERVICES = ("web", "mentor", "agent-api", "collector")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def volumes(name):
    return [v.split(":")[0] for v in SERVICES[name].get("volumes", [])]


def test_no_service_is_privileged_or_reaches_docker():
    for name, svc in SERVICES.items():
        assert not svc.get("privileged"), name
        assert "docker.sock" not in str(svc.get("volumes", [])), name
        assert svc.get("security_opt") == ["no-new-privileges:true"], name
        assert svc.get("cap_drop") == ["ALL"], name
        assert set(svc.get("cap_add", [])) <= {"NET_BIND_SERVICE"}, name
        assert svc.get("network_mode") in (None, "service:mentor"), name


def test_app_services_run_as_fixed_non_root_users_on_read_only_fs():
    users = {name: SERVICES[name]["user"] for name in APP_SERVICES}
    assert users == {"web": "10001:10001", "mentor": "10002:10002", "agent-api": "10001:10001",
                     "collector": "10001:10001"}
    for name in APP_SERVICES:
        assert SERVICES[name]["read_only"] is True, name
        assert SERVICES[name]["restart"] == "unless-stopped", name


def test_credentials_and_financial_data_never_share_a_container():
    assert "data" not in volumes("mentor")                            # quem tem credenciais de IA não vê o banco
    for name in ("web", "agent-api", "collector"):
        assert "mentor-home" not in volumes(name), name               # quem tem o banco não vê credenciais
    assert SERVICES["agent-api"]["network_mode"] == "service:mentor"  # API de leitura só no loopback do mentor
    assert "ports" not in SERVICES["agent-api"] and "ports" not in SERVICES["mentor"]


def test_socket_identity_matches_the_image_users():
    env = SERVICES["mentor"]["environment"]
    assert env["LASTRO_SOCKET_PEER_UID"] == "10001" and env["LASTRO_SOCKET_GID"] == "10010"
    assert SERVICES["web"]["group_add"] == ["10010"] and SERVICES["mentor"]["group_add"] == ["10010"]
    for uid in ("10001", "10002", "10010"):
        assert uid in DOCKERFILE


def test_web_is_local_only_by_default_and_has_health_checks():
    assert SERVICES["web"]["ports"] == ["${LASTRO_BIND:-127.0.0.1}:${LASTRO_HTTP_PORT:-8080}:8080"]
    for name in ("web", "mentor"):
        assert SERVICES[name]["healthcheck"]["test"], name
    assert SERVICES["collector"]["depends_on"]["web"]["condition"] == "service_healthy"  # migra antes


def test_no_personal_infrastructure_or_secrets_in_install_files():
    for path in ("compose.yaml", "Dockerfile", ".env.example", "deploy/docker/Caddyfile", "scripts/init-env.sh"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "doinlabs" not in text and "/opt/meu-patrimonio" not in text, path
        assert not re.search(r"/home/(?!mentor)|/Users/|C:\\", text), path  # só o HOME do usuário da imagem
    assert "${LASTRO_AGENT_API_TOKEN:?" in (ROOT / "compose.yaml").read_text(encoding="utf-8")


def test_proprietary_cli_is_opt_in():
    assert re.search(r"ARG WITH_CLAUDE_CODE=0", DOCKERFILE) and re.search(r"ARG WITH_CODEX=0", DOCKERFILE)
    assert SERVICES["web"]["build"]["args"]["WITH_CLAUDE_CODE"] == "${LASTRO_WITH_CLAUDE_CODE:-0}"


def test_dockerignore_keeps_secrets_and_data_out_of_the_image():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for entry in (".env", "*.db", "data", "backups", ".git", "**/node_modules", ".venv"):
        assert entry in ignore, entry


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("sh"), reason="script POSIX")
def test_init_env_generates_a_private_random_token(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "init-env.sh", tmp_path / "scripts")
    shutil.copy(ROOT / ".env.example", tmp_path)
    subprocess.run(["sh", str(tmp_path / "scripts" / "init-env.sh")], check=True, capture_output=True)
    env = (tmp_path / ".env").read_text()
    token = re.search(r"^LASTRO_AGENT_API_TOKEN=(\w+)$", env, re.M).group(1)
    assert len(token) == 96
    assert (tmp_path / ".env").stat().st_mode & 0o077 == 0
    subprocess.run(["sh", str(tmp_path / "scripts" / "init-env.sh")], check=True, capture_output=True)
    assert (tmp_path / ".env").read_text() == env                     # nunca sobrescreve


def test_current_systemd_installation_keeps_working():
    """A instância pessoal (systemd) continua com o Claude Code implícito e os extras instalados."""
    unit = (ROOT / "deploy" / "systemd" / "lastro-mentor.service").read_text(encoding="utf-8")
    assert "Environment=LASTRO_IMPLICIT_CLAUDE_CODE=1" in unit
    assert "LASTRO_PROVIDERS_FILE=/var/lib/mentor/providers.json" in unit
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    assert "--extra claude-code --extra browser" in deploy
