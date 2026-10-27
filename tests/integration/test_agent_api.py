from decimal import Decimal


def test_health(client, auth):
    body = client.get("/v1/health", headers=auth).json()
    assert body["mode"] == "read-only" and body["data_kind"] == "synthetic"


def test_personas_listing(client, auth):
    body = client.get("/v1/personas", headers=auth).json()
    assert {p["id"] for p in body["personas"]} >= {"iniciante-150", "cartao-rotativo"}


def test_diagnosis_for_debt_persona(client, auth):
    body = client.get("/v1/personas/cartao-rotativo/diagnosis", headers=auth).json()
    assert body["guidance"]["stage"] == "priorizar_divida"
    assert body["as_of"] == "2026-10-26"


def test_unknown_persona_404(client, auth):
    assert client.get("/v1/personas/nao-existe/diagnosis", headers=auth).status_code == 404


def test_three_reproducible_projections(client, auth):
    url = "/v1/projection?initial=1000&contribution=300&months=120"
    first, second = client.get(url, headers=auth).json(), client.get(url, headers=auth).json()
    assert first == second
    projections = first["projections"]
    assert [p["scenario"] for p in projections] == ["conservador", "base", "otimista"]
    for p in projections:
        assert Decimal(p["final_nominal"]) > Decimal(p["final_real_todays_money"])
        assert p["assumptions"]["annual_inflation"] and p["limitations"]
    assert "não são previsão" in first["assumptions_note"].lower() or "Não são previsão" in first["assumptions_note"]


def test_bad_params_rejected(client, auth):
    assert client.get("/v1/projection?contribution=1,5", headers=auth).status_code == 422
    assert client.get("/v1/projection?months=-1", headers=auth).status_code == 422
    assert client.get("/v1/projection?months=99999", headers=auth).status_code == 422
