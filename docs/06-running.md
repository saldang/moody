# 06 · Avvio e uso quotidiano

Come avviare Moody, verificare che tutto funzioni, fare la prima conversazione e gestire il
sistema nel tempo: knowledge base, dispositivi, aggiornamenti, backup e soluzione dei problemi più
comuni. Per i comandi si presume di essere nella cartella del repository sul server.

## Prerequisiti

- Server configurato come in [03-setup-ambiente.md](03-setup-ambiente.md): `setup.sh` eseguito,
  modelli scaricati, ntfy configurato.
- Almeno un dispositivo flashato e registrato come in [05-setup-device.md](05-setup-device.md),
  presente in `deploy/config/devices.yaml`.

---

## 1. Avvio

```bash
cd deploy
docker compose up -d                                              # casa
docker compose -f compose.yaml -f compose.gpu.yaml up -d          # casa con GPU NVIDIA
docker compose -f compose.yaml -f compose.enterprise.yaml up -d   # struttura (Keycloak/OIDC)
```

Al primo avvio Docker costruisce l'immagine `moody/server` da `../server`: unica immagine, con tre
entrypoint (`moody-gateway`, `moody-brain`, `moody-wellbeing`). Gli override si combinano, ad
esempio `-f compose.yaml -f compose.gpu.yaml -f compose.enterprise.yaml`.

> 💡 **Suggerimento:** per non ripetere i `-f` crea un alias, ad esempio
> `alias mc='docker compose -f compose.yaml -f compose.enterprise.yaml'`, oppure imposta
> `COMPOSE_FILE=compose.yaml:compose.enterprise.yaml` in `deploy/.env`.

## 2. Verifiche

### 2.1 Stato dei container

```bash
docker compose ps
```

Devono risultare `running`: `gateway`, `brain`, `wellbeing`, `ollama`, `whisper`, `piper`, `ntfy`
(più `keycloak` e `keycloak-db` in enterprise).

### 2.2 Log (JSON, con redazione dei dati personali)

```bash
docker compose logs -f gateway brain wellbeing
docker compose logs brain | grep '"event"'          # solo eventi di audit
```

Ogni riga è un oggetto JSON con `ts`, `level`, `logger`, `msg` ed eventuali campi di audit. Gli
eventi utili:

| Evento | Servizio | Significato |
|---|---|---|
| `gateway listening` | gateway | Il gateway è in ascolto sulla porta 8443 |
| `device_connected` / `device_disconnected` | gateway | Un dispositivo autorizzato si è connesso o disconnesso |
| `device_rejected` | gateway | Certificato sconosciuto, disabilitato o revocato (HTTP 403) |
| `device_duplicate_connection` | gateway | Due connessioni con lo stesso certificato: **possibile clonazione** |
| `turn_completed` | gateway | Turno vocale completato, con `category` e `latency_ms` |
| `knowledge indexed` | brain | Knowledge base indicizzata all'avvio (`new_chunks`) |
| `tool_called`, `tool_confirmation_requested`, `tool_confirmed` | brain | Uso degli strumenti |
| `safety_escalation`, `input_blocked` | brain | Guardrail attivati (crisi, emergenza, prompt injection) |
| `help_requested` | wellbeing | Notifica di aiuto inviata via ntfy |

Le trascrizioni **non** compaiono nei log, a meno che `MOODY_LOG_TRANSCRIPTS=true` (sconsigliato,
e anche in quel caso il testo passa dalla redazione PII).

### 2.3 Health check del brain

Il brain accetta solo connessioni mTLS da certificati della service-CA. Il modo più semplice per
interrogarlo è dal suo stesso container, con il suo certificato:

```bash
docker compose exec brain python -c "import httpx,ssl; c=ssl.create_default_context(cafile='/pki/service-ca.pem'); c.load_cert_chain('/pki/self/tls.pem','/pki/self/tls.key'); print(httpx.get('https://brain:8080/healthz', verify=c).text)"
# atteso: {"ok":true}
```

### 2.4 Il gateway risponde (dalla VLAN IoT o dal server)

```bash
openssl s_client -connect moody.lan:8443 -CAfile deploy/pki/service-ca/ca.pem </dev/null 2>&1 | grep -E "Verify return code|subject="
```

Ci aspettiamo `Verify return code: 0 (ok)`. Senza un certificato client la connessione WebSocket
viene comunque rifiutata: è il comportamento corretto.

## 3. La prima conversazione

1. Accendi il dispositivo: si connette al Wi-Fi e poi al gateway. Lo schermo mostra lo stato
   **a riposo**: *"Di' Hi ESP o tocca lo schermo"*.
2. Pronuncia **"Hi ESP"** (wake word riconosciuta **sul dispositivo** da ESP-SR WakeNet9) oppure
   **tocca lo schermo** (push-to-talk).
3. Il dispositivo passa a **in ascolto**, con l'**indicatore rosso di privacy**. Solo da questo
   momento l'audio viene inviato al gateway.
4. Parla normalmente. Il dispositivo chiude l'ascolto quando rileva la fine della frase (al massimo
   15 secondi per frase).
5. Stato **sto pensando**: il gateway trascrive (Whisper) e passa il testo al brain. Sul display
   compare ciò che è stato capito.
6. Stato **sto parlando**: la risposta viene letta da Piper e mostrata sul display.
7. Se la risposta è una **domanda** (ad esempio una conferma), il dispositivo riapre l'ascolto per
   circa **6 secondi** senza bisogno della wake word, poi torna a riposo.

Per interrompere Moody mentre parla, tocca lo schermo. Con il **mute hardware** attivo
(indicatore rosso sul pulsante) nessun suono viene captato.

### Frasi d'esempio

| Cosa vuoi fare | Prova a dire | Cosa succede |
|---|---|---|
| Check-in dell'umore | "Oggi mi sento abbastanza bene, direi un quattro." | `mood_checkin` registra il punteggio (cifrato) |
| Andamento dell'umore | "Come è andato il mio umore questa settimana?" | `mood_summary` riassume media e tendenza |
| Promemoria | "Ricordami di bere un bicchiere d'acqua tra 30 minuti." | `set_reminder`. Al momento giusto il dispositivo lo legge, tranne nelle `quiet_hours` |
| Promemoria a orario | "Ricordami alle 17:30 di chiamare mia figlia." | Prossima occorrenza delle 17:30 |
| Elenco promemoria | "Quali promemoria ho?" | `list_reminders` |
| Respirazione | "Mi guidi in un esercizio di respirazione?" | `breathing_exercise` (quadrata, 4-7-8, coerente) |
| Attività (knowledge base) | "Che attività ci sono martedì?" / "A che ora è il pranzo?" | Risposta basata su `deploy/knowledge/*.md` |
| Chiedere aiuto | "Puoi avvisare qualcuno? Ho bisogno di una mano." | `request_help`: notifica ntfy al contatto o allo staff |
| Cancellare i propri dati | "Cancella tutti i miei dati." → Moody chiede conferma → "Sì." | `erase_my_data` (richiede conferma per policy) |
| Domotica (se HA è configurato) | "Accendi la luce del soggiorno." | Tool `homeassistant.*` consentiti dalla policy |

> ⚠️ **Attenzione:** frasi di **crisi** (es. pensieri di farsi del male) o di **emergenza**
> (es. "sono caduto e non riesco ad alzarmi") **non arrivano al LLM**. Moody risponde con un
> messaggio fisso e verificato che invita a chiamare il 112. In caso di emergenza avvisa subito il
> contatto o lo staff. In caso di crisi chiede prima conferma (o avvisa direttamente se
> `MOODY_ESCALATION=auto`). Moody **non** sostituisce il 112 né il campanello di chiamata.

## 4. Aggiornare la knowledge base

1. Modifica o aggiungi file Markdown in `deploy/knowledge/` (calendario attività, orari, regole).
   Solo contenuti generali, **mai dati personali** (vedi `deploy/knowledge/README.md`).
2. Riavvia il brain: reindicizza solo i file cambiati e rimuove quelli cancellati.
   ```bash
   cd deploy && docker compose restart brain
   docker compose logs brain | grep "knowledge indexed"
   ```

## 5. Gestire i dispositivi

### Aggiungere un dispositivo

Dopo il provisioning ([05-setup-device.md](05-setup-device.md)) aggiungi il CN a
`deploy/config/devices.yaml`:

```yaml
devices:
  moody-a1b2c3:
    subject: res-001          # pseudonimo, MAI nomi o camere
    enabled: true
    quiet_hours: "22:00-07:30"
```

Il gateway **ricarica il file a caldo** a ogni nuova connessione: non serve riavviare nulla.

### Sospendere o revocare

- **Sospensione temporanea:** `enabled: false`.
- **Revoca definitiva** (dispositivo perso, rubato o dismesso): trova il seriale in
  `deploy/pki/issued.csv` (colonne `seriale,CN,scadenza`) e lancia:
  ```bash
  .venv/bin/python -m moody.pki revoke <SERIALE_HEX> --devices-file deploy/config/devices.yaml
  ```
  Il seriale finisce in `revoked_serials` e il gateway rifiuta il certificato (HTTP 403) anche se
  il CN è ancora presente. Una connessione già attiva cade al primo riavvio del gateway o alla
  riconnessione: per tagliarla subito usa `docker compose restart gateway`.

## 6. Aggiornamenti

Tutte le immagini sono **fissate a una versione** in `deploy/.env` (`OLLAMA_VERSION`,
`WHISPER_VERSION`, `PIPER_VERSION`, `NTFY_VERSION`, `KEYCLOAK_VERSION`).

1. Leggi il changelog della nuova versione (sicurezza, cambi di configurazione).
2. Aggiorna il numero di versione in `deploy/.env`.
3. Applica:
   ```bash
   cd deploy
   docker compose pull
   docker compose up -d
   ```
4. Per il codice di Moody: `git pull` nel repository, poi `docker compose build && docker compose up -d`.
5. Controlla i log e fai una conversazione di prova.

> ℹ️ Le immagini dei modelli girano senza Internet. Un cambio di modello (`MOODY_LLM_MODEL`,
> `WHISPER_MODEL`, `PIPER_VOICE`) richiede di rilanciare `./scripts/bootstrap-models.sh`.

## 7. Backup

| Cosa | Dove | Come conservarlo |
|---|---|---|
| Chiavi delle CA | `deploy/pki/*/ca.key` | **Offline** (chiavetta cifrata in cassaforte), mai insieme ai backup ordinari |
| Certificati e `issued.csv` | `deploy/pki/` (senza `ca.key`) | Backup ordinario |
| Segreti | `deploy/secrets/` | Backup cifrato. La `data_key` va conservata **separata** dal database |
| Diario dell'umore e promemoria (cifrati) | `deploy/data/wellbeing/` | Backup cifrato |
| Configurazione | `deploy/.env`, `deploy/config/`, `deploy/knowledge/` | Backup cifrato (`.env` contiene password in enterprise) |
| Indice della knowledge base | `deploy/data/brain/` | Facoltativo: si ricostruisce da solo |

Esempio con **restic** (BSD-2-Clause), backup cifrato su un disco o un NAS:

```bash
sudo apt install -y restic
export RESTIC_REPOSITORY=/mnt/backup/moody RESTIC_PASSWORD_FILE=~/.restic-pass
restic init                                            # solo la prima volta
restic backup deploy/data/wellbeing deploy/config deploy/knowledge deploy/.env \
  --exclude 'deploy/pki/*/ca.key'
restic forget --keep-daily 7 --keep-weekly 4 --prune   # rispetta anche la retention GDPR
```

Fai il backup di `deploy/secrets/data_key` **in un repository diverso** (o su carta/password
manager): chi ruba il backup del database senza la chiave non può leggerlo.

> ⚠️ **Attenzione: retention.** I backup conservano i dati oltre i `MOODY_RETENTION_DAYS`. Tieni
> la rotazione dei backup coerente con l'informativa privacy e ricorda che una richiesta di
> cancellazione vale anche per i backup, alla loro scadenza naturale
> ([09-privacy-by-design.md](09-privacy-by-design.md)).

## 8. Soluzione dei problemi

| Sintomo | Causa probabile | Soluzione |
|---|---|---|
| Il dispositivo mostra un errore di connessione e il gateway non registra nulla | Wi-Fi sbagliato, VLAN IoT che non raggiunge `server:8443`, DNS `moody.lan` non risolto | Verifica SSID e password, regole firewall/`DOCKER-USER`, record DNS (o usa l'IP nell'URL) |
| Errore TLS sul dispositivo | Orologio non sincronizzato (i certificati "non ancora validi"), CA sbagliata nel provisioning, nome o IP non presente nei SAN del certificato del gateway | Controlla che il dispositivo raggiunga un server NTP. Rifai il provisioning con la `service-ca` corretta. Rigenera il certificato del gateway con `moody.pki service gateway --dns ... --ip ...` |
| `device_rejected` nei log (HTTP 403) | CN non presente in `devices.yaml`, `enabled: false` o seriale revocato | Aggiungi o abilita il dispositivo. Se è revocato serve un nuovo provisioning |
| `device_duplicate_connection` | Due dispositivi con lo stesso certificato | Indaga: possibile clonazione. Revoca il seriale e rifai il provisioning |
| Moody risponde "Non ho capito bene" o lo STT è vuoto | Mute hardware attivo, microfono coperto, frase troppo breve o sottovoce, modello Whisper troppo piccolo | Togli il mute, avvicinati, prova `WHISPER_MODEL=small-int8` o `medium-int8` |
| Risposte molto lente | Modello troppo grande per l'hardware, modello scaricato dalla RAM | Usa `qwen3:4b`. Con GPU usa `compose.gpu.yaml`. Controlla `docker compose logs ollama` |
| "Ho avuto un problema tecnico" | Errore nel brain (LLM o tool non raggiungibile) | `docker compose logs brain`: cerca `turn failed` o `tool provider ... unavailable` |
| Il contatto non riceve notifiche di aiuto | Token ntfy mancante, topic vuoto, app non iscritta, `MOODY_NTFY_BIND` non raggiungibile dal telefono | Rilancia `./scripts/ntfy-setup.sh`, poi `docker compose restart wellbeing`. Verifica `help_requested` nei log |
| I promemoria non suonano | Fascia `quiet_hours` attiva, dispositivo disconnesso | Controlla `devices.yaml` e lo stato della connessione |
| La knowledge base viene ignorata | `MOODY_EMBED_MODEL` vuoto o modello non scaricato | Imposta `bge-m3`, poi `bootstrap-models.sh` e `docker compose restart brain` |
| Il container non legge chiavi o certificati (permission denied) | `MOODY_UID`/`MOODY_GID` diversi dal proprietario dei file in `deploy/` | Allinea i valori in `.env` all'utente che ha eseguito `setup.sh` (`id -u`, `id -g`) |

## 9. Eseguire i test

```bash
cd server
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                # unit test + test end-to-end mTLS del gateway
ruff check moody tests
```

I test coprono redazione PII, guardrail (crisi, emergenza, prompt injection, dosaggi), cifratura e
retention del database, policy dei tool (iniezione del `subject`, conferme), knowledge base e un
turno vocale completo via WebSocket con mTLS, compreso il rifiuto di dispositivi sconosciuti,
disabilitati o revocati. Per i test sul comportamento del modello vedi
[11-red-teaming.md](11-red-teaming.md).

---

Prossimo passo → [07 · Sicurezza in casa](07-sicurezza-home.md) · [08 · Sicurezza enterprise](08-sicurezza-enterprise.md)
