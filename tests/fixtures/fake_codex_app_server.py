# SPDX-License-Identifier: AGPL-3.0-or-later
"""`codex app-server` falso para testes: JSON por linha em stdio, registra tudo que recebe em FAKE_CODEX_LOG.

No turno, pede ao cliente uma ferramenta fora da concessão, uma aprovação de comando nativo e um pedido
desconhecido, e só então responde com texto, consumo e fim do turno.
"""

import json
import os
import sys

LOG = open(os.environ["FAKE_CODEX_LOG"], "a", encoding="utf-8")


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def receive():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    message = json.loads(line)
    LOG.write(json.dumps(message) + "\n")
    LOG.flush()
    return message


def wait_for(request_id):
    while True:
        message = receive()
        if message.get("id") == request_id and "method" not in message:
            return message


while True:
    msg = receive()
    method, thread = msg.get("method"), "th1"
    if method == "initialize":
        send({"id": msg["id"], "result": {"userAgent": "fake"}})
    elif method == "thread/start":
        send({"id": msg["id"], "result": {"thread": {"id": thread}, "model": "fake"}})
    elif method == "turn/start":
        send({"id": msg["id"], "result": {"turn": {"id": "tu1", "status": "inProgress"}}})
        base = {"threadId": thread, "turnId": "tu1"}
        send({"id": 100, "method": "item/tool/call",
              "params": {**base, "callId": "c1", "namespace": None, "tool": "transferir_dinheiro", "arguments": {}}})
        wait_for(100)
        send({"id": 101, "method": "item/commandExecution/requestApproval", "params": {**base, "itemId": "i0"}})
        wait_for(101)
        send({"id": 102, "method": "account/chatgptAuthTokens/refresh", "params": {}})
        wait_for(102)
        send({"method": "item/agentMessage/delta", "params": {**base, "itemId": "i1", "delta": "Vou consultar. "}})
        send({"method": "item/agentMessage/delta", "params": {**base, "itemId": "i2", "delta": "Resposta final."}})
        send({"method": "thread/tokenUsage/updated",
              "params": {**base, "tokenUsage": {"last": {"inputTokens": 11, "outputTokens": 4}}}})
        send({"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": "tu1", "status": "completed"}}})
    elif "id" in msg and "method" in msg:
        send({"id": msg["id"], "result": {}})
