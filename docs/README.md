# Documentazione di Moody

Guida passo passo, nell'ordine in cui serve.

| # | Documento | Contenuto |
|---|---|---|
| 00 | [Architettura](00-architettura.md) | I tre livelli, mappatura Microsoft → open source, flussi, confini di fiducia |
| 01 | [Lista della spesa](01-acquisto.md) | Hardware per casa ed enterprise, prezzi indicativi, dimensionamento |
| 02 | [Montaggio](02-montaggio.md) | BOX‑3, posizionamento, accessibilità, server e rete |
| 03 | [Setup ambiente](03-setup-ambiente.md) | Sistema operativo, hardening, Docker, `setup.sh`, modelli QVAC, Home Assistant |
| 04 | [PKI e identità](04-pki-identita.md) | Due CA, revoca, rinnovo, custodia chiavi, Keycloak |
| 05 | [Setup del dispositivo](05-setup-device.md) | Build, flash, provisioning, Secure Boot, Flash Encryption, OTA |
| 06 | [Running](06-running.md) | Avvio, uso quotidiano, knowledge base, backup, troubleshooting |
| 07 | [Sicurezza – casa](07-sicurezza-home.md) | Threat model e controlli per l'ambiente domestico |
| 08 | [Sicurezza – enterprise](08-sicurezza-enterprise.md) | Senior living: governance, consenso, ciclo di vita dei dispositivi, PKI su scala |
| 09 | [Privacy by design](09-privacy-by-design.md) | GDPR art. 25, inventario dati, AI Act, DPIA |
| 10 | [Licenze](10-licenze.md) | Analisi delle licenze per un repository MIT |
| 11 | [Red teaming](11-red-teaming.md) | Test avversariali con harness, promptfoo e garak |
| 12 | [Protocollo](12-protocollo.md) | Specifica del protocollo edge ⇄ gateway `moody.v1` |
| 13 | [QVAC (Tether)](13-qvac.md) | Runtime AI di default: modelli, configurazione, varianti offline/HTTPS, prestazioni misurate |
