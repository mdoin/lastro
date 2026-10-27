"""Comandos de administração do Lastro, rodados no servidor pelo dono.

  lastro-admin set-password        # define/troca a senha (pede no terminal, sem eco)
  lastro-admin migrate             # aplica migrações pendentes (com backup automático antes)
  lastro-admin logout-all          # encerra todas as sessões
  lastro-admin unlock              # remove bloqueios de login por tentativas erradas
  lastro-admin backup DESTINO.db   # cópia consistente do banco, com o app rodando
  lastro-admin restore ORIGEM.db   # restaura um backup (pare web, coletor e API de leitura antes)

O banco guarda dados financeiros, conversas e configurações. Credenciais de IA NÃO estão nele: ficam no volume
do worker (ver docs/BACKUP.md).
"""

import argparse
import getpass
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import auth, db

DEFAULT_DB = Path(os.environ.get("LASTRO_DB", "/var/lib/patrimonio/lastro.db"))


def backup(conn: sqlite3.Connection, dest: Path) -> Path:
    """Cópia online e consistente (API de backup do SQLite), conferida e gravada com permissão 0600."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    target = sqlite3.connect(tmp)
    try:
        conn.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("o backup não passou na verificação de integridade")
    finally:
        target.close()
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)
    return dest


def pre_migration_backup(conn: sqlite3.Connection, db_path: Path) -> Path | None:
    """Antes de migrar um banco que já tem dados, guarda uma cópia em backups/ ao lado do banco."""
    version = db.current_version(conn)
    if version == 0 or version >= db.LATEST_VERSION or str(db_path) == ":memory:":
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return backup(conn, db_path.parent / "backups" / f"pre-v{db.LATEST_VERSION}-{stamp}.db")


def restore(source: Path, db_path: Path) -> int:
    """Confere o backup e troca o arquivo do banco de uma vez; devolve a versão do esquema restaurado."""
    check = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("o arquivo de backup está corrompido")
        version = db.current_version(check)
    finally:
        check.close()
    if version > db.LATEST_VERSION:
        raise RuntimeError("o backup é de uma versão mais nova do Lastro; atualize antes de restaurar")
    tmp = db_path.with_name(db_path.name + ".restoring")
    shutil.copyfile(source, tmp)
    os.chmod(tmp, 0o600)
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    os.replace(tmp, db_path)
    return version


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="lastro-admin")
    parser.add_argument("command", choices=["set-password", "migrate", "logout-all", "unlock", "backup", "restore"])
    parser.add_argument("path", nargs="?", type=Path, help="arquivo de backup (backup/restore)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    if args.command in ("backup", "restore") and not args.path:
        print("Informe o arquivo: lastro-admin backup /caminho/lastro-AAAA-MM-DD.db", file=sys.stderr)
        return 2
    if args.command == "restore":
        try:
            version = restore(args.path, args.db)
        except (RuntimeError, sqlite3.DatabaseError, OSError) as exc:
            print(f"Restauração recusada: {exc}", file=sys.stderr)
            return 1
        conn = db.connect(args.db)
        print(f"Backup restaurado (esquema v{version}); banco agora na versão {db.migrate(conn)}.")
        return 0

    conn = db.connect(args.db)
    if args.command == "backup":
        print(f"Backup gravado em {backup(conn, args.path)}.")
        conn.close()
        return 0
    saved = pre_migration_backup(conn, args.db)
    if saved:
        print(f"Backup antes da migração: {saved}")
    version = db.migrate(conn)
    if args.command == "migrate":
        print(f"Banco na versão {version}.")
    elif args.command == "set-password":
        if not sys.stdin.isatty():
            print("Rode num terminal interativo; a senha não é aceita por pipe.", file=sys.stderr)
            return 2
        first = getpass.getpass("Nova senha do Lastro (mín. 12 caracteres): ")
        if getpass.getpass("Repita a senha: ") != first:
            print("As senhas não conferem.", file=sys.stderr)
            return 1
        try:
            auth.set_password(conn, first)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print("Senha definida. Sessões anteriores foram encerradas.")
    elif args.command == "logout-all":
        conn.execute("DELETE FROM auth_sessions")
        print("Todas as sessões foram encerradas.")
    elif args.command == "unlock":
        print(f"Bloqueios de login removidos ({auth.unlock(conn)} tentativas erradas apagadas).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
