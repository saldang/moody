# 07 · Sicurezza in ambiente domestico

Questa guida descrive come proteggere un'installazione di Moody **in casa**: un dispositivo
ESP32-S3-BOX-3 (o pochi), un piccolo server locale, la rete di casa. Moody è progettato per essere
*secure by default*: buona parte delle protezioni è già attiva dopo `scripts/setup.sh`. Qui spieghiamo
**da cosa ci proteggiamo**, **quale meccanismo lo fa** e **cosa devi fare tu** (router, firewall, backup,
aggiornamenti).

> ℹ️ **Nota**: se installi Moody in una struttura (senior living, RSA, residenze), leggi anche
> [08-sicurezza-enterprise.md](08-sicurezza-enterprise.md). Le misure domestiche restano la base.

---

## 1. Modello delle minacce (STRIDE semplificato)

| # | Scenario | Categoria STRIDE | Impatto | Controlli principali in Moody |
|---|----------|------------------|---------|-------------------------------|
| T1 | **Dispositivo rubato o perso** (o portato via da un ospite) | Spoofing, Information disclosure | Uso del certificato per parlare col gateway; estrazione di Wi‑Fi e chiavi dalla flash | Chiave privata generata **sul dispositivo**; Flash Encryption + NVS encryption + Secure Boot v2 in release; revoca del seriale in `devices.yaml`; un solo collegamento attivo per dispositivo |
| T2 | **Vicino sulla Wi‑Fi** o qualcuno che conosce la password Wi‑Fi | Spoofing, Tampering | Connessione al gateway, intercettazione del traffico | mTLS obbligatorio (senza certificato firmato dalla *device CA* il TLS fallisce); TLS 1.2+ con sole suite ECDHE+AEAD verso i dispositivi, TLS 1.3 tra servizi |
| T3 | **Dispositivo IoT compromesso sulla LAN** (TV, telecamera cinese, presa smart) | Elevation of privilege, Information disclosure | Scansione e attacco al server Moody | VLAN/SSID IoT separato; gateway unico servizio esposto; reti Docker `internal`; firewall host |
| T4 | **Contenuto malevolo / prompt injection** (frase detta, documento nella knowledge base, output di un tool) | Tampering, Elevation of privilege | Il modello esegue azioni non volute (aprire porte, cancellare dati) | Guardrail deterministici prima dell'LLM; policy dei tool *deny by default* con pattern di blocco duro; livello *confirm*; documenti e output tool marcati come dati non fidati |
| T5 | **Fuga di dati verso il cloud** | Information disclosure | Conversazioni o umore inviati a terzi | Nessun servizio cloud: STT, LLM, TTS, RAG tutti locali in QVAC; runtime senza Internet (reti `internal`); nessuna telemetria nel codice Moody né documentata in QVAC; il registry P2P di QVAC si contatta solo durante il bootstrap |
| T6 | **Backup persi o rubati** | Information disclosure | Esposizione di chiavi CA, diario dell'umore | Diario cifrato (Fernet) e pseudonimizzato (HMAC); chiave dati separata dal DB; chiavi CA offline e cifrate con passphrase |
| T7 | **Familiari curiosi** che chiedono a Moody cosa ha detto un'altra persona | Information disclosure | Violazione della privacy domestica | Nessuna memoria a lungo termine delle conversazioni (sessione in RAM ≤ 10 minuti); niente trascrizioni nei log; il riepilogo umore richiede il dispositivo della persona |
| T8 | **Ascolto ambientale** (il timore "mi ascolta sempre") | Information disclosure | Registrazione di conversazioni private | Wake word "Hi ESP" **sul dispositivo**: prima del wake word (o del tocco sullo schermo) nessun audio lascia il device; il gateway scarta l'audio fuori da `listen_start`/`listen_end`; tasto mute hardware; nessuna fotocamera |

> ⚠️ **Attenzione**: Moody **non** protegge da chi ha accesso fisico e amministrativo al server
> (root sul mini PC). Il server è la cassaforte: trattalo come tale (disco cifrato, password robuste,
> niente servizi superflui).

---

## 2. I controlli integrati, spiegati

### 2.1 Identità: mTLS con due CA separate

`scripts/setup.sh` crea con `python -m moody.pki init` **due radici indipendenti** in `deploy/pki/`:

| CA | Firma | Chi si fida |
|----|-------|-------------|
| `device-ca` | certificati client dei dispositivi (`CN=moody-xxxxxx`, solo `clientAuth`) | solo il **gateway** |
| `service-ca` | certificati di gateway, brain, wellbeing (e Keycloak in enterprise) | dispositivi (per autenticare il gateway) e servizi tra loro |

Conseguenza pratica: anche se qualcuno estrae il certificato di un dispositivo, **non può** usarlo per
parlare con il brain o con i tool. Il test `test_service_cert_cannot_connect_as_device` verifica anche
il caso inverso. Dettagli in [04-pki-identita.md](04-pki-identita.md).

Il gateway poi controlla, **prima dell'upgrade WebSocket** (risposta HTTP 403 altrimenti):

1. che il CN sia presente in `deploy/config/devices.yaml`;
2. che il dispositivo sia `enabled: true`;
3. che il seriale del certificato non sia in `revoked_serials`.

Il file viene ricaricato automaticamente a ogni connessione: revocare un dispositivo **non richiede riavvii**.

### 2.2 Il dispositivo: Secure Boot, Flash Encryption, NVS cifrata

Il firmware Moody ha due profili (vedi [05-setup-device.md](05-setup-device.md)):

| Profilo | Uso | Protezioni |
|---------|-----|------------|
| *dev* (`sdkconfig.defaults`) | sviluppo, banco | nessuna eFuse bruciata, NVS in chiaro: **non dare a nessuno un dispositivo dev** |
| *release* (`sdkconfig.defaults.release`) | uso reale | Secure Boot v2 (solo firmware firmato con la tua chiave), Flash Encryption in modalità *release*, NVS encryption, JTAG disabilitato via eFuse |

Inoltre:

- la **chiave privata nasce sul dispositivo** durante il provisioning USB (`firmware/tools/provision.py`):
  al PC arriva solo la CSR, mai la chiave;
- un **tocco prolungato di 10 secondi** sullo schermo esegue il factory reset (cancella Wi‑Fi,
  certificato e chiave): utile prima di regalare o smaltire il dispositivo.

> ⚠️ **Attenzione**: Secure Boot e Flash Encryption bruciano eFuse **in modo irreversibile**. Prova
> sempre prima il profilo dev e conserva la chiave di firma offline: se la perdi non potrai più
> aggiornare il firmware di quel dispositivo.

### 2.3 Privacy acustica

- Wake word "Hi ESP" (ESP-SR WakeNet) eseguito **localmente** sull'ESP32-S3; in alternativa *tap-to-talk*.
- Il gateway accetta frame audio **solo** tra `listen_start` e `listen_end`, con limite di 15 secondi
  (`MAX_UTTERANCE_SECONDS`); l'audio resta in RAM, viene passato allo STT e poi scartato
  (`server/moody/gateway/server.py`).
- Pulsante **mute hardware** dell'ESP32-S3-BOX-3: verifica sul tuo esemplare che l'indicatore rosso si accenda.
- Nessuna fotocamera nell'hardware consigliato; il dock sensori (radar di presenza) **non** va montato
  di default (vedi [02-montaggio.md](02-montaggio.md)).

### 2.4 Server: reti Docker isolate e runtime offline

`deploy/compose.yaml` definisce quattro reti:

| Rete | Membri | Internet |
|------|--------|----------|
| `lan` | gateway (porta 8443), ntfy (8088) | sì (è la rete bridge) |
| `core` | gateway, brain, qvac (trascrizione e voce) | **no** (`internal: true`) |
| `ai` | brain, qvac (LLM ed embedding) | **no** |
| `tools` | brain, wellbeing, ntfy | **no** |

Con `compose.classic.yaml` al posto di `qvac` ci sono `whisper` e `piper` su `core` e `ollama` su `ai`.

I modelli si scaricano **una volta** con `scripts/bootstrap-models.sh` (che aggiunge temporaneamente una
rete `egress` ai soli container dei modelli) e poi i container vengono ricreati senza accesso a Internet.
Il registry di QVAC è peer-to-peer (Hyperswarm): durante il bootstrap l'IP del server è visibile agli
altri peer. Se non lo vuoi, usa la config solo HTTPS (`QVAC_CONFIG=qvac.https.config.json`, vedi
[13-qvac.md](13-qvac.md)).

Il container `qvac` (runtime AI di Tether) è indurito come i servizi Moody:

- ascolta solo sulle reti interne e richiede una **chiave Bearer** (`deploy/secrets/qvac_api_key`,
  letta da file, mai sulla riga di comando);
- accetta solo l'header `Host: qvac` (`--allowed-host`), contro il DNS rebinding;
- espone solo l'API OpenAI-compatibile (`--no-default`: niente superficie nativa QVAC né route admin);
- la **cache KV**, costruita dalle conversazioni e che QVAC normalmente tiene su disco fino a 24 ore,
  è montata su **tmpfs**: vive solo in RAM e sparisce al riavvio.

Ogni servizio Moody gira con: utente non-root (`MOODY_UID`), filesystem `read_only`, `cap_drop: ALL`,
`no-new-privileges`, limiti di memoria e PID. I segreti sono **file** (`deploy/secrets/`, permessi 600)
montati come Docker secrets, mai variabili d'ambiente.

### 2.5 Agente e tool: deny by default

Il file `deploy/config/tool-policy.yaml` è la *whitelist* di ciò che il modello può fare:

- un tool **non elencato è invisibile** al modello;
- `confirm`: Moody chiede "Vuoi che proceda…? Rispondi sì oppure no" e agisce solo con un "sì" al turno successivo
  (es. `wellbeing.erase_my_data`, `homeassistant.HassClimateSetTemperature`);
- `deny_patterns` (`*lock*`, `*alarm*`, `*camera*`, `*door*`, `*garage*`, `*valve*`, `*oven*`, `*shell*`,
  `*exec*`) vincono su tutto, anche su voci `allow` scritte per errore;
- `internal_only` (`wellbeing.due_reminders`) è chiamabile solo dal sistema;
- **iniezione dell'identità**: il parametro `subject` viene tolto dallo schema che vede il modello e
  inserito dal brain in base al dispositivo autenticato. Il modello non può leggere o scrivere i dati di
  un'altra persona nemmeno se glielo si chiede esplicitamente;
- **rate limit**: `rate_limit_per_minute: 10` chiamate tool per persona.

Prima dell'LLM girano i guardrail deterministici (`server/moody/brain/guardrails.py`): frasi di crisi ed
emergenza ricevono una risposta fissa e revisionata (112, Telefono Amico), i tentativi di prompt injection
noti vengono bloccati, l'output viene ripulito (niente markdown, niente `<think>`, niente dosaggi di farmaci).

### 2.6 Log e dati

- `MOODY_LOG_TRANSCRIPTS=false` (default): le frasi pronunciate **non** finiscono nei log.
- Ogni record di log passa da `redact()` (`server/moody/common/pii.py`): email, IBAN, codice fiscale,
  carte, telefoni, IP vengono sostituiti da segnaposto. È una rete di sicurezza, non un'anonimizzazione.
- Diario dell'umore e promemoria: cifrati con Fernet, chiave in `deploy/secrets/data_key`; le righe sono
  indicizzate con `HMAC-SHA256(subject)`; `PRAGMA secure_delete=ON`; retention massima
  `MOODY_RETENTION_DAYS` (default 30) applicata ogni ora.

---

## 3. Cosa devi fare tu

### 3.1 Router: SSID e VLAN dedicati all'IoT

Configura sul router (OpenWrt, pfSense/OPNsense, UniFi, Fritz!Box con rete ospiti…):

1. **SSID dedicato** `casa-iot` con WPA3-Personal (o WPA2/WPA3 transitional se necessario), password lunga e diversa da quella principale.
2. **VLAN separata** (es. `192.168.20.0/24`) per l'SSID IoT, con **isolamento dei client** attivo.
3. Regole tra VLAN:

| Da | A | Porta | Azione |
|----|---|-------|--------|
| VLAN IoT | server Moody | TCP 8443 | consenti |
| VLAN IoT | server Moody | UDP 123 (se usi il server come NTP) | consenti |
| VLAN IoT | Internet | TCP 443 / UDP 123 | consenti solo se serve NTP pubblico; altrimenti nega |
| VLAN IoT | LAN principale | qualsiasi | **nega** |
| LAN principale | VLAN IoT | qualsiasi | nega (tranne la tua postazione di amministrazione) |

4. Prenota un **IP statico** (DHCP reservation) per il server e, se possibile, un nome DNS locale
   (`moody.lan`) che corrisponda al SAN del certificato del gateway.
5. Imposta `MOODY_GATEWAY_BIND` in `deploy/.env` all'IP del server sulla VLAN IoT invece di `0.0.0.0`.

> 💡 **Suggerimento**: il dispositivo ha bisogno di un orologio corretto per validare i certificati.
> Se blocchi Internet alla VLAN IoT, offri NTP dal router o dal server.

### 3.2 Firewall dell'host

Esempio con `ufw` su Debian/Ubuntu (adatta interfacce e subnet):

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp      # SSH solo dalla LAN principale
sudo ufw allow from 192.168.20.0/24 to any port 8443 proto tcp   # dispositivi Moody
sudo ufw allow from 192.168.1.0/24 to any port 8088 proto tcp    # app ntfy dei familiari (se esposto)
sudo ufw enable
```

> ⚠️ **Attenzione**: Docker scrive regole iptables proprie e le porte pubblicate **bypassano ufw**.
> Per questo il compose pubblica ntfy su `127.0.0.1` di default e conviene legare il gateway a un IP
> specifico. Per filtrare il traffico dei container usa la catena `DOCKER-USER`.

#### Catena DOCKER-USER: brain verso Home Assistant soltanto

Se abiliti l'integrazione Home Assistant con `compose.homeassistant.yaml`, il container `brain` entra
nella rete `lan` e ottiene una via d'uscita. Limitala al solo IP di Home Assistant:

```bash
# Subnet della rete docker "moody_lan" (verifica con: docker network inspect moody_lan)
LAN_NET=$(docker network inspect moody_lan -f '{{(index .IPAM.Config 0).Subnet}}')
BRAIN_IP=$(docker inspect moody-brain-1 -f '{{(index .NetworkSettings.Networks "moody_lan").IPAddress}}')
HA_IP=192.168.1.50

# Consenti solo brain -> Home Assistant:8123, nega il resto del traffico in uscita del brain
sudo iptables -I DOCKER-USER 1 -s "$BRAIN_IP" -d "$HA_IP" -p tcp --dport 8123 -j ACCEPT
sudo iptables -I DOCKER-USER 2 -s "$BRAIN_IP" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -I DOCKER-USER 3 -s "$BRAIN_IP" -j DROP
```

L'IP del container può cambiare a ogni ricreazione: per una regola stabile assegna un IP fisso al brain
sulla rete `lan` (sezione `ipam` del compose) oppure rigenera le regole con uno script all'avvio. Rendi le
regole persistenti con `iptables-persistent` o con un'unità systemd.

Configura poi in Home Assistant **solo** le entità esposte ad Assist che vuoi far controllare a Moody,
con un token *long-lived* dedicato salvato in `deploy/secrets/ha_token`.

### 3.3 Hardening del server

- Disco cifrato (LUKS) in installazione, BIOS/UEFI con password, Secure Boot dell'OS se supportato.
- SSH solo con chiavi (`PasswordAuthentication no`, `PermitRootLogin no`).
- `unattended-upgrades` per le patch di sicurezza del sistema operativo.
- Nessun altro servizio esposto sulla stessa macchina (niente port forwarding sul router verso Moody).
- Accesso da remoto, se proprio serve: VPN self-hosted (WireGuard) — **mai** esporre 8443 o 8088 su Internet.

Dettagli di installazione in [03-setup-ambiente.md](03-setup-ambiente.md).

---

## 4. Aggiornamenti

| Componente | Come | Frequenza consigliata |
|------------|------|-----------------------|
| Sistema operativo | `unattended-upgrades` | automatico (sicurezza) |
| Immagini container | aggiorna le versioni *pinnate* in `deploy/.env` (`QVAC_CLI_VERSION`, `NTFY_VERSION`, …), leggi i changelog, poi `docker compose build qvac && docker compose pull && docker compose up -d` | mensile, o subito per CVE critiche |
| Codice Moody | `git pull`, `docker compose build`, ripeti i test e il red teaming ([11-red-teaming.md](11-red-teaming.md)) | a ogni release |
| Modelli AI | modifica `deploy/config/qvac/*.json` e rilancia `scripts/bootstrap-models.sh` (unico momento con Internet); QVAC verifica lo SHA‑256 dei file | quando cambi modello: ripeti il red teaming |
| Firmware | build firmata con la chiave di Secure Boot, flash/OTA | a ogni release del firmware |

> ⚠️ **Attenzione**: le versioni delle immagini sono fissate di proposito. Non usare `latest`: un
> aggiornamento non verificato di un'immagine di terze parti è un rischio di supply chain.

---

## 5. Backup

| Cosa | Dove | Note |
|------|------|------|
| `deploy/pki/*/ca.key` | **offline** (chiavetta cifrata o password manager), due copie in luoghi diversi | Senza la device CA non puoi provisionare nuovi dispositivi. Imposta `MOODY_CA_PASSPHRASE` per cifrare le chiavi |
| Chiave di firma Secure Boot del firmware | offline, come sopra | Senza di essa niente aggiornamenti firmware sui dispositivi release |
| `deploy/secrets/data_key` | offline, **separata** dal backup dei dati | Chi ha DB + chiave può leggere il diario dell'umore |
| `deploy/data/wellbeing/` | backup cifrato (es. `restic`, `borg`) | Contiene solo dati cifrati; rispetta comunque la retention |
| `deploy/.env`, `deploy/config/` | backup cifrato | Configurazione |

Dopo aver salvato offline la `device-ca/ca.key`, valuta di **rimuoverla dal server** e di ricaricarla solo
quando devi provisionare un nuovo dispositivo.

---

## 6. Dispositivo perso o rubato

1. Trova il seriale del certificato in `deploy/pki/issued.csv` (colonne: seriale, CN, scadenza).
2. Revocalo:

   ```bash
   .venv/bin/python -m moody.pki revoke <SERIALE> --devices-file deploy/config/devices.yaml
   ```

3. Per sicurezza disabilita anche la voce del dispositivo in `deploy/config/devices.yaml`
   (`enabled: false`). Il gateway ricarica il file alla connessione successiva: non serve riavviare.
4. Se il dispositivo era in profilo **dev** (NVS non cifrata), considera compromessa la password
   dell'SSID IoT e cambiala.
5. Se vuoi cancellare anche i dati della persona: con un altro dispositivo associato allo stesso
   pseudonimo chiedi "cancella i miei dati" (con conferma), oppure vedi la procedura in
   [08-sicurezza-enterprise.md](08-sicurezza-enterprise.md#4-ciclo-di-vita-del-dispositivo).
6. Provisiona il dispositivo sostitutivo con un **nuovo** certificato ([05-setup-device.md](05-setup-device.md)).

---

## 7. Checklist finale

- [ ] Dispositivi in profilo **release** (Secure Boot v2, Flash Encryption, NVS encryption, JTAG off)
- [ ] Chiave di firma firmware e chiavi CA salvate **offline**, con passphrase
- [ ] SSID/VLAN IoT dedicati con isolamento dei client e regole inter-VLAN
- [ ] `MOODY_GATEWAY_BIND` legato all'IP della VLAN IoT; ntfy non esposto oltre il necessario
- [ ] Firewall host attivo; regole `DOCKER-USER` se usi Home Assistant
- [ ] Nessun port forwarding verso Moody; accesso remoto solo via VPN
- [ ] Disco del server cifrato, SSH solo con chiavi, aggiornamenti automatici
- [ ] `MOODY_LOG_TRANSCRIPTS=false`
- [ ] `deploy/secrets/qvac_api_key` presente (permessi 600) e `qvac` raggiungibile solo dalle reti interne
- [ ] `tool-policy.yaml` rivista: solo i tool necessari, nessuna serratura/allarme/telecamera
- [ ] In Home Assistant esposte ad Assist solo le entità desiderate
- [ ] Backup cifrati, chiave dati conservata separatamente
- [ ] Red teaming eseguito dopo ogni cambio di modello ([11-red-teaming.md](11-red-teaming.md))
- [ ] Le persone di casa sanno cosa fa Moody, come usare il mute e come chiedere la cancellazione dei dati

---

**Prossimo passo →** [08 · Sicurezza in ambito enterprise (senior living)](08-sicurezza-enterprise.md)
