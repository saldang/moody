"""Tool layer: MCP clients + an explicit, deny-by-default tool policy.

Open-source replacement for a managed agent tool catalogue. Key properties:

* **Deny by default**: a tool the policy does not mention is invisible to the LLM.
* **Confirm** tier: sensitive actions need a spoken "si" in the next turn.
* **Hard deny patterns** (locks, alarms, cameras...) win over everything.
* **Server-side identity injection**: parameters such as ``subject`` are removed
  from the schema the LLM sees and filled from the authenticated device.
* **Rate limiting** per subject, to contain runaway loops or abuse.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import ssl
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml

log = logging.getLogger("moody.tools")

Decision = Literal["allow", "confirm", "deny"]
INJECTED_PARAMS = ("subject",)


@dataclass
class ToolPolicy:
    tools: dict[str, Decision] = field(default_factory=dict)
    deny_patterns: list[str] = field(default_factory=list)
    internal_only: list[str] = field(default_factory=list)
    rate_limit_per_minute: int = 10

    @classmethod
    def load(cls, path: Path | str) -> ToolPolicy:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(
            tools={k: v for k, v in (data.get("tools") or {}).items()},
            deny_patterns=[p.lower() for p in data.get("deny_patterns") or []],
            internal_only=list(data.get("internal_only") or []),
            rate_limit_per_minute=int(data.get("rate_limit_per_minute", 10)),
        )

    def decide(self, name: str) -> Decision:
        lowered = name.lower()
        if any(fnmatch.fnmatch(lowered, p) for p in self.deny_patterns):
            return "deny"
        if name in self.internal_only:
            return "deny"  # callable by the system, never by the LLM
        decision = self.tools.get(name)
        if decision is None:
            # allow wildcard entries such as "homeassistant.Hass*"
            for pattern, value in self.tools.items():
                if "*" in pattern and fnmatch.fnmatch(name, pattern):
                    decision = value
                    break
        return decision if decision in ("allow", "confirm") else "deny"


@dataclass
class ToolSpec:
    name: str  # "<server>.<tool>"
    description: str
    parameters: dict[str, Any]
    injected: tuple[str, ...]


class ToolProvider(Protocol):
    name: str

    async def list_tools(self) -> list[ToolSpec]: ...

    async def call(self, tool: str, arguments: dict[str, Any]) -> str: ...


def _root_cause(exc: BaseException) -> str:
    """Unwrap ExceptionGroup/__cause__ chains (anyio, httpx) into a short, loggable reason."""
    while True:
        if isinstance(exc, BaseExceptionGroup) and exc.exceptions:
            exc = exc.exceptions[0]
        elif exc.__cause__ is not None:
            exc = exc.__cause__
        else:
            return f"{type(exc).__name__}: {str(exc)[:160]}"


def _strip_injected(schema: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    schema = json.loads(json.dumps(schema or {"type": "object", "properties": {}}))
    props = schema.get("properties", {})
    injected = tuple(p for p in INJECTED_PARAMS if p in props)
    for p in injected:
        props.pop(p, None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"] if r not in injected]
    schema.pop("title", None)
    return schema, injected


class MCPProvider:
    """Connects to an MCP server over Streamable HTTP (mTLS or bearer token)."""

    def __init__(self, name: str, url: str, *, ssl_context: ssl.SSLContext | None = None,
                 bearer_token: str = "", timeout: float = 15) -> None:
        self.name = name
        self.url = url
        self.ssl_context = ssl_context
        self.bearer_token = bearer_token
        self.timeout = timeout

    def _client(self):  # noqa: ANN202 - mcp types are an implementation detail here
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client

        headers = {"Authorization": f"Bearer {self.bearer_token}"} if self.bearer_token else {}
        http = httpx2.AsyncClient(trust_env=False, headers=headers, verify=self.ssl_context or True,
                                  timeout=self.timeout)
        return Client(streamable_http_client(self.url, http_client=http), read_timeout_seconds=self.timeout)

    async def list_tools(self) -> list[ToolSpec]:
        async with self._client() as client:
            result = await client.list_tools()
        specs = []
        for tool in result.tools:
            params, injected = _strip_injected(tool.input_schema)
            specs.append(ToolSpec(f"{self.name}.{tool.name}", (tool.description or "")[:500], params, injected))
        return specs

    async def call(self, tool: str, arguments: dict[str, Any]) -> str:
        async with self._client() as client:
            result = await client.call_tool(tool, arguments)
        text = " ".join(getattr(c, "text", "") for c in result.content).strip()
        if result.is_error:
            return json.dumps({"error": text[:300] or "tool error"})
        return text[:4000]


class ToolRegistry:
    def __init__(self, providers: list[ToolProvider], policy: ToolPolicy) -> None:
        self.providers = {p.name: p for p in providers}
        self.policy = policy
        self._specs: dict[str, ToolSpec] = {}
        self._refreshed = 0.0
        self._calls: dict[str, deque[float]] = defaultdict(deque)

    async def refresh(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._refreshed < 300 and self._specs:
            return
        specs: dict[str, ToolSpec] = {}
        for provider in self.providers.values():
            try:
                for spec in await provider.list_tools():
                    specs[spec.name] = spec
            except Exception as exc:  # noqa: BLE001 - a broken provider must not break the assistant
                log.warning("tool provider %s unavailable: %s", provider.name, _root_cause(exc))
        self._specs = specs
        self._refreshed = time.monotonic()

    def llm_tools(self) -> list[dict[str, Any]]:
        """Tool definitions exposed to the LLM (policy-filtered, identity params hidden)."""
        out = []
        for spec in self._specs.values():
            if self.policy.decide(spec.name) == "deny":
                continue
            out.append({
                "type": "function",
                "function": {
                    # dots are not valid in some tool-name grammars: use "__"
                    "name": spec.name.replace(".", "__"),
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            })
        return out

    def resolve(self, llm_name: str) -> str:
        return llm_name.replace("__", ".", 1)

    def decide(self, name: str) -> Decision:
        return self.policy.decide(name) if name in self._specs else "deny"

    def _rate_ok(self, subject: str) -> bool:
        window = self._calls[subject]
        now = time.monotonic()
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.policy.rate_limit_per_minute:
            return False
        window.append(now)
        return True

    async def call(self, name: str, arguments: dict[str, Any], *, subject: str,
                   system: bool = False) -> str:
        """Execute a tool. ``system=True`` bypasses the LLM policy (used for internal calls)."""
        spec = self._specs.get(name)
        if spec is None:
            await self.refresh(force=True)
            spec = self._specs.get(name)
        if spec is None:
            return json.dumps({"error": "unknown tool"})
        if not system and self.policy.decide(name) == "deny":
            return json.dumps({"error": "tool not allowed"})
        if not self._rate_ok(subject):
            return json.dumps({"error": "rate limit"})
        args = {k: v for k, v in arguments.items() if k not in INJECTED_PARAMS}
        for param in spec.injected:
            args[param] = subject
        server, tool = name.split(".", 1)
        return await self.providers[server].call(tool, args)
