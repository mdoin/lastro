# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cofre de credenciais de plataformas (Central de Contas e Acessos, docs/CONTAS.md). Só no worker.

- Em repouso: AES-256-GCM (criptografia autenticada) num arquivo 0600 do worker. A chave NÃO fica junto: vem da
  credencial cifrada do systemd (`LoadCredentialEncrypted=lastro-cofre`, cifrada com a chave do host, só root lê o
  original) e aparece só para este serviço em `$CREDENTIALS_DIRECTORY`. Sem chave, o cofre fica indisponível (nada
  de texto puro como plano B).
- Saída: `public()` nunca traz senha; `for_agent()` entrega a um agente só as plataformas em que ele está autorizado,
  e o agente nunca a vê: a ferramenta `aplicador_login` digita no campo, e só nos domínios da credencial.
- Mudar os domínios de uma credencial sem mandar a senha de novo apaga a senha (um web app comprometido não
  redireciona o segredo para outro site), como `registry.SECRET_BOUND` faz com as chaves de IA.
- Operação `contas` do worker: quem chama é só o web app (socket conferido por SO_PEERCRED), que exige a senha do
  dono antes de gravar ou apagar.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("lastro.mentor.cofre")
AAD = b"lastro-cofre-v1"
# Agentes que têm alguma ferramenta de login hoje. Os de Finanças só leem dados: nenhum recebe credencial.
AGENTES = ("aplicador",)
PLATFORM = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MAX_USER, MAX_SECRET, MAX_DOMAINS = 254, 512, 10


class CofreError(ValueError):
    """Mensagem segura para o dono: nunca inclui valor recebido."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_key() -> bytes | None:
    """Chave de 32 bytes em hexadecimal: credencial do systemd ou, em desenvolvimento, `LASTRO_COFRE_KEY_FILE`."""
    creds = os.environ.get("CREDENTIALS_DIRECTORY")
    path = Path(creds) / "lastro-cofre" if creds else None
    if path is None or not path.is_file():
        env = os.environ.get("LASTRO_COFRE_KEY_FILE")
        path = Path(env) if env else None
    if path is None or not path.is_file():
        return None
    try:
        key = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except ValueError:
        log.error("chave do cofre em formato inválido (esperado: 64 caracteres hexadecimais)")
        return None
    return key if len(key) == 32 else None


def clean_domains(domains) -> list[str]:
    if not isinstance(domains, list) or not domains or len(domains) > MAX_DOMAINS:
        raise CofreError(f"Informe de 1 a {MAX_DOMAINS} domínios.")
    out = []
    for d in domains:
        d = str(d).strip().lower().rstrip(".")
        if not DOMAIN.match(d):
            raise CofreError("Domínio inválido (use só o nome, como gupy.io).")
        out.append(d)
    return sorted(set(out))


def _text(value, limit: int, what: str) -> str:
    value = "" if value is None else str(value)
    if len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise CofreError(f"{what} em formato inválido.")
    return value


class Cofre:
    def __init__(self, path: Path, key: bytes | None, legacy: Path | None = None):
        self.path, self.legacy = path, legacy
        self._aes = None
        if key is not None:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            self._aes = AESGCM(key)
        self._lock = threading.Lock()

    @property
    def disponivel(self) -> bool:
        return self._aes is not None

    # ---- arquivo ----
    def _read(self) -> dict:
        if self._aes is None:
            return {}
        if not self.path.is_file():
            return self._import_legacy()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        nonce, data = base64.b64decode(raw["nonce"]), base64.b64decode(raw["dados"])
        # InvalidTag (arquivo alterado ou chave errada) sobe: nunca devolve conteúdo adulterado
        return json.loads(self._aes.decrypt(nonce, data, AAD))

    def _write(self, entries: dict) -> None:
        nonce = os.urandom(12)
        blob = self._aes.encrypt(nonce, json.dumps(entries, ensure_ascii=False).encode(), AAD)
        doc = {"versao": 1, "nonce": base64.b64encode(nonce).decode(), "dados": base64.b64encode(blob).decode()}
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".cofre-", suffix=".tmp")
        try:
            os.chmod(tmp, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _import_legacy(self) -> dict:
        """Migração única do cofre antigo em texto puro (cofre.json): cifra e renomeia o original para
        `.importado` (o operador apaga depois de conferir as candidaturas; docs/CONTAS.md)."""
        if self.legacy is None or not self.legacy.is_file():
            return {}
        old = json.loads(self.legacy.read_text(encoding="utf-8"))
        entries = {}
        for platform, cred in old.items():
            if PLATFORM.match(str(platform)) and isinstance(cred, dict) and cred.get("senha"):
                entries[platform] = {"usuario": str(cred.get("usuario", "")), "senha": str(cred["senha"]),
                                     "dominios": clean_domains(cred.get("dominios") or []),
                                     "agentes": ["aplicador"], "atualizado_em": _now()}
        self._write(entries)
        self.legacy.rename(self.legacy.with_name(self.legacy.name + ".importado"))
        log.info("cofre antigo importado: %d credencial(is)", len(entries))
        return entries

    # ---- leitura ----
    def for_agent(self, agent: str) -> dict:
        """O que um agente pode usar: só as plataformas que o autorizam (ferramenta de login, nunca o modelo)."""
        with self._lock:
            entries = self._read()
        return {p: {"usuario": e["usuario"], "senha": e["senha"], "dominios": e["dominios"]}
                for p, e in entries.items() if agent in e.get("agentes", [])}

    def public(self) -> list[dict]:
        with self._lock:
            entries = self._read()
        return [self._view(p, e) for p, e in sorted(entries.items())]

    @staticmethod
    def _view(platform: str, e: dict) -> dict:
        user = e.get("usuario", "")
        hint = (user[:2] + "…" + user[user.find("@"):]) if "@" in user else (user[:2] + "…" if user else "")
        return {"plataforma": platform, "tem_senha": bool(e.get("senha")), "usuario_dica": hint,
                "dominios": e.get("dominios", []), "agentes": e.get("agentes", []),
                "atualizado_em": e.get("atualizado_em")}

    # ---- escrita (só pelo web app, depois da senha do dono) ----
    def save(self, platform: str, *, usuario=None, senha=None, dominios=None, agentes=None) -> dict:
        if self._aes is None:
            raise CofreError("Cofre indisponível: a chave do cofre não está instalada no servidor.")
        if not PLATFORM.match(str(platform)):
            raise CofreError("Plataforma inválida.")
        with self._lock:
            entries = self._read()
            old = entries.get(platform) or {}
            entry = dict(old)
            if dominios is not None:
                entry["dominios"] = clean_domains(dominios)
                if old and entry["dominios"] != old.get("dominios") and senha is None:
                    entry["senha"] = ""  # destino mudou sem a senha: ela não segue para o domínio novo
            if not entry.get("dominios"):
                raise CofreError("Informe os domínios em que a senha pode ser digitada.")
            if usuario is not None:
                entry["usuario"] = _text(usuario.strip(), MAX_USER, "Usuário")
            if senha is not None:
                if not senha:
                    raise CofreError("Senha vazia.")
                entry["senha"] = _text(senha, MAX_SECRET, "Senha")
            if agentes is not None:
                if not isinstance(agentes, list) or any(a not in AGENTES for a in agentes):
                    raise CofreError("Agente não autorizado a usar credenciais.")
                entry["agentes"] = sorted(set(agentes))
            entry.setdefault("agentes", ["aplicador"])
            entry.setdefault("usuario", "")
            if not entry.get("senha"):
                raise CofreError("Informe a senha.")
            entry["atualizado_em"] = _now()
            entries[platform] = entry
            self._write(entries)
        log.info("credencial gravada: %s", platform)
        return self._view(platform, entry)

    def delete(self, platform: str) -> bool:
        if self._aes is None:
            raise CofreError("Cofre indisponível: a chave do cofre não está instalada no servidor.")
        with self._lock:
            entries = self._read()
            found = entries.pop(platform, None) is not None
            if found:
                self._write(entries)
        log.info("credencial revogada: %s", platform)
        return found


_COFRE: Cofre | None = None


def default() -> Cofre:
    global _COFRE
    if _COFRE is None:
        base = Path(os.environ.get("LASTRO_APLICADOR_DIR", "/var/lib/mentor/carreira"))
        _COFRE = Cofre(base / "cofre.enc", load_key(), legacy=base / "cofre.json")
    return _COFRE


ACTIONS = {"listar", "salvar", "revogar", "verificar", "desconectar"}


async def handle(browser, req: dict, cofre: Cofre | None = None) -> dict:
    """Operação `contas` do worker. Nenhuma resposta traz senha."""
    cofre = cofre or default()
    action = str(req.get("acao") or "")
    if action not in ACTIONS:
        raise ValueError("ação de contas desconhecida")
    platform = str(req.get("plataforma") or "")
    try:
        if action == "listar":
            return {"ok": True, "disponivel": cofre.disponivel, "credenciais": cofre.public()}
        if action == "salvar":
            return {"ok": True, "credencial": cofre.save(platform, usuario=req.get("usuario"), senha=req.get("senha"),
                                                         dominios=req.get("dominios"), agentes=req.get("agentes"))}
        if action == "revogar":
            return {"ok": True, "revogada": cofre.delete(platform)}
        from .aplicador import sessao

        dominios = clean_domains(req.get("dominios"))
        if action == "verificar":
            return {"ok": True, **await sessao(browser, "verificar", dominios, str(req.get("url") or ""))}
        result = await sessao(browser, "desconectar", dominios)
        return {"ok": True, **result, "revogada": cofre.delete(platform) if cofre.disponivel else False}
    except CofreError as exc:
        return {"ok": False, "detalhe": str(exc)}
