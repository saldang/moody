# moody (server package)

Python services of [Moody](../README.md), the privacy-first open-source wellbeing voice assistant:

- `moody-gateway` - WSS + mutual TLS edge gateway, device registry, voice pipeline, signed OTA
- `moody-brain` - guardrails, agent loop, local RAG, deny-by-default MCP tool policy
- `moody-wellbeing` - MCP server: encrypted mood journal, reminders, help requests
- `python -m moody.pki` - private PKI (device CA + service CA)

AI runtime: QVAC by Tether through its OpenAI-compatible API (default) or Ollama/Wyoming.
Documentation: [../docs](../docs/README.md). License: MIT.
