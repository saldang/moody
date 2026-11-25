# 04 · PKI e identità

Questo documento spiega come Moody sostituisce **Microsoft Entra ID** e la gestione dei certificati
del progetto originale: una **PKI privata a due CA** per l'autenticazione reciproca (mTLS) di
dispositivi e servizi, più **Keycloak** (OIDC) tra gateway e brain nel profilo enterprise. Copre la
creazione, il rinnovo, la revoca e le pratiche consigliate per una struttura.

## Prerequisiti

- Server preparato come in [03 · Setup ambiente](03-setup-ambiente.md).
- `./scripts/setup.sh` già eseguito: ha creato `.venv/` e la PKI in `deploy/pki/`.

---

## 1. Perché due CA

| CA | Firma | Chi la considera affidabile | Cosa permette |
|---|---|---|---|
| `device-ca` | certificati dei dispositivi (solo `clientAuth`) | **solo il gateway** | Un dispositivo si collega al gateway |
| `service-ca` | gateway, brain, wellbeing, keycloak (`serverAuth`+`clientAuth`) | dispositivi (per verificare il gateway) e servizi tra loro | I servizi si autenticano a vicenda |

Un certificato estratto da un dispositivo rubato **non viene accettato** da brain e tool, perché
quelli si fidano solo della `service-ca`. Il test `test_service_cert_cannot_connect_as_device`
verifica anche il caso inverso.

Scelte crittografiche (`server/moody/pki.py`):

- ECDSA **P‑256** per tutte le chiavi: accelerazione hardware su ESP32‑S3, certificati piccoli.
- Root valide 10 anni, certificati dei servizi **397 giorni**, dei dispositivi **365 giorni**
  (personalizzabile con `--days`).
- Chiavi delle CA scritte con permessi `0600`, cifrabili con passphrase (`MOODY_CA_PASSPHRASE`).
- I dispositivi generano la propria chiave **sul chip**: il server firma solo una **CSR**. La CN deve
  avere la forma `moody-xxxxxx` e coincidere con l'ID dichiarato dal dispositivo.

## 2. Struttura dei file

```text
deploy/pki/
├── device-ca/ca.key, ca.pem       # ⚠️ chiave: tienila OFFLINE dopo il provisioning
├── service-ca/ca.key, ca.pem
├── services/<nome>/tls.key, tls.pem
└── issued.csv                      # registro: seriale, CN, scadenza dei certificati emessi
```

## 3. Comandi

Tutti i comandi si lanciano dalla root del repository:

```bash
export MOODY_PKI_DIR=deploy/pki        # default
# (facoltativo) cifra le chiavi delle CA
export MOODY_CA_PASSPHRASE='una-passphrase-lunga'

# Creare le due CA (idempotente: non sovrascrive)
.venv/bin/python -m moody.pki init

# Certificato di un servizio (SAN DNS/IP per il gateway: il nome usato dai dispositivi!)
.venv/bin/python -m moody.pki service gateway --dns moody.lan --ip 192.168.10.5

# Firmare una CSR a mano (di solito lo fa provision.py)
.venv/bin/python -m moody.pki sign-csr device.csr --cn moody-a1b2c3 --out device.pem

# Revocare un certificato (aggiunge il seriale a revoked_serials in devices.yaml)
.venv/bin/python -m moody.pki revoke 5F3A9C... --devices-file deploy/config/devices.yaml
```

> ⚠️ **Attenzione**: il certificato del gateway deve contenere il nome host **esattamente** come
> compare nell'URL di provisioning (`wss://moody.lan:8443/v1/ws`). Usa preferibilmente un nome DNS:
> la verifica degli IP nel SAN dipende dalla versione di mbedTLS.

## 4. Revoca e disattivazione

Il gateway rilegge `deploy/config/devices.yaml` **a ogni nuova connessione** (non serve riavviare):

```yaml
devices:
  moody-a1b2c3:
    subject: res-001
    enabled: false            # disattivazione temporanea (es. ricovero)
revoked_serials:
  - 5F3A9C...                 # revoca definitiva (dispositivo perso/rubato)
```

Una connessione già aperta resta attiva fino alla disconnessione: per chiuderla subito riavvia il
gateway (`docker compose restart gateway`). Al prossimo tentativo riceve **HTTP 403** prima
dell'upgrade WebSocket (evento di audit `device_rejected`).

I seriali li trovi in `deploy/pki/issued.csv` oppure nell'output di `provision.py`.

## 5. Rinnovo

| Cosa | Quando | Come |
|---|---|---|
| Certificati dei servizi | prima dei 397 giorni | `rm -r deploy/pki/services/<nome>` → `./scripts/setup.sh` (ricrea solo i mancanti) → `docker compose up -d --force-recreate` |
| Certificato di un dispositivo | prima dei 365 giorni | factory reset (tieni premuto lo schermo 10 s) → di nuovo `provision.py`; revoca il seriale vecchio |
| CA | ogni 5–10 anni o in caso di compromissione | nuova PKI, nuovo provisioning di tutti i dispositivi |

Il firmware v0.1 non rinnova i certificati da solo: è un rinnovo manuale, consapevole. Per flotte
grandi vedi la sezione enterprise qui sotto.

## 6. Custodia delle chiavi

- **Backup offline** di `deploy/pki/*/ca.key` (chiavetta cifrata in cassaforte, due copie).
- Dopo il provisioning, togli `device-ca/ca.key` dal server: serve solo per firmare nuovi
  dispositivi. Se il server viene compromesso, l'attaccante non può creare nuovi dispositivi falsi.
- La `service-ca/ca.key` serve solo per (ri)emettere certificati dei servizi: anche questa può
  stare offline.
- Mai mettere le chiavi nel repository: `.gitignore` esclude `deploy/pki/*`, `*.key`, `*.pem`.

## 7. Enterprise: PKI su scala

Per una struttura con decine o centinaia di dispositivi lo script incluso è un punto di partenza;
in produzione si raccomanda:

1. **Root offline** (laptop air‑gapped o **YubiHSM 2**) che firma due **intermedie**: una per i
   dispositivi, una per i servizi.
2. **step‑ca** (Smallstep, Apache‑2.0) come CA online per le intermedie, con provisioner separati
   e certificati a **vita breve** (es. 30–90 giorni) per i servizi.
3. **Separazione dei compiti**: chi fa il provisioning dei dispositivi non amministra i server, chi
   custodisce la root non fa provisioning.
4. Una **postazione di provisioning** dedicata (vedi [08 · Sicurezza enterprise](08-sicurezza-enterprise.md)).

> ℹ️ Il gateway verifica la catena con la sola CA configurata in `MOODY_DEVICE_CA`. Con
> un'intermedia, metti nel file la catena completa (intermedia + root) e verifica la configurazione
> con un dispositivo di test prima del rollout.

## 8. Keycloak al posto di Entra ID (profilo enterprise)

`deploy/compose.enterprise.yaml` aggiunge **Keycloak** (Apache‑2.0) e PostgreSQL:

| Elemento | Configurazione |
|---|---|
| Realm | `moody` (`deploy/config/keycloak/realm-moody.json`): solo TLS, protezione brute force, token di 5 minuti, policy password robusta |
| Client `moody-gateway` | confidential, **solo client‑credentials** (nessun login interattivo), mapper di audience `moody-brain` |
| Brain | verifica firma (JWKS), `iss`, `aud`, scadenza e che il client sia `moody-gateway` (`server/moody/brain/auth.py`) |
| Ruoli | `moody-operator`, `moody-dpo` (predisposti per strumenti di amministrazione futuri) |
| Console admin | pubblicata solo su `127.0.0.1:8444`: si raggiunge con un tunnel SSH |

Il token OIDC si **aggiunge** a mTLS, non lo sostituisce: per chiamare il brain servono sia un
certificato della `service-ca` sia un token valido (difesa in profondità).

```bash
./scripts/setup.sh --hostname moody.lan --ip 192.168.10.5 --enterprise   # genera segreti e cert keycloak
cd deploy && docker compose -f compose.yaml -f compose.enterprise.yaml up -d

# accesso alla console admin dal tuo PC (aggiungi "127.0.0.1 keycloak" al file hosts del PC)
ssh -L 8444:127.0.0.1:8444 utente@moody-server
# poi apri https://keycloak:8444/admin  (attiva subito la MFA per gli amministratori)
```

> ⚠️ **Attenzione**: l'immagine di Keycloak gira con UID 1000. Se il tuo utente sul server ha un
> UID diverso, rendi leggibile `deploy/pki/services/keycloak/` a quell'UID (es. `chown 1000`).

---

Prossimo passo → [05 · Setup del dispositivo](05-setup-device.md)
