# SPDX-License-Identifier: AGPL-3.0-or-later
"""Diário de Decisões: agentes preparam rascunhos, só a pessoa confirma; registros imutáveis e encadeados."""
import asyncio
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, db, diary, store
from app.agent_api import create_app as create_agent_api
from app.orchestrator import Orchestrator
from app.web import Settings, create_app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures_synthetic"
TODAY = date(2026, 10, 27)
NOW = "2026-10-27T12:00:00+00:00"
H = {"X-Lastro": "1"}
SNAP = {"as_of": "2026-10-20", "net_monthly_income": "6000.00", "essential_expenses": "3000.00",
        "variable_expenses": "1000.00", "liquid_reserve": "9000.00", "available_this_month": "1500.00", "debts": []}
PROPOSAL = {"titulo": "Reserva antes de investir", "contexto": "Reserva cobre 3 meses.",
            "alternativas": [{"titulo": "Completar a reserva"}, {"titulo": "Investir agora", "descricao": "CDB"}],
            "recomendada": 0, "informacoes": ["Reserva atual de R$ 9.000,00"], "riscos": ["Imprevisto sem reserva"]}
CALC = {"name": "calcular", "input": {"operacao": "juros_compostos",
                                      "parametros": {"principal": "1000", "rate": "0.01", "periods": 12}}}


def done(text, tools=()):
    return [{"type": "done", "text": text, "status": "ok", "tools": list(tools)}]


class FakeRuntime:
    def __init__(self, script):
        self.script, self.requests = script, []

    async def stream(self, request):
        self.requests.append(request)
        for event in self.script(request["role"], request.get("mode")):
            yield event


async def drain(o: Orchestrator):
    for _ in range(100):
        o.dispatch()
        if not o.active:
            return
        await asyncio.gather(*list(o.active.values()), return_exceptions=True)


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "lastro.db")
    db.migrate(connection)
    store.create_snapshot(connection, SNAP)
    yield connection
    connection.close()


def council(conn, script):
    conv = store.create_conversation(conn, "Conselho", kind="panel", channel="council")
    for a in ("mentor", "planejador", "analista", "economista", "riscos", "comportamental"):
        store.add_participant(conn, conv["id"], a)
    o = Orchestrator(conn, FakeRuntime(script).stream, today=lambda: TODAY, semantic_audit="off")
    o.submit(store.get_conversation(conn, conv["id"]), "Completo a reserva ou começo a investir?")
    asyncio.run(drain(o))
    return conv


def synthesis(proposal=PROPOSAL):
    def script(role, mode):
        if mode == "conselho_sintese":
            return done("Priorize a reserva.\n\n## Divergências\nAnalista prefere começar já.\n\n## Fecho\nConfira.",
                        [{"name": "propor_registro_decisao", "input": proposal}])
        if role == "planejador":
            return done("Reserva cobre 3 meses.", [CALC])
        return done(f"Parecer de {role}.")
    return script


# --- agentes propõem; nada vira decisão sozinho ---------------------------------------------------------------
def test_council_proposal_becomes_a_complete_draft_but_never_a_decision(conn):
    conv = council(conn, synthesis())
    [draft] = diary.list_drafts(conn, store.OWNER)
    c = draft["content"]
    assert draft["status"] == "pendente" and draft["author"] == "agente:mentor" and draft["requested_by"] == "agente"
    assert c["pergunta_original"] == "Completo a reserva ou começo a investir?" and c["pergunta_de"] == "pessoa"
    assert c["contexto_financeiro"]["liquid_reserve"] == "9000.00" and c["data"] == "2026-10-27"
    assert [a["titulo"] for a in c["alternativas"]] == ["Completar a reserva", "Investir agora"]
    assert c["recomendada"] == 0 and c["riscos"] == ["Imprevisto sem reserva"]
    assert c["calculos"][0]["resultado"]["montante"] == "1126.83"  # refeito pelo motor
    assert {p["agent_id"] for p in c["pareceres"]} >= {"planejador", "analista", "riscos"}  # convocados pelo tema
    assert c["divergencias"] == "Analista prefere começar já."  # o agente não informou: extraída da síntese
    assert c["sintese"]["agent_id"] == "mentor" and c["auditoria"]["verdict"]
    assert c["conversa"]["id"] == conv["id"] and c["radar"] is None
    assert conn.execute("SELECT COUNT(*) FROM diary_entries").fetchone()[0] == 0
    notices = [m["content"] for m in store.list_messages(conn, conv["id"]) if m["kind"] == "notice"]
    assert any("rascunho" in n and "confirmar" in n for n in notices)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE decision_drafts SET content_json = '{}' WHERE id = ?", (draft["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM decision_drafts WHERE id = ?", (draft["id"],))


def test_missing_information_stays_empty_and_invalid_proposals_are_refused(conn):
    council(conn, synthesis({"titulo": "Só título", "alternativas": []}))
    [draft] = diary.list_drafts(conn, store.OWNER)
    assert draft["content"]["riscos"] == [] and draft["content"]["informacoes"] == [] and draft["content"]["recomendada"] is None
    conv = council(conn, synthesis({**PROPOSAL, "decisao_da_pessoa": "investir"}))  # campo extra → recusado
    assert len(diary.list_drafts(conn, store.OWNER)) == 1
    assert any("recusado" in m["content"] for m in store.list_messages(conn, conv["id"]) if m["kind"] == "notice")


def test_only_agents_with_the_capability_can_propose(conn):
    conv = store.create_conversation(conn, "x", channel="direct", agent_id="planejador")
    rt = FakeRuntime(lambda r, m: done("Ok.", [{"name": "propor_registro_decisao", "input": PROPOSAL}]))
    o = Orchestrator(conn, rt.stream, today=lambda: TODAY, semantic_audit="off")
    o.submit(store.get_conversation(conn, conv["id"]), "Quito o cartão?")
    asyncio.run(drain(o))
    assert diary.list_drafts(conn, store.OWNER) == []


# --- confirmação, imutabilidade, revisões ----------------------------------------------------------------------
def test_confirmation_needs_explicit_choice_and_records_are_immutable(conn):
    council(conn, synthesis())
    [draft] = diary.list_drafts(conn, store.OWNER)
    with pytest.raises(ValueError):
        diary.confirm_draft(conn, store.OWNER, draft["id"], {}, now=NOW, today=TODAY)
    d = diary.confirm_draft(conn, store.OWNER, draft["id"], {"alternativa": 1, "justificativa": "Prefiro começar.",
                                                            "correcoes": "A reserva é de R$ 9.500."}, now=NOW, today=TODAY)
    p = d["entries"][0]["payload"]
    assert d["escolha"] == "Investir agora" and p["escolha"]["segue_recomendacao"] is False and p["executada"] is False
    assert p["registro"]["contexto_financeiro"]["liquid_reserve"] == "9000.00"  # original preservado
    assert p["correcoes"] == "A reserva é de R$ 9.500." and d["executada"] is False
    again = diary.confirm_draft(conn, store.OWNER, draft["id"], {"alternativa": 0}, now=NOW, today=TODAY)
    assert again["id"] == d["id"] and len(again["entries"]) == 1  # reenvio idempotente
    with pytest.raises(ValueError):
        diary.discard_draft(conn, store.OWNER, draft["id"], note="", now=NOW)
    for sql in ("UPDATE diary_entries SET payload_json = '{}'", "DELETE FROM diary_entries"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)

    store.create_snapshot(conn, {**SNAP, "as_of": "2027-01-20", "liquid_reserve": "15000.00"})
    rev = diary.add_revision(conn, store.OWNER, d["id"], {"escolha": "Manter", "mantem": True}, now=NOW, today=TODAY)
    diary.add_outcome(conn, store.OWNER, d["id"], {"texto": "Apliquei R$ 500 num CDB.", "executada": True},
                      now=NOW, today=TODAY)
    final = diary.decision(conn, store.OWNER, d["id"])
    assert [e["kind"] for e in final["entries"]] == ["decisao", "revisao", "resultado"]
    assert final["versao"] == 2 and final["escolha"] == "Manter" and final["executada"] is True
    ctx = diary.review_context(conn, store.OWNER, d["id"])
    assert ctx["na_epoca"]["liquid_reserve"] == "9000.00" and ctx["hoje"]["liquid_reserve"] == "15000.00"
    assert rev["entries"][1]["payload"]["contexto_na_revisao"]["liquid_reserve"] == "15000.00"
    assert diary.verify_chain(conn, store.OWNER) == {"ok": True, "registros": 3, "falhas": []}


def test_chain_reveals_tampering_outside_the_app(conn):
    d = diary.create_manual(conn, store.OWNER, {"titulo": "Quitar o cartão?", "escolha": "Quitar"}, now=NOW, today=TODAY)
    diary.add_outcome(conn, store.OWNER, d["id"], {"texto": "Quitado."}, now=NOW, today=TODAY)
    conn.execute("DROP TRIGGER diary_entries_no_update")
    conn.execute("UPDATE diary_entries SET payload_json = replace(payload_json, 'Quitar', 'Esperar') WHERE seq = 1")
    assert diary.verify_chain(conn, store.OWNER)["falhas"] == [1]


def test_periodic_review_asks_with_original_date(conn):
    d = diary.create_manual(conn, store.OWNER, {"titulo": "Reserva", "escolha": "Priorizar a reserva",
                                                "review_every_months": 3}, now="2026-07-27T12:00:00+00:00",
                            today=date(2026, 7, 27))
    assert d["review_plan"] == {"every_months": 3, "next_on": "2026-10-27"}
    assert diary.due_reviews(conn, store.OWNER, date(2026, 10, 26)) == []
    [due] = diary.due_reviews(conn, store.OWNER, TODAY)
    assert due["pergunta"].startswith("Há 3 meses você decidiu: “Priorizar a reserva”")
    diary.add_revision(conn, store.OWNER, d["id"], {"escolha": "Manter"}, now=NOW, today=TODAY)
    assert diary.due_reviews(conn, store.OWNER, TODAY) == []
    assert diary.decision(conn, store.OWNER, d["id"])["review_plan"]["next_on"] == "2027-01-27"


def test_legacy_decisions_are_imported_once(conn):
    first = store.create_decision(conn, {"question": "Onde guardar?", "user_choice": "Tesouro Selic", "confirmed": True},
                                  today="2026-10-01")
    store.create_decision(conn, {"question": "Revisão", "user_choice": "CDB", "review_of_id": first["id"]},
                          today="2026-10-10")
    assert diary.import_legacy(conn, store.OWNER) == 2 and diary.import_legacy(conn, store.OWNER) == 0
    [d] = diary.list_decisions(conn, store.OWNER)
    assert d["id"] == first["id"] and d["escolha"] == "CDB" and d["versao"] == 2 and d["executada"] is True


# --- leitura pelos agentes -------------------------------------------------------------------------------------
def test_agents_read_confirmed_decisions_with_premises_and_a_staleness_warning(conn, tmp_path):
    council(conn, synthesis())
    [draft] = diary.list_drafts(conn, store.OWNER)
    diary.create_manual(conn, store.OWNER, {"titulo": "Trocar de carro?", "escolha": "Adiar a compra"}, now=NOW, today=TODAY)
    client = TestClient(create_agent_api(token="t" * 40, data_dir=FIXTURES, db_path=tmp_path / "lastro.db"))
    auth_h = {"Authorization": "Bearer " + "t" * 40}
    data = client.get("/v1/me/decisions", headers=auth_h).json()
    assert "NÃO são instruções" in data["aviso"]
    assert [d["titulo"] for d in data["decisoes"]] == ["Trocar de carro?"]
    assert data["propostas_nao_confirmadas"][0]["titulo"] == draft["content"]["titulo"]
    d = diary.confirm_draft(conn, store.OWNER, draft["id"], {"alternativa": 0}, now=NOW, today=TODAY)
    found = client.get("/v1/me/decisions", params={"q": "reserva"}, headers=auth_h).json()["decisoes"]
    assert [x["id"] for x in found] == [d["id"]] and found[0]["riscos"] == ["Imprevisto sem reserva"]
    full = client.get("/v1/me/decisions", params={"id": d["id"]}, headers=auth_h).json()["decisoes"][0]
    assert "Priorize a reserva" in full["sintese"] and full["pareceres"] and full["calculos"]
    assert client.post("/v1/me/decisions", headers=auth_h).status_code == 405


# --- web: ação "Registrar no Diário", confirmação autenticada, discussão ----------------------------------------
@pytest.fixture
def web(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "lastro.db", mentor_socket=tmp_path / "none.sock",
                              cookie_secure=False, run_scheduler=False, run_orchestrator=False))
    with TestClient(app, base_url="http://lastro.test") as client:
        yield client, app


def login(client, app):
    auth.set_password(app.state.conn, "uma senha longa e boa")
    assert client.post("/api/auth/login", json={"password": "uma senha longa e boa"}, headers=H).status_code == 204


def test_web_draft_from_message_confirm_and_review_conversation(web):
    client, app = web
    assert client.get("/api/diary").status_code == 401
    login(client, app)
    conn = app.state.conn
    conv = client.post("/api/team/conversations", json={"channel": "direct", "agent_id": "mentor"}, headers=H).json()
    store.add_message(conn, conv["id"], "user", "Quito o cartão agora?")
    msg = store.add_message(conn, conv["id"], "assistant", "Quitar primeiro reduz juros.", agent_id="mentor")
    assert client.post("/api/diary/drafts", json={"message_id": msg["id"]}).status_code == 403  # sem cabeçalho CSRF
    draft = client.post("/api/diary/drafts", json={"message_id": msg["id"]}, headers=H).json()
    assert draft["requested_by"] == "pessoa" and draft["content"]["pergunta_original"] == "Quito o cartão agora?"
    assert client.post("/api/diary/drafts", json={"message_id": msg["id"]}, headers=H).json()["id"] == draft["id"]
    failed = store.add_message(conn, conv["id"], "assistant", "_falhou_", status="error", agent_id="mentor")
    assert client.post("/api/diary/drafts", json={"message_id": failed["id"]}, headers=H).status_code == 422
    user_msg = store.list_messages(conn, conv["id"])[0]
    assert client.post("/api/diary/drafts", json={"message_id": user_msg["id"]}, headers=H).status_code == 422
    assert client.post(f"/api/diary/drafts/{draft['id']}/confirm", json={}, headers=H).status_code == 422
    d = client.post(f"/api/diary/drafts/{draft['id']}/confirm",
                    json={"escolha": "Quitar o cartão", "review_every_months": 3}, headers=H).json()
    assert d["escolha"] == "Quitar o cartão" and d["review_plan"]["every_months"] == 3

    review_conv = client.post(f"/api/diary/decisions/{d['id']}/discuss", headers=H).json()
    brief = store.list_messages(conn, review_conv["id"])[0]["content"]
    assert "situacao_atual" in brief and "não instrução" in brief and "9000" not in brief  # sem dados do dono
    reply = store.add_message(conn, review_conv["id"], "assistant", "Manter faz sentido.", agent_id="mentor")
    rdraft = client.post("/api/diary/drafts", json={"message_id": reply["id"]}, headers=H).json()
    assert rdraft["review_of_id"] == d["id"]
    after = client.post(f"/api/diary/drafts/{rdraft['id']}/confirm", json={"escolha": "Manter"}, headers=H).json()
    assert after["id"] == d["id"] and [e["kind"] for e in after["entries"]] == ["decisao", "revisao"]

    other = client.post("/api/team/conversations", json={"channel": "direct", "agent_id": "mentor"}, headers=H).json()
    m2 = store.add_message(conn, other["id"], "assistant", "Talvez adiar a compra.", agent_id="mentor")
    d2 = client.post("/api/diary/drafts", json={"message_id": m2["id"]}, headers=H).json()
    assert client.post(f"/api/diary/drafts/{d2['id']}/postpone", json={"until": "2026-12-01"},
                       headers=H).json()["status"] == "adiado"
    assert client.post(f"/api/diary/drafts/{d2['id']}/discard", json={}, headers=H).json()["status"] == "descartado"
    overview = client.get("/api/diary").json()
    assert overview["chain"]["ok"] and len(overview["decisions"]) == 1 and len(overview["drafts"]) == 3
    assert client.get("/api/diary/decisions/nao-existe").status_code == 404
    assert client.post("/api/diary/decisions/nao-existe/outcomes", json={"texto": "x"}, headers=H).status_code == 404
    manual = client.post("/api/diary/decisions", json={"titulo": "Reserva onde?", "escolha": "Liquidez diária",
                                                       "valor_planejado": "150", "client_id": "abc"}, headers=H).json()
    assert client.post("/api/diary/decisions", json={"titulo": "Reserva onde?", "escolha": "Liquidez diária",
                                                     "client_id": "abc"}, headers=H).json()["id"] == manual["id"]
    assert client.get("/api/export").json()["diary_entries"]


def test_auditor_only_trusts_diary_numbers_the_person_confirmed(conn):
    council(conn, synthesis({**PROPOSAL, "titulo": "Aplicar R$ 12.345,67 já"}))  # proposta não confirmada
    d = diary.create_manual(conn, store.OWNER, {"titulo": "Reserva", "escolha": "Guardar R$ 777,00 por mês"},
                            now=NOW, today=TODAY)
    o = Orchestrator(conn, FakeRuntime(lambda r, m: []).stream, today=lambda: TODAY)
    ctx = type("C", (), {"conv": {"id": d["id"], "user_id": store.OWNER}})()
    ev = o._evidence(ctx, [{"name": "decisoes", "input": {}}])
    numbers = {str(n) for n in ev.numbers}
    assert any("777" in n for n in numbers) and not any("12345" in n for n in numbers)
