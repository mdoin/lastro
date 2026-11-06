# SPDX-License-Identifier: AGPL-3.0-or-later
"""Central de Contas e Acessos (docs/CONTAS.md): plataformas, pendências dos agentes e retomada das tarefas.

Só metadados no banco. Quem usa: o web app (rotas /api/contas) e o serviço lastro-carreira (o Aplicador abre
pendência quando falta acesso). Segredos nunca passam por aqui: ficam no cofre cifrado do worker.
"""

import json
import re

from crypto.service import notify

from . import db, store

ACESSO = ("login", "cadastro", "sessao_expirada", "verificacao_identidade", "dois_fatores", "confirmacao_email")
TIPOS = (*ACESSO, "informacao_ausente")
ACAO = {"login": "Entrar na conta pelo navegador do agente (ou cadastrar a senha no cofre).",
        "cadastro": "Criar a conta pelo navegador do agente, se quiser usar esta plataforma.",
        "sessao_expirada": "Entrar de novo pelo navegador do agente.",
        "verificacao_identidade": "Concluir a verificação de identidade no navegador do agente.",
        "dois_fatores": "Concluir a autenticação em duas etapas no navegador do agente.",
        "confirmacao_email": "Confirmar o cadastro pelo link enviado ao seu e-mail.",
        "informacao_ausente": "Completar a informação pedida e marcar como resolvida."}
ESTADO = {"login": "aguardando_autenticacao", "cadastro": "nao_configurada", "sessao_expirada": "sessao_expirada",
          "verificacao_identidade": "requer_verificacao", "dois_fatores": "requer_verificacao",
          "confirmacao_email": "requer_verificacao"}
PLATFORM = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")


def plataforma_id(text: str) -> str:
    """Nome dado pelo agente ou fonte da vaga ('email-linkedin') → id da plataforma; inválido vira 'desconhecida'."""
    pid = re.sub(r"^email-", "", str(text or "").strip().lower())
    pid = re.sub(r"[^a-z0-9_-]+", "-", pid).strip("-")[:40]
    return pid if PLATFORM.match(pid) else "desconhecida"


def plataforma(conn, pid: str):
    """Linha da plataforma; uma que o agente encontrou e ainda não está no registro entra sem endereço oficial
    (o endereço vindo de página é dado não confiável: a interface mostra 'não verificado')."""
    conn.execute("INSERT OR IGNORE INTO contas_plataformas (id, nome, autenticacao, dominios_json, updated_at) "
                 "VALUES (?, ?, 'sessao', '[]', ?)", (pid, pid, db.utcnow()))
    return conn.execute("SELECT * FROM contas_plataformas WHERE id = ?", (pid,)).fetchone()


def abrir_pendencia(conn, *, plataforma_nome: str, tipo: str, agente: str, motivo: str,
                    chave: str = "") -> tuple[int, bool]:
    """Abre (ou reaproveita) a pendência. Devolve (id, nova). Nova = avisa o dono uma vez só."""
    pid = plataforma_id(plataforma_nome)
    row = plataforma(conn, pid)
    tipo = tipo if tipo in TIPOS else "login"
    motivo = str(motivo or "")[:400]
    if tipo == "cadastro" and (row["tem_credencial"] or row["ultima_autenticacao"]):
        # registro de conta existente: login que falhou não prova falta de cadastro
        tipo, motivo = "login", f"{motivo} (há registro de conta nesta plataforma: tratado como login)"[:400]
    now = db.utcnow()
    new = conn.execute("INSERT OR IGNORE INTO contas_pendencias (plataforma, agente, tipo, chave, motivo, acao, "
                       "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (pid, agente, tipo, chave, motivo or "sem motivo informado", ACAO[tipo], now)).rowcount == 1
    pend_id = conn.execute("SELECT id FROM contas_pendencias WHERE plataforma = ? AND tipo = ? AND chave = ? "
                           "AND estado = 'aberta'", (pid, tipo, chave)).fetchone()[0]
    if tipo in ESTADO:
        conn.execute("UPDATE contas_plataformas SET estado = ?, detalhe = ?, updated_at = ? WHERE id = ?",
                     (ESTADO[tipo], motivo[:300], now, pid))
    if new:
        notify(conn, store.OWNER, kind="acesso_pendente", severity="atencao",
               title=f"{row['nome']}: {ACAO[tipo].split(' (')[0].rstrip('.')}"[:200],
               body=f"{agente} pediu sua ação: {motivo}", link="/contas", ref=f"pendencia:{pend_id}")
    return pend_id, new


def bloqueadas(conn) -> set[str]:
    """Plataformas com pendência de acesso aberta: as vagas delas esperam, as das outras seguem."""
    marks = ",".join("?" * len(ACESSO))
    return {r[0] for r in conn.execute(f"SELECT DISTINCT plataforma FROM contas_pendencias WHERE estado = 'aberta' "
                                       f"AND tipo IN ({marks})", ACESSO)}


def resolver(conn, pend_id: int, *, resolucao: str, estado: str = "resolvida") -> list[str]:
    """Fecha a pendência e solta as tarefas presas nela. Devolve os ids das vagas retomadas."""
    from carreira import candidatura, registro  # o serviço de carreira importa este módulo

    pend = conn.execute("SELECT * FROM contas_pendencias WHERE id = ? AND estado = 'aberta'", (pend_id,)).fetchone()
    if pend is None:
        return []
    now = db.utcnow()
    conn.execute("UPDATE contas_pendencias SET estado = ?, resolucao = ?, resolved_at = ? WHERE id = ?",
                 (estado, resolucao[:200], now, pend_id))
    conn.execute("UPDATE notifications SET status = 'lido' WHERE kind = 'acesso_pendente' AND ref = ?",
                 (f"pendencia:{pend_id}",))
    resumed = []
    for row in conn.execute("SELECT vaga_id, status FROM carreira_candidaturas WHERE pendencia_id = ?", (pend_id,)).fetchall():
        attempts = conn.execute("SELECT COUNT(*) FROM carreira_envios WHERE vaga_id = ?", (row["vaga_id"],)).fetchone()[0]
        if estado == "descartada":
            new = "encerrada"
        elif row["status"] == "aguardando_acesso" or attempts < candidatura.MAX_ATTEMPTS:
            new = "curriculo"  # volta à fila; espera por acesso não gastou tentativa
        else:
            new = row["status"]
        conn.execute("UPDATE carreira_candidaturas SET status = ?, pendencia_id = NULL, updated_at = ? WHERE vaga_id = ?",
                     (new, now, row["vaga_id"]))
        registro.evento(conn, row["vaga_id"], "acesso_descartado" if estado == "descartada" else "retomada", "dono",
                        pendencia_id=pend_id, anterior=row["status"], novo=new)
        if new == "curriculo":
            resumed.append(row["vaga_id"])
    if resumed:  # o serviço de carreira confere este sinal a cada minuto e roda a fila sem esperar a volta de 30 min
        conn.execute("INSERT INTO carreira_estado (chave, valor) VALUES ('retomar', ?) "
                     "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor", (now,))
    return resumed


def resolver_acesso(conn, pid: str, resolucao: str) -> list[str]:
    """Sessão confirmada: fecha todas as pendências de acesso da plataforma."""
    marks = ",".join("?" * len(ACESSO))
    ids = [r[0] for r in conn.execute(f"SELECT id FROM contas_pendencias WHERE plataforma = ? AND estado = 'aberta' "
                                      f"AND tipo IN ({marks})", (pid, *ACESSO))]
    return [v for i in ids for v in resolver(conn, i, resolucao=resolucao)]


def marcar(conn, pid: str, estado: str, detalhe: str = "", *, verificada: bool = False) -> None:
    now = db.utcnow()
    conn.execute("UPDATE contas_plataformas SET estado = ?, detalhe = ?, updated_at = ?, "
                 "ultima_verificacao = CASE WHEN ? THEN ? ELSE ultima_verificacao END, "
                 "ultima_autenticacao = CASE WHEN ? = 'conectada' THEN ? ELSE ultima_autenticacao END WHERE id = ?",
                 (estado, detalhe[:300], now, verificada, now, estado, now, pid))


def listar(conn) -> dict:
    plats = [{**dict(r), "dominios": json.loads(r["dominios_json"]), "agentes": json.loads(r["agentes_json"]),
              "tem_credencial": bool(r["tem_credencial"])}
             for r in conn.execute("SELECT * FROM contas_plataformas ORDER BY modulo, nome")]
    for p in plats:
        p.pop("dominios_json"), p.pop("agentes_json")
    pend = [dict(r) for r in conn.execute(
        "SELECT p.*, pl.nome AS plataforma_nome, pl.url_oficial FROM contas_pendencias p "
        "JOIN contas_plataformas pl ON pl.id = p.plataforma "
        "WHERE p.estado = 'aberta' OR p.resolved_at >= datetime('now', '-7 days') ORDER BY p.estado, p.created_at DESC")]
    for p in pend:
        p["tarefas"] = [dict(r) for r in conn.execute(
            "SELECT v.rowid AS n, v.title, v.company, c.status FROM carreira_candidaturas c "
            "JOIN carreira_vagas v ON v.id = c.vaga_id WHERE c.pendencia_id = ? ORDER BY v.rowid", (p["id"],))]
    return {"plataformas": plats, "pendencias": pend}
