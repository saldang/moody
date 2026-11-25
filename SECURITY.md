# Security policy

Moody handles voice, wellbeing data and help requests of potentially vulnerable people:
we take security reports seriously.

## Reporting a vulnerability

- **Do not open a public issue.** Use GitHub's private vulnerability reporting
  ("Security" tab → "Report a vulnerability") on this repository.
- Include: affected component (firmware / gateway / brain / wellbeing / deploy), version or commit,
  reproduction steps, impact. A proof of concept helps, real personal data does not: never send it.
- We aim to acknowledge within 5 working days and to agree on a disclosure date (default 90 days).

## Scope

In scope: code and configuration in this repository (firmware, `server/`, `deploy/`, `scripts/`),
including guardrail bypasses that lead to unsafe behaviour (e.g. medication dosage advice,
mishandled crisis phrases, cross-resident data access, tool policy bypass).

Out of scope: vulnerabilities in upstream projects (report them upstream: ESP-IDF, Ollama,
Piper, faster-whisper, Keycloak, ntfy...), denial of service requiring LAN access you already
control, social engineering.

## Supported versions

Only the latest release on `main` receives security fixes during the 0.x series.

## Hardening baseline

See [docs/07-sicurezza-home.md](docs/07-sicurezza-home.md) and
[docs/08-sicurezza-enterprise.md](docs/08-sicurezza-enterprise.md).
Production devices must run the **release** firmware (Secure Boot V2 + Flash Encryption).
