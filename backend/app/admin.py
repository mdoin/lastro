"""Comandos de administração do Lastro, rodados no servidor pelo dono.

  sudo lastro-admin set-password   # define/troca a senha (pede no terminal, sem eco)
  sudo lastro-admin migrate        # aplica migrações pendentes
  sudo lastro-admin logout-all     # encerra todas as sessões
  sudo lastro-admin unlock         # remove bloqueios de login por tentativas erradas
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

from . import auth, db

DEFAULT_DB = Path(os.environ.get("LASTRO_DB", "/var/lib/patrimonio/lastro.db"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="lastro-admin")
    parser.add_argument("command", choices=["set-password", "migrate", "logout-all", "unlock"])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
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
