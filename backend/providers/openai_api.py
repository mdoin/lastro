"""OpenAI (Responses API, chave de API) e endpoints compatíveis com Chat Completions.

- `openai`: Responses API com `store=False` (a conversa não fica guardada na OpenAI; o histórico vem do Lastro).
- `openai_compatible` e predefinições (`ollama`, `openrouter`, `gemini`): Chat Completions no endereço que o
  operador configurar. Modelos locais variam muito: ferramentas e janela de contexto são ajustes da conexão,
  não suposições do Lastro.

O login com a conta do ChatGPT é feito pelo executável oficial do Codex (providers/codex.py), não aqui.
"""

from __future__ import annotations

import json

import openai

from .base import Emit, Provider, ProviderCapabilities, ProviderError, SessionSpec
from .loop import Call, LoopSession, Step, map_sdk_error


def _truthy(value, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "sim", "yes", "on")


class _OpenAIBase(Provider):
    default_base_url: str | None = None
    requires_key = True

    def __init__(self, connection, *, http_client=None):
        super().__init__(connection)
        self._http_client = http_client

    def is_configured(self) -> bool:
        return bool(self.connection.secret.get("api_key")) or not self.requires_key

    def client(self) -> openai.AsyncOpenAI:
        if not self.is_configured():
            raise ProviderError("not_configured", "Informe a chave de API desta conexão.")
        base_url = self.connection.settings.get("base_url") or self.default_base_url
        return openai.AsyncOpenAI(api_key=self.connection.secret.get("api_key") or "sem-chave",
                                  base_url=base_url or None, max_retries=0, http_client=self._http_client,
                                  timeout=float(self.connection.settings.get("timeout") or 600))

    async def list_models(self) -> list[dict]:
        try:
            return sorted(({"id": m.id, "label": m.id} async for m in self.client().models.list()),
                          key=lambda m: m["id"])
        except openai.APIError as exc:
            raise map_sdk_error(exc) from None


# ---------------------------------------------------------------- Responses API

class ResponsesSession(LoopSession):
    def __init__(self, provider: "OpenAIProvider", spec: SessionSpec):
        super().__init__(spec)
        self.provider = provider
        self.model = spec.model or provider.default_model
        self.tool_defs = [{"type": "function", "name": t.name, "description": t.description,
                           "parameters": t.input_schema} for t in spec.tools]

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant_text(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    async def step(self, emit: Emit) -> Step:
        kwargs = {"tools": self.tool_defs} if self.tool_defs else {}
        response = None
        try:
            stream = await self.provider.client().responses.create(
                model=self.model, instructions=self.spec.system_prompt, input=self.messages, store=False,
                stream=True, include=["reasoning.encrypted_content"], **kwargs)
            async for event in stream:
                if event.type == "response.output_text.delta":
                    await emit({"type": "delta", "text": event.delta})
                elif event.type in ("response.completed", "response.incomplete"):
                    response = event.response
                elif event.type == "response.failed":
                    code = getattr(event.response.error, "code", "") or ""
                    raise ProviderError("rate_limit" if "limit" in code else "internal", f"O provedor falhou ({code}).")
        except openai.APIError as exc:
            raise map_sdk_error(exc) from None
        if response is None:
            raise ProviderError("network", "A resposta do provedor terminou antes de concluir.")
        items = [item.model_dump(mode="json", exclude_none=True) for item in response.output]
        self.messages.extend(items)
        text = "".join(part.get("text", "") for item in items if item.get("type") == "message"
                       for part in item.get("content", []) if part.get("type") == "output_text")
        calls = [Call(item["call_id"], item["name"], item.get("arguments") or "{}")
                 for item in items if item.get("type") == "function_call"]
        if response.status == "incomplete":
            calls = []
        usage = response.usage
        return Step(text=text, calls=calls, usage={"input_tokens": getattr(usage, "input_tokens", 0),
                                                   "output_tokens": getattr(usage, "output_tokens", 0)})

    def add_tool_results(self, results) -> None:
        self.messages.extend({"type": "function_call_output", "call_id": call.id, "output": text}
                             for call, text, _ in results)


class OpenAIProvider(_OpenAIBase):
    type = "openai"
    label = "OpenAI API (chave)"
    capabilities = ProviderCapabilities(api_key=True,
                                        notes="Responses API com store=false; cobrança na sua conta da OpenAI Platform.")
    settings_schema = {"model": "modelo padrão", "base_url": "URL da API (opcional)", "timeout": "segundos"}

    async def open(self, spec: SessionSpec) -> ResponsesSession:
        if not (spec.model or self.default_model):
            raise ProviderError("not_configured", "Escolha um modelo para esta conexão.")
        return ResponsesSession(self, spec)


# ---------------------------------------------------------------- Chat Completions (compatíveis)

class ChatSession(LoopSession):
    def __init__(self, provider: "OpenAICompatibleProvider", spec: SessionSpec):
        super().__init__(spec)
        self.provider = provider
        self.model = spec.model or provider.default_model
        self.tool_defs = ([{"type": "function", "function": {"name": t.name, "description": t.description,
                                                             "parameters": t.input_schema}} for t in spec.tools]
                          if provider.tools_enabled else [])

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant_text(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    def _window(self) -> list:
        """Corta o histórico mais antigo para caber no contexto configurado (aprox. 4 caracteres por token)."""
        limit = self.provider.context_tokens
        if not limit:
            return self.messages
        budget = limit * 4 - len(self.spec.system_prompt)
        kept, size = [], 0
        for message in reversed(self.messages):
            size += len(json.dumps(message, ensure_ascii=False))
            if size > budget and kept:
                break
            kept.append(message)
        kept.reverse()
        while len(kept) > 1 and kept[0]["role"] != "user":  # nunca começa por resposta de ferramenta órfã
            kept.pop(0)
        return kept

    async def step(self, emit: Emit) -> Step:
        kwargs = {"tools": self.tool_defs} if self.tool_defs else {}
        messages = [{"role": "system", "content": self.spec.system_prompt}, *self._window()]
        text, calls, usage = "", {}, {}
        finish = None
        try:
            stream = await self.provider.client().chat.completions.create(
                model=self.model, messages=messages, stream=True, **kwargs)
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = {"input_tokens": chunk.usage.prompt_tokens or 0,
                             "output_tokens": chunk.usage.completion_tokens or 0}
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta and delta.content:
                    text += delta.content
                    await emit({"type": "delta", "text": delta.content})
                for tc in (delta.tool_calls or []) if delta else []:
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    slot["id"] = tc.id or slot["id"]
                    if tc.function:
                        slot["name"] += tc.function.name or ""
                        slot["arguments"] += tc.function.arguments or ""
                finish = choice.finish_reason or finish
        except openai.APIError as exc:
            raise map_sdk_error(exc) from None
        ordered = [calls[i] for i in sorted(calls)] if finish != "length" else []
        for i, call in enumerate(ordered):
            call["id"] = call["id"] or f"call_{len(self.messages)}_{i}"
        assistant = {"role": "assistant", "content": text or None}
        if ordered:
            assistant["tool_calls"] = [{"id": c["id"], "type": "function",
                                        "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                                       for c in ordered]
        self.messages.append(assistant)
        return Step(text=text, calls=[Call(c["id"], c["name"], c["arguments"] or "{}") for c in ordered],
                    usage=usage)

    def add_tool_results(self, results) -> None:
        self.messages.extend({"role": "tool", "tool_call_id": call.id, "content": text} for call, text, _ in results)


class OpenAICompatibleProvider(_OpenAIBase):
    type = "openai_compatible"
    label = "Endpoint compatível com OpenAI"
    requires_key = False
    capabilities = ProviderCapabilities(api_key=True, usage=False,
                                        notes="Qualquer servidor com /v1/chat/completions (LM Studio, vLLM, LiteLLM…).")
    settings_schema = {"model": "modelo", "base_url": "URL base (…/v1)", "timeout": "segundos",
                       "tools": "o modelo suporta ferramentas? (sim/não)",
                       "context_tokens": "janela de contexto em tokens (corta o histórico antigo)"}

    @property
    def tools_enabled(self) -> bool:
        return _truthy(self.connection.settings.get("tools"))

    @property
    def context_tokens(self) -> int | None:
        value = self.connection.settings.get("context_tokens")
        return int(value) if value else None

    def is_configured(self) -> bool:
        has_url = bool(self.connection.settings.get("base_url") or self.default_base_url)
        return has_url and (bool(self.connection.secret.get("api_key")) or not self.requires_key)

    def effective_capabilities(self) -> ProviderCapabilities:
        caps = self.capabilities.public()
        caps["tools"] = self.tools_enabled
        return ProviderCapabilities(**caps)

    async def open(self, spec: SessionSpec) -> ChatSession:
        if not (spec.model or self.default_model):
            raise ProviderError("not_configured", "Escolha um modelo para esta conexão.")
        return ChatSession(self, spec)


class OllamaProvider(OpenAICompatibleProvider):
    type = "ollama"
    label = "Ollama (modelo local)"
    default_base_url = "http://127.0.0.1:11434/v1"
    capabilities = ProviderCapabilities(api_key=False, usage=False,
                                        notes="Roda na sua máquina; nenhum dado sai para a internet. Capacidade de "
                                              "análise e de ferramentas depende do modelo baixado.")


class OpenRouterProvider(OpenAICompatibleProvider):
    type = "openrouter"
    label = "OpenRouter"
    requires_key = True
    default_base_url = "https://openrouter.ai/api/v1"
    capabilities = ProviderCapabilities(api_key=True, usage=False,
                                        notes="Roteia para vários provedores; a política de dados depende do modelo.")


class GeminiProvider(OpenAICompatibleProvider):
    type = "gemini"
    label = "Google Gemini (chave de API)"
    requires_key = True
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    capabilities = ProviderCapabilities(api_key=True, usage=False,
                                        notes="Usa o endpoint compatível com OpenAI documentado pelo Google.")
