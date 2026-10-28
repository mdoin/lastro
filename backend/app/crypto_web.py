# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotas do Radar cripto e da central de notificações (docs/CRYPTO.md).

Escrita só de preferências, da chave da CoinGecko (que nunca volta ao navegador) e de pedidos de análise; nada aqui
movimenta ativos. Tudo filtra pela pessoa autenticada.
"""

import asyncio
import time
import uuid
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from crypto import service


class CryptoPrefsIn(BaseModel):
    watchlist: list[str] | None = Field(None, max_length=20)
    holdings: dict[str, str] | None = None
    sensitivity: Literal["baixa", "media", "alta"] | None = None
    muted: list[str] | None = Field(None, max_length=10)
    concentration_limit: str | None = Field(None, pattern=r"^0(\.\d{1,4})?$|^1(\.0+)?$")
    autonomous: bool | None = None
    deliver: Literal["alertas", "analises"] | None = None
    min_severity: Literal["atencao", "risco", "conselho"] | None = None
    max_meetings_per_day: int | None = Field(None, ge=0, le=10)
    cooldown_hours: int | None = Field(None, ge=1, le=168)
    quiet_start: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    quiet_end: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    paused_until: datetime | None = None
    clear_pause: bool = False
    monthly_token_budget: int | None = Field(None, ge=0, le=100_000_000)


class KeyIn(BaseModel):
    key: str = Field(min_length=10, max_length=80)


def _uuid(value: str) -> str:
    try:
        uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail="Inexistente.") from None
    return value


def register(app: FastAPI, conn, *, current_user, log_access, monitor: service.Monitor) -> None:
    @app.get("/api/crypto/overview")
    async def crypto_overview(user: str = Depends(current_user)):
        return monitor.overview()

    @app.put("/api/crypto/prefs")
    async def crypto_prefs(body: CryptoPrefsIn, user: str = Depends(current_user)):
        data = body.model_dump(exclude_none=True)
        if data.pop("clear_pause", False):
            data["paused_until"] = None
        elif "paused_until" in data:
            data["paused_until"] = data["paused_until"].isoformat()
        try:
            out = service.save_prefs(conn, user, data)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        log_access(user, "crypto.prefs", "autonomas" if out["autonomous"] else "alertas")
        return out

    @app.put("/api/crypto/coingecko-key", status_code=204)
    async def crypto_key_set(body: KeyIn, user: str = Depends(current_user)):
        if not monitor.key_file:
            raise HTTPException(status_code=409, detail="Instalação sem pasta de dados para a chave.")
        try:
            service.write_key(monitor.key_file, body.key.strip())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        monitor.reload_keys()
        log_access(user, "crypto.key", "coingecko")  # nunca a chave

    @app.delete("/api/crypto/coingecko-key", status_code=204)
    async def crypto_key_delete(user: str = Depends(current_user)):
        if monitor.key_file:
            service.write_key(monitor.key_file, None)
        monitor.reload_keys()
        log_access(user, "crypto.key.delete", "coingecko")

    @app.post("/api/crypto/providers/{name}/test")
    async def crypto_test(name: Literal["binance", "coingecko", "defillama"], user: str = Depends(current_user)):
        """Teste de conectividade e de obtenção de dados, com uma chamada leve e real."""
        if not monitor.collect_in_web:
            monitor.request_collection()
            return {"provider": name, "ok": None, "latency_ms": 0, "quota": None,
                    "detail": "Teste pedido ao coletor (o único processo com saída à internet); o resultado aparece no "
                              "status da fonte em até 1 minuto."}
        prov = monitor.providers[name]
        started = time.monotonic()

        def call():
            if name == "binance":
                q = prov.stats_24h("BTC")
                return f"BTC = {q.price} {q.quote_currency} (ref. {service._iso(q.reference_time)})"
            if name == "coingecko":
                q = next(q for q in prov.simple_price(["bitcoin"], ("brl",), purpose="user"))
                return f"BTC = R$ {q.price} (ref. {service._iso(q.reference_time)})"
            return f"{len(prov.chains())} redes com TVL"
        try:
            detail = await asyncio.to_thread(call)
            ok = True
        except Exception as exc:  # noqa: BLE001 — a mensagem é curta e nunca contém a chave (sources a protege)
            detail, ok = f"{type(exc).__name__}: {str(exc)[:200]}", False
        log_access(user, "crypto.test", name, "ok" if ok else "falhou")
        return {"provider": name, "ok": ok, "detail": detail, "latency_ms": int((time.monotonic() - started) * 1000),
                "quota": prov.quota() if name == "coingecko" and getattr(prov, "configured", False) else None}

    @app.post("/api/crypto/collect")
    async def crypto_collect(user: str = Depends(current_user)):
        log_access(user, "crypto.collect", "manual")
        if not monitor.collect_in_web:
            monitor.request_collection()
            return {"requested": True, "detail": "Coleta pedida ao coletor; os dados chegam em até 1 minuto."}
        return await monitor.tick(force=True)

    @app.post("/api/crypto/events/{event_id}/convene")
    async def crypto_convene(event_id: str, user: str = Depends(current_user)):
        try:
            status = monitor.convene_manually(_uuid(event_id))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        log_access(user, "crypto.convene", event_id)
        return {"status": status, "event": monitor._event(event_id)}

    # --- central de notificações ---

    @app.get("/api/notifications")
    async def notifications_list(user: str = Depends(current_user)):
        rows = conn.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
                            (user,)).fetchall()
        return {"items": [dict(r) for r in rows],
                "unread": sum(1 for r in rows if r["status"] == "novo")}

    @app.post("/api/notifications/{notification_id}/read", status_code=204)
    async def notification_read(notification_id: str, user: str = Depends(current_user)):
        if not conn.execute("UPDATE notifications SET status = 'lido' WHERE id = ? AND user_id = ?",
                            (_uuid(notification_id), user)).rowcount:
            raise HTTPException(status_code=404, detail="Notificação inexistente.")

    @app.post("/api/notifications/read-all", status_code=204)
    async def notifications_read_all(user: str = Depends(current_user)):
        conn.execute("UPDATE notifications SET status = 'lido' WHERE user_id = ? AND status = 'novo'", (user,))
