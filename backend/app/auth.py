"""Autenticação do dono do app: senha (scrypt) + sessão por cookie.

- A senha só é definida no servidor (`lastro-admin set-password`), nunca pela web.
- O token de sessão é aleatório; o banco guarda apenas o sha256 dele.
- Tentativas de login são limitadas por cliente (IP; IPv6 por /64): quem erra demais é bloqueado,
  mas um terceiro nunca consegue bloquear o dono. No total, falhas demais só deixam o login mais lento.
"""

import base64
import hashlib
import hmac
import ipaddress
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from .db import utcnow
from .store import OWNER

SESSION_COOKIE = "lastro_session"
SESSION_DAYS = 14
MAX_FAILURES = 5                  # por cliente, na janela: bloqueio
FAILURE_WINDOW = timedelta(minutes=15)
GLOBAL_SLOWDOWN_AFTER = 50        # falhas de todos os clientes antes de começar a atrasar
MAX_GLOBAL_DELAY_SECONDS = 5.0    # atraso limitado; nunca vira recusa
MIN_PASSWORD_LENGTH = 12

_SCRYPT = {"n": 2**15, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, maxmem=64 * 1024 * 1024, dklen=32, **_SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p),
                                maxmem=64 * 1024 * 1024, dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def set_password(conn: sqlite3.Connection, password: str) -> None:
    conn.execute("INSERT INTO credentials (user_id, password_hash, updated_at) VALUES (?,?,?) "
                 "ON CONFLICT(user_id) DO UPDATE SET password_hash = excluded.password_hash, updated_at = excluded.updated_at",
                 (OWNER, hash_password(password), utcnow()))
    # Trocar a senha encerra todas as sessões abertas e zera os bloqueios de login.
    conn.execute("DELETE FROM auth_sessions")
    conn.execute("DELETE FROM login_attempts")


def password_is_set(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM credentials WHERE user_id = ?", (OWNER,)).fetchone() is not None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def client_key(host: str | None) -> str:
    """Chave do limitador: o IP do cliente; para IPv6, o prefixo /64 (um único assinante troca o resto à vontade)."""
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return host or "desconhecido"
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _since() -> str:
    return (_now() - FAILURE_WINDOW).isoformat(timespec="seconds")


def too_many_failures(conn: sqlite3.Connection, client: str) -> bool:
    failures = conn.execute("SELECT COUNT(*) FROM login_attempts WHERE success = 0 AND at >= ? AND client = ?",
                            (_since(), client)).fetchone()[0]
    return failures >= MAX_FAILURES


def global_delay(conn: sqlite3.Connection) -> float:
    """Segundos de espera quando há muitas falhas somando todos os clientes (ataque distribuído)."""
    failures = conn.execute("SELECT COUNT(*) FROM login_attempts WHERE success = 0 AND at >= ?",
                            (_since(),)).fetchone()[0]
    if failures < GLOBAL_SLOWDOWN_AFTER:
        return 0.0
    return min(MAX_GLOBAL_DELAY_SECONDS, 0.1 * (failures - GLOBAL_SLOWDOWN_AFTER + 1))


def attempt_login(conn: sqlite3.Connection, password: str, client: str) -> str | None:
    """Retorna um token de sessão novo, ou None se a senha estiver errada."""
    row = conn.execute("SELECT password_hash FROM credentials WHERE user_id = ?", (OWNER,)).fetchone()
    ok = bool(row) and verify_password(password, row["password_hash"])
    prune_attempts(conn)
    conn.execute("INSERT INTO login_attempts (at, success, client) VALUES (?, ?, ?)", (utcnow(), 1 if ok else 0, client))
    if not ok:
        return None
    token = secrets.token_urlsafe(32)
    now = _now()
    conn.execute("INSERT INTO auth_sessions (token_hash, created_at, expires_at, last_seen_at) VALUES (?,?,?,?)",
                 (_hash_token(token), now.isoformat(timespec="seconds"),
                  (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds"), now.isoformat(timespec="seconds")))
    return token


def unlock(conn: sqlite3.Connection) -> int:
    """Remove as falhas registradas (todos os bloqueios). Retorna quantas foram apagadas."""
    return conn.execute("DELETE FROM login_attempts WHERE success = 0").rowcount


def prune_attempts(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM login_attempts WHERE at < ?", ((_now() - timedelta(days=1)).isoformat(timespec="seconds"),))


def session_is_valid(conn: sqlite3.Connection, token: str | None) -> bool:
    if not token:
        return False
    row = conn.execute("SELECT expires_at FROM auth_sessions WHERE token_hash = ?", (_hash_token(token),)).fetchone()
    if not row:
        return False
    if datetime.fromisoformat(row["expires_at"]) <= _now():
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_hash_token(token),))
        return False
    conn.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?", (utcnow(), _hash_token(token)))
    return True


def logout(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_hash_token(token),))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
