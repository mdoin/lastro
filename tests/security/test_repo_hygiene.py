"""Nenhum segredo ou dado real versionado; .gitignore cobre o que precisa."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)(api[_-]?key|secret|password|senha)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
]
# Infraestrutura da instância pessoal da autora: nunca no estado publicado do repositório.
PERSONAL = re.compile(r"doinlabs\.com|50\.114\.206\.|maitedoin@")
CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
CARD = re.compile(r"\b(?:\d[ -]?){15}\d\b")


def repo_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not SKIP_DIRS & set(path.relative_to(ROOT).parts) and path.suffix not in {".lock"}:
            yield path


def test_no_secrets_or_identifiers_committed():
    for path in repo_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if path.name == "test_repo_hygiene.py":
            continue
        for pattern in SECRET_PATTERNS + [CPF, CARD, PERSONAL]:
            assert not pattern.search(text), f"possível segredo/identificador em {path.relative_to(ROOT)}"


def test_gitignore_covers_sensitive_paths():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in (".env", "*.db", "*.sqlite", "data/", "backups/", "exports/", "*.ofx", "extratos/"):
        assert entry in ignore, entry


def test_env_example_has_no_secret_values():
    """Padrões não secretos (porta, fuso) podem vir preenchidos; tokens, chaves e senhas nunca."""
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            if re.search(r"TOKEN|KEY|SECRET|PASSWORD|SENHA", key):
                assert value == "", f".env.example com segredo preenchido: {key}"
            if key not in ("LASTRO_BIND", "LASTRO_TRUSTED_PROXIES"):  # loopback e o IP fixo do caddy
                assert not re.search(r"\d{1,3}(\.\d{1,3}){3}", value), f"IP fixo em {key}"


def test_all_fixtures_are_marked_synthetic():
    for path in (ROOT / "tests" / "fixtures_synthetic").glob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8")).get("synthetic") is True, path.name
