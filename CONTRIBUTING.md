# Contribuire a Moody

Grazie! Alcune regole per mantenere il progetto sicuro, rispettoso della privacy e con licenza MIT pulita.

1. **Privacy prima di tutto**: nessuna nuova raccolta di dati senza una motivazione scritta nella PR
   (cosa, perché, per quanto tempo, cifratura). Niente telemetria, niente servizi cloud obbligatori.
2. **Licenze**: ogni nuova dipendenza deve avere una licenza compatibile con MIT (MIT, BSD, Apache‑2.0,
   ISC…). Componenti copyleft (GPL/AGPL) solo come **servizi separati** e documentati in
   [docs/10-licenze.md](docs/10-licenze.md). Segui la checklist in quel documento.
3. **Sicurezza**: le modifiche a guardrail, policy dei tool, TLS/PKI o firmware richiedono test.
   Non indebolire i default (deny‑by‑default, mTLS, retention).
4. **Niente affermazioni mediche**: Moody non è un dispositivo medico; testi e prompt non devono
   promettere diagnosi o terapie.
5. **Test e lint**: `cd server && pip install -e ".[dev]" && pytest && ruff check moody tests`.
   Per il firmware: build con `espressif/idf:v5.5.6` (vedi `docs/05-setup-device.md`).
6. **Mai committare segreti**: `deploy/.env`, `deploy/pki/`, `deploy/secrets/`, chiavi di firma.

Commit piccoli e descrittivi; documentazione in italiano, codice e commenti in inglese.
