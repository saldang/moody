"""Minimal LLM clients. No vendor SDK: plain HTTP, easy to audit.

* ``OllamaClient``  - native Ollama ``/api/chat`` (home default).
* ``OpenAICompatClient`` - any OpenAI-compatible server: vLLM, llama.cpp server,
  LocalAI (enterprise default with GPUs).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class ChatResult:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult: ...

    def assistant_message(self, result: ChatResult) -> dict: ...

    def tool_message(self, call: ToolCall, content: str) -> dict: ...


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


class OllamaClient:
    def __init__(self, base_url: str, model: str, *, temperature: float = 0.4, timeout: float = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self._http = httpx.AsyncClient(trust_env=False, timeout=timeout)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,  # voice UX: no long hidden reasoning
            "keep_alive": "30m",
            "options": {"temperature": self.temperature, "num_ctx": 8192},
        }
        if tools:
            payload["tools"] = tools
        resp = await self._http.post(f"{self.base_url}/api/chat", json=payload)
        resp.raise_for_status()
        msg = resp.json().get("message", {})
        calls = [
            ToolCall(c["function"]["name"], _parse_args(c["function"].get("arguments")))
            for c in msg.get("tool_calls") or []
        ]
        return ChatResult(msg.get("content") or "", calls)

    def assistant_message(self, result: ChatResult) -> dict:
        return {
            "role": "assistant",
            "content": result.content,
            "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}} for c in result.tool_calls],
        }

    def tool_message(self, call: ToolCall, content: str) -> dict:
        return {"role": "tool", "tool_name": call.name, "content": content}


class OpenAICompatClient:
    """OpenAI-compatible chat API: QVAC (``qvac serve --openai``), vLLM, llama.cpp server, LocalAI.

    ``no_think`` appends Qwen3's ``/no_think`` soft switch to the system prompt, for servers
    (like QVAC) that expose no thinking flag: voice replies must be short and fast.
    """

    def __init__(self, base_url: str, model: str, *, api_key: str = "", temperature: float = 0.4,
                 timeout: float = 120, no_think: bool = False, max_tokens: int = 400) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.no_think = no_think
        self.max_tokens = max_tokens
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(trust_env=False, timeout=timeout, headers=headers)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        if self.no_think and messages and messages[0].get("role") == "system":
            messages = [{**messages[0], "content": messages[0]["content"] + "\n/no_think"}, *messages[1:]]
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": self.temperature,
                                   "max_tokens": self.max_tokens}
        if tools:
            payload["tools"] = tools
        resp = await self._http.post(f"{self.base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        calls = [
            ToolCall(c["function"]["name"], _parse_args(c["function"].get("arguments")), c.get("id", ""))
            for c in msg.get("tool_calls") or []
        ]
        return ChatResult(msg.get("content") or "", calls)

    def assistant_message(self, result: ChatResult) -> dict:
        return {
            "role": "assistant",
            "content": result.content or None,
            "tool_calls": [
                {"id": c.id or f"call_{i}", "type": "function",
                 "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                for i, c in enumerate(result.tool_calls)
            ],
        }

    def tool_message(self, call: ToolCall, content: str) -> dict:
        return {"role": "tool", "tool_call_id": call.id or "call_0", "content": content}
