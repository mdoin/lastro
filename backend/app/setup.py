"""Token de instalação: protege a criação da primeira senha pela web.

Numa instalação nova o web app ainda não tem senha; sem este token, quem chegasse primeiro ao endereço
tomaria a instância. O token vem de `LASTRO_SETUP_TOKEN` ou é gerado uma vez num arquivo 0600 ao lado do banco
(`setup-token`), que só quem administra o servidor lê. Ele é apagado assim que a senha é definida.
"""

import hmac
import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger("lastro.setup")
TOKEN_FILE = "setup-token"


def ensure_token(data_dir: Path) -> str:
    explicit = os.environ.get("LASTRO_SETUP_TOKEN")
    if explicit:
        return explicit
    path = data_dir / TOKEN_FILE
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(24)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    log.warning("Instalação sem senha. Token de instalação gravado em %s (leia no servidor para criar a senha).", path)
    return token


def token_matches(expected: str | None, given: str) -> bool:
    return bool(expected) and hmac.compare_digest(expected.encode(), given.strip().encode())


def discard_token(data_dir: Path) -> None:
    try:
        (data_dir / TOKEN_FILE).unlink()
    except FileNotFoundError:
        pass
