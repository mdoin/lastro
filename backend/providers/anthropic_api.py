"""Anthropic (Claude) pela Messages API, com chave da Claude Console.

É o caminho que a Anthropic indica para produtos construídos sobre o Claude
(https://code.claude.com/docs/en/legal-and-compliance). Sem estado no provedor: o histórico da sessão é
reenviado a cada passo (providers/loop.py).
"""

from __future__ import annotations

import anthropic

from .base import Emit, Provider, ProviderCapabilities, ProviderError, SessionSpec
from .loop import Call, LoopSession, Step, map_sdk_error

DEFAULT_MAX_TOKENS = 32000


class AnthropicSession(LoopSession):
    def __init__(self, provider: "AnthropicProvider", spec: SessionSpec):
        super().__init__(spec)
        self.provider = provider
        self.model = spec.model or provider.default_model
        self.tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.input_schema}
                          for t in spec.tools]

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant_text(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    async def step(self, emit: Emit) -> Step:
        client = self.provider.client()
        kwargs = {"tools": self.tool_defs} if self.tool_defs else {}
        try:
            async with client.messages.stream(model=self.model, max_tokens=self.provider.max_tokens,
                                              system=self.spec.system_prompt, messages=self.messages,
                                              **kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        await emit({"type": "delta", "text": event.delta.text})
                message = await stream.get_final_message()
        except anthropic.APIError as exc:
            raise map_sdk_error(exc) from None
        if message.stop_reason == "refusal":
            raise ProviderError("internal", "O modelo recusou a solicitação.")
        # Blocos voltam como vieram (inclusive thinking), como a API exige.
        self.messages.append({"role": "assistant",
                              "content": [b.model_dump(mode="json", exclude_none=True) for b in message.content]})
        text = "".join(b.text for b in message.content if b.type == "text")
        calls = [Call(b.id, b.name, b.input) for b in message.content if b.type == "tool_use"]
        if message.stop_reason == "max_tokens":
            calls = []  # entrada de ferramenta possivelmente truncada: não executa
        usage = {"input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens}
        return Step(text=text, calls=calls, usage=usage)

    def add_tool_results(self, results) -> None:
        # Todos os resultados de um passo vão numa única mensagem.
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call.id, "content": text, "is_error": is_error}
            for call, text, is_error in results]})


class AnthropicProvider(Provider):
    type = "anthropic"
    label = "Anthropic API (Claude)"
    capabilities = ProviderCapabilities(api_key=True, notes="Chave da Claude Console; cobrança na sua conta Anthropic.")
    settings_schema = {"model": "modelo padrão (ex.: claude-opus-5-5)", "base_url": "URL da API (opcional)",
                       "max_tokens": "limite de saída por passo", "timeout": "segundos por requisição"}

    def __init__(self, connection, *, http_client=None):
        super().__init__(connection)
        self._http_client = http_client

    @property
    def max_tokens(self) -> int:
        return int(self.connection.settings.get("max_tokens") or DEFAULT_MAX_TOKENS)

    def is_configured(self) -> bool:
        return bool(self.connection.secret.get("api_key"))

    def client(self) -> anthropic.AsyncAnthropic:
        if not self.is_configured():
            raise ProviderError("not_configured", "Informe a chave da API da Anthropic.")
        # api_key explícita: nunca cai em variáveis de ambiente ou perfis do disco do worker.
        return anthropic.AsyncAnthropic(api_key=self.connection.secret["api_key"],
                                        base_url=self.connection.settings.get("base_url") or None,
                                        timeout=float(self.connection.settings.get("timeout") or 600),
                                        max_retries=0, http_client=self._http_client)

    async def open(self, spec: SessionSpec) -> AnthropicSession:
        if not (spec.model or self.default_model):
            raise ProviderError("not_configured", "Escolha um modelo para esta conexão.")
        return AnthropicSession(self, spec)

    async def list_models(self) -> list[dict]:
        try:
            return [{"id": m.id, "label": m.display_name} async for m in self.client().models.list()]
        except anthropic.APIError as exc:
            raise map_sdk_error(exc) from None
