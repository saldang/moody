"""Wire the brain together from environment variables and serve it over mTLS."""

from __future__ import annotations

import asyncio
import logging
import ssl
from pathlib import Path

import uvicorn

from ..common.config import env, env_bool, env_int, read_secret
from ..common.logging import setup_logging
from ..common.tls import TLSFiles, client_context
from .agent import Agent, AgentSettings
from .app import create_app
from .auth import OIDCVerifier
from .guardrails import GuardModel
from .llm import OllamaClient, OpenAICompatClient
from .rag import KnowledgeBase, OllamaEmbedder, OpenAICompatEmbedder
from .tools import MCPProvider, ToolPolicy, ToolRegistry

log = logging.getLogger("moody.brain")


def build_agent() -> Agent:
    # Default: QVAC by Tether (OpenAI-compatible). "ollama" keeps the native Ollama API.
    backend = env("MOODY_LLM_BACKEND", "openai")
    llm_url = env("MOODY_LLM_URL", "http://qvac:11435/v1" if backend == "openai" else "http://ollama:11434")
    model = env("MOODY_LLM_MODEL", "moody-llm" if backend == "openai" else "qwen3:8b")
    if backend == "openai":
        llm = OpenAICompatClient(llm_url, model, api_key=read_secret("MOODY_LLM_API_KEY", ""),
                                 no_think=env_bool("MOODY_LLM_NO_THINK", False),
                                 temperature=float(env("MOODY_LLM_TEMPERATURE", "0.2")))
    else:
        llm = OllamaClient(llm_url, model, temperature=float(env("MOODY_LLM_TEMPERATURE", "0.2")))

    tls = TLSFiles(Path(env("MOODY_TLS_CERT", required=True)), Path(env("MOODY_TLS_KEY", required=True)),
                   Path(env("MOODY_TLS_CA", required=True)))
    providers = [MCPProvider("wellbeing", env("MOODY_WELLBEING_URL", "https://wellbeing:8090/mcp"),
                             ssl_context=client_context(tls))]
    if env("MOODY_HA_MCP_URL"):
        # Home Assistant "Model Context Protocol Server" integration (long-lived token).
        providers.append(MCPProvider("homeassistant", env("MOODY_HA_MCP_URL"),
                                     bearer_token=read_secret("MOODY_HA_TOKEN")))
    registry = ToolRegistry(providers, ToolPolicy.load(env("MOODY_TOOL_POLICY", "/config/tool-policy.yaml")))

    kb = None
    embed_model = env("MOODY_EMBED_MODEL", "moody-embed" if backend == "openai" else "bge-m3")
    if embed_model.lower() not in ("none", "off", "false"):  # "none" disables the knowledge base
        data_dir = Path(env("MOODY_DATA_DIR", "/data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        embed_url = env("MOODY_EMBED_URL", llm_url)
        if env("MOODY_EMBED_BACKEND", backend) == "openai":
            embedder = OpenAICompatEmbedder(embed_url, embed_model, read_secret("MOODY_LLM_API_KEY", ""))
        else:
            embedder = OllamaEmbedder(embed_url, embed_model)
        kb = KnowledgeBase(data_dir / "knowledge.sqlite3", embedder,
                           min_score=float(env("MOODY_RAG_MIN_SCORE", "0.55")))

    guard_model = env("MOODY_GUARD_MODEL")
    guard = GuardModel(env("MOODY_GUARD_URL", llm_url), guard_model) if guard_model else None

    settings = AgentSettings(
        locale=env("MOODY_LOCALE", "it"),
        tz=env("TZ", "Europe/Rome"),
        log_transcripts=env_bool("MOODY_LOG_TRANSCRIPTS", False),
        escalation=env("MOODY_ESCALATION", "ask"),
    )
    return Agent(llm, registry, kb, settings, guard)


def main() -> None:
    setup_logging(env("MOODY_LOG_LEVEL", "INFO"))
    agent = build_agent()

    verifier = None
    if env("MOODY_OIDC_ISSUER"):
        # Keycloak presents a service-CA certificate: trust only that CA (no client cert needed).
        ca_only = ssl.create_default_context(cafile=env("MOODY_TLS_CA"))
        verifier = OIDCVerifier(
            env("MOODY_OIDC_ISSUER"), env("MOODY_OIDC_AUDIENCE", "moody-brain"),
            {c for c in env("MOODY_OIDC_ALLOWED_CLIENTS", "moody-gateway").split(",") if c},
            env("MOODY_OIDC_JWKS_URL"),
            ssl_context=ca_only,
        )

    async def index_knowledge() -> None:
        """Index in the background, retrying while the AI runtime is still loading its models."""
        folder = Path(env("MOODY_KNOWLEDGE_DIR", "/knowledge"))
        delay = 5.0
        while True:
            try:
                added = await agent.kb.index_dir(folder)  # type: ignore[union-attr]
                log.info("knowledge indexed", extra={"fields": {"new_chunks": added}})
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("knowledge indexing failed (retry in %ds): %s", int(delay), type(exc).__name__)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)

    background: set[asyncio.Task] = set()

    async def startup() -> None:
        if agent.kb is not None:
            task = asyncio.create_task(index_knowledge())
            background.add(task)
            task.add_done_callback(background.discard)
        await agent.tools.refresh(force=True)

    config = uvicorn.Config(
        create_app(agent, verifier),
        host="0.0.0.0",  # noqa: S104 - container-internal network only
        port=env_int("MOODY_BRAIN_PORT", 8080),
        ssl_certfile=env("MOODY_TLS_CERT"),
        ssl_keyfile=env("MOODY_TLS_KEY"),
        ssl_ca_certs=env("MOODY_TLS_CA"),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        log_config=None,
        server_header=False,
    )

    async def run() -> None:
        await startup()
        await uvicorn.Server(config).serve()

    asyncio.run(run())


if __name__ == "__main__":
    main()
