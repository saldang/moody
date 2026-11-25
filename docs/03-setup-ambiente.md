# 03 · Setup dell'ambiente server

Come preparare il server che ospita Moody, passo dopo passo: sistema operativo cifrato e
aggiornato, firewall, Docker, configurazione con `setup.sh` (PKI privata, segreti, `.env`),
download dei modelli di **[QVAC](13-qvac.md)** (il runtime AI di Tether) **una volta sola** e
funzionamento offline, notifiche ntfy e, se vuoi,
integrazione con Home Assistant. Alla fine il server è pronto per i dispositivi
([05-setup-device.md](05-setup-device.md)) e per l'avvio ([06-running.md](06-running.md)).

## Prerequisiti

- Hardware scelto in [01-acquisto.md](01-acquisto.md), montato come in [02-montaggio.md](02-montaggio.md)
  (TPM e Secure Boot abilitati nel BIOS).
- Una chiavetta USB da almeno 4 GB per l'installer del sistema operativo.
- Una coppia di chiavi SSH sul tuo PC (`ssh-keygen -t ed25519`).
- Accesso al router per DHCP, DNS e VLAN.

---

## 1. Sistema operativo

| Scelta | Quando |
|---|---|
| **Debian 13 "trixie"** (consigliato) | Sistema stabile e minimale, nessun componente aggiuntivo del vendor |
| **Ubuntu Server 24.04 LTS** | Se preferisci Ubuntu o ti serve un supporto commerciale. Comodo con i driver NVIDIA |
| macOS (Mac mini) | Solo per l'opzione D, vedi [sezione dedicata](#mac-mini) |

Durante l'installazione:

1. Scegli **partizionamento guidato con LVM cifrato (LUKS)**. Usa una passphrase lunga e
   conservala in un password manager e su carta in cassaforte.
2. Installa solo **SSH server** e le utility standard. Niente ambiente desktop.
3. Crea un utente amministratore non root (es. `moody`).

> ⚠️ **Attenzione:** la cifratura del disco protegge chiavi della CA, segreti e diario dell'umore
> in caso di furto del server. In una struttura **non è opzionale**.

### 1.1 (Opzionale) Sblocco automatico con TPM2

Un server con disco cifrato chiede la passphrase a ogni riavvio. Per farlo ripartire da solo dopo
un blackout, puoi legare lo sblocco al TPM e allo stato di Secure Boot:

```bash
sudo apt install -y systemd-cryptsetup tpm2-tools
lsblk -o NAME,FSTYPE | grep crypto_LUKS          # individua la partizione, es. /dev/nvme0n1p3
sudo systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=7 /dev/nvme0n1p3
# in /etc/crypttab aggiungi l'opzione tpm2-device=auto alla riga del volume, poi:
sudo update-initramfs -u
```

Il PCR 7 lega lo sblocco allo stato di Secure Boot: se qualcuno lo disattiva o avvia un sistema
diverso, il disco resta cifrato e serve la passphrase. **Conserva sempre la passphrase di recupero.**

## 2. Hardening di base

### 2.1 SSH solo con chiavi

```bash
# dal tuo PC
ssh-copy-id moody@<ip-server>
# sul server
sudo tee /etc/ssh/sshd_config.d/10-moody.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers moody
EOF
sudo systemctl restart ssh
```

### 2.2 Aggiornamenti di sicurezza automatici

```bash
sudo apt update && sudo apt install -y unattended-upgrades apt-listchanges
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 2.3 Firewall

Indirizzi d'esempio, adattali alla tua rete:

| Rete | Subnet d'esempio | Porte consentite verso il server |
|---|---|---|
| Admin / LAN principale | `192.168.1.0/24` | 22 (SSH), 8088 (ntfy) |
| VLAN IoT (dispositivi Moody) | `192.168.20.0/24` | **solo 8443** (gateway) |
| VPN (WireGuard, opzionale) | `10.8.0.0/24` | 8088 (ntfy dal telefono fuori casa) |

Firewall dell'host per i servizi non Docker (SSH):

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp
sudo ufw enable
```

> ⚠️ **Attenzione: Docker scavalca ufw.** Le porte pubblicate dai container (8443, 8088) passano
> dalla catena `DOCKER` di iptables e **non** sono filtrate dalle regole `ufw`. Per limitarle hai
> due strumenti, da usare insieme:
>
> 1. **Bind sull'interfaccia giusta** in `deploy/.env`: `MOODY_GATEWAY_BIND=<ip del server sulla
>    VLAN IoT>` e `MOODY_NTFY_BIND=<ip LAN o VPN>` (default `127.0.0.1`).
> 2. **Regole nella catena `DOCKER-USER`**, valutata prima di quelle di Docker:
>
> ```bash
> # 8443 solo dalla VLAN IoT, 8088 solo da LAN admin e VPN
> sudo iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 8443 ! -s 192.168.20.0/24 -j DROP
> sudo iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 8088 -s 192.168.20.0/24 -j DROP
> sudo apt install -y iptables-persistent && sudo netfilter-persistent save
> ```

Altre regole (egress del container `brain` verso Home Assistant e simili) sono in
[07-sicurezza-home.md](07-sicurezza-home.md).

## 3. Docker Engine e Compose (repository ufficiale)

```bash
sudo apt install -y ca-certificates curl git python3 python3-venv
sudo install -m 0755 -d /etc/apt/keyrings
. /etc/os-release
sudo curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/$ID $VERSION_CODENAME stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker moody     # poi esci e rientra
docker compose version
```

> ⚠️ **Attenzione:** essere nel gruppo `docker` equivale ad avere i privilegi di root. Aggiungi
> solo l'utente amministratore.

### 3.1 (Opzionale) GPU NVIDIA

1. Installa il driver NVIDIA della distribuzione (`nvidia-driver` su Debian, con il repository
   `non-free`, oppure `ubuntu-drivers install` su Ubuntu) e riavvia. Verifica con `nvidia-smi`.
2. Installa **NVIDIA Container Toolkit** seguendo la guida ufficiale NVIDIA, poi:
   ```bash
   sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
   ```
3. Da qui in poi aggiungi `-f compose.gpu.yaml` ai comandi `docker compose` ed esporta
   `MOODY_GPU=1` prima di lanciare `bootstrap-models.sh`.

> ⚠️ **Sperimentale:** su Linux QVAC usa la GPU tramite **Vulkan**. `compose.gpu.yaml` riserva la GPU
> al servizio `qvac` ed espone l'ICD Vulkan di NVIDIA (`NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility`).
> Controlla nei log di `qvac` quale backend viene scelto: se Vulkan non è disponibile QVAC torna alla
> CPU. Con lo stack classico (`compose.classic.yaml`) aggiungi lo stesso blocco `deploy:` al servizio
> `ollama`, che usa CUDA.

## 4. Clonare il repository

```bash
cd ~
git clone https://github.com/saldang/moody.git
cd moody
```

## 5. DNS: il nome `moody.lan`

I dispositivi verificano il certificato del gateway, che è valido per il nome DNS e l'IP che passi a
`setup.sh`. Prima di tutto:

1. Nel router assegna un **IP statico** (DHCP reservation) al server, es. `192.168.20.5` sulla VLAN
   IoT.
2. Crea un record DNS `moody.lan → 192.168.20.5`: dal router (OpenWrt: *Network → DHCP and DNS →
   Hostnames*), da Pi-hole/AdGuard Home (*Local DNS records*) oppure, solo per i test, in
   `/etc/hosts` del tuo PC.

## 6. Configurazione iniziale con `setup.sh`

```bash
./scripts/setup.sh --hostname moody.lan --ip 192.168.20.5
# struttura senior living (Keycloak/OIDC):
./scripts/setup.sh --hostname moody.lan --ip 192.168.20.5 --enterprise
```

Lo script è idempotente (puoi rilanciarlo) e crea:

| Cosa | Dove | Note |
|---|---|---|
| Virtualenv con gli strumenti PKI e di provisioning | `.venv/` | Installa `server[pki]` (cryptography, pyserial) |
| Configurazione | `deploy/.env` | Copiato da `.env.example`, con il tuo UID/GID e un topic ntfy casuale `moody-help-…` |
| Chiave dati (Fernet) del diario e dei promemoria | `deploy/secrets/data_key` | Permessi `600`. **Senza questa chiave il database non è leggibile:** fanne un backup separato |
| Chiave API tra brain/gateway e QVAC | `deploy/secrets/qvac_api_key` | Casuale, permessi `600`; QVAC rifiuta le richieste senza questa chiave |
| Segnaposto per i token ntfy e Home Assistant | `deploy/secrets/ntfy_token`, `ha_token` | Vengono riempiti più avanti |
| Cartelle dei dati | `deploy/data/brain`, `deploy/data/wellbeing`, `deploy/data/qvac-models` | La terza contiene i modelli scaricati da QVAC (~4 GB) |
| Due CA indipendenti (ECDSA P-256, 10 anni) | `deploy/pki/device-ca/`, `deploy/pki/service-ca/` | Un certificato dispositivo non può mai autenticarsi come servizio. Vedi [04-pki-identita.md](04-pki-identita.md) |
| Certificati dei servizi (`gateway`, `brain`, `wellbeing`) | `deploy/pki/services/<nome>/tls.{pem,key}` | Il gateway ha come SAN `moody.lan` e l'IP |
| Registro dispositivi vuoto | `deploy/config/devices.yaml` | Ricaricato a caldo dal gateway |
| *(con `--enterprise`)* password di Keycloak e DB, client secret del gateway, certificato `keycloak` | `deploy/.env`, `deploy/secrets/gateway_client_secret` | |

> ⚠️ **Attenzione:** `deploy/pki/*/ca.key` sono le chiavi più preziose del sistema. Fai subito un
> **backup offline** (chiavetta cifrata in cassaforte). Valuta poi di rimuovere
> `device-ca/ca.key` dal server e di firmare i nuovi dispositivi solo da una macchina offline.
> Puoi anche cifrare le chiavi della CA con `MOODY_CA_PASSPHRASE`. Tutto è spiegato in
> [04-pki-identita.md](04-pki-identita.md).

Rivedi poi `deploy/.env`. Le voci principali:

| Variabile | Default | Cosa cambia |
|---|---|---|
| `QVAC_CONFIG` | `qvac.config.json` | Quali modelli carica QVAC (file in `deploy/config/qvac/`). `qvac.https.config.json` = solo Hugging Face, senza TTS (vedi sotto) |
| `QVAC_MEM_LIMIT` | `12g` | Memoria massima del container `qvac` |
| `MOODY_LLM_MODEL` | `moody-llm` | Alias del modello nella config di QVAC (Qwen3‑4B di default). Per cambiare modello modifica la config, non l'alias |
| `MOODY_LLM_TEMPERATURE` | `0.2` | Bassa = chiamate agli strumenti più affidabili |
| `MOODY_EMBED_MODEL` | `moody-embed` | Alias dell'embedding (bge‑m3). `none` disattiva la knowledge base |
| `MOODY_RAG_MIN_SCORE` | `0.55` | Soglia di pertinenza dei documenti, tarata su bge‑m3 |
| `MOODY_STT_BACKEND` / `MOODY_TTS_BACKEND` | `openai` / `openai` | `openai` = QVAC; `wyoming` = faster‑whisper / Piper |
| `MOODY_TTS_VOICE` | `F1` | Voce di Supertonic 3 (F1–F5, M1–M5); con `wyoming` è il nome della voce Piper |
| `MOODY_GUARD_MODEL` | *(vuoto)* | Es. `granite3-guardian:2b` per un secondo filtro di sicurezza: richiede un endpoint Ollama (`MOODY_GUARD_URL`) |
| `MOODY_RETENTION_DAYS` | `30` | Conservazione massima del diario dell'umore e dei promemoria |
| `MOODY_LOG_TRANSCRIPTS` | `false` | Tienilo `false` in produzione |
| `MOODY_ESCALATION` | `ask` | `auto` invia la notifica di aiuto senza chiedere conferma (default in enterprise) |
| `MOODY_GATEWAY_BIND` / `MOODY_NTFY_BIND` | `0.0.0.0` / `127.0.0.1` | Interfacce su cui ascoltano le porte pubblicate |

## 7. Download dei modelli (una sola volta) e poi offline

A runtime il container `qvac` sta solo sulle reti Docker `internal: true` (`core` e `ai`),
**senza accesso a Internet**. Per scaricare i modelli serve un passaggio dedicato:

```bash
./scripts/bootstrap-models.sh          # con GPU: MOODY_GPU=1 ./scripts/bootstrap-models.sh
```

Lo script:

1. costruisce l'immagine `moody/qvac` (Node.js + `@qvac/cli` 0.20.0) e genera al volo un override
   che aggiunge temporaneamente una rete `egress` ai soli servizi di modelli dello stack attivo;
2. avvia `qvac`, che scarica e carica i modelli dichiarati in `deploy/config/qvac/$QVAC_CONFIG`:

   | Alias | Modello | Licenza | Dimensione | Sorgente |
   |---|---|---|---|---|
   | `moody-llm` | Qwen3‑4B (`QWEN3_4B_INST_Q4_K_M`) | Apache‑2.0 | ~2,5 GB | registry QVAC |
   | `moody-embed` | bge‑m3 Q8_0 (GGUF `ggml-org`) | MIT | ~635 MB | Hugging Face |
   | `moody-stt` | TranscribePsy 250M (Tether) | Apache‑2.0 | ~305 MB | registry QVAC |
   | `moody-tts` | Supertonic 3, italiano, voce F1 | **OpenRAIL** | ~126 MB | registry QVAC (solo P2P) |

3. attende che `qvac` risulti `healthy` (tutti i modelli caricati; la prima volta può richiedere
   parecchi minuti);
4. ricrea i container **senza** la rete `egress`.

I modelli restano in `deploy/data/qvac-models`. Per cambiarli modifica il file di config di QVAC
(vedi [13 · QVAC](13-qvac.md)) e rilancia lo script.

> ⚠️ **Registry peer-to-peer:** il registry di QVAC distribuisce i modelli via **Hyperswarm**, che
> richiede **UDP in uscita** durante il bootstrap e rende visibile l'IP del server agli altri peer.
> Se la rete lo blocca (tipico in azienda) o preferisci evitarlo, usa la variante solo HTTPS
> (Hugging Face) con Piper per la voce:
>
> ```bash
> # in deploy/.env: QVAC_CONFIG=qvac.https.config.json
> MOODY_COMPOSE_FILES="compose.piper.yaml" ./scripts/bootstrap-models.sh
> cd deploy && docker compose -f compose.yaml -f compose.piper.yaml up -d
> ```
>
> Supertonic 3 è disponibile solo nel registry QVAC: nella variante HTTPS la voce è Piper
> (GPL‑3.0, in un container separato). In alternativa puoi pre‑popolare `deploy/data/qvac-models`
> da una macchina con accesso.

**Stack classico** (Ollama + faster‑whisper + Piper, l'alternativa a QVAC):

```bash
MOODY_COMPOSE_FILES="compose.classic.yaml" ./scripts/bootstrap-models.sh
cd deploy && docker compose -f compose.yaml -f compose.classic.yaml up -d && docker compose stop qvac
```

Con lo stack classico i modelli si scelgono con `OLLAMA_LLM_MODEL` (default `qwen3:8b`),
`OLLAMA_EMBED_MODEL` (`bge-m3`), `WHISPER_MODEL` (`small-int8`) e `PIPER_VOICE`
(`it_IT-paola-medium`, controlla la licenza nella MODEL_CARD della voce) e restano nei volumi
Docker `ollama`, `whisper` e `piper`.

## 8. Notifiche di aiuto (ntfy)

Quando una persona chiede aiuto, il tool `request_help` invia una notifica push al contatto di
fiducia (casa) o allo staff (struttura) tramite **ntfy self-hosted**. Il server ntfy nega tutto a
chi non ha credenziali.

```bash
./scripts/ntfy-setup.sh figlia          # nome dell'utente che riceverà le notifiche
```

Lo script crea l'utente `moody-publisher` (sola scrittura sul topic) e salva il suo token in
`deploy/secrets/ntfy_token`. Poi crea l'utente destinatario (ti chiede la password) con sola
lettura. Sul telefono installa l'app **ntfy**, aggiungi il server `http://moody.lan:8088` (oppure
l'IP LAN o VPN, ricordando `MOODY_NTFY_BIND`), accedi con l'utente creato e iscriviti al topic
indicato dallo script.

> 💡 **Suggerimento:** fuori casa, raggiungi ntfy attraverso una VPN (WireGuard) e **non** esporlo
> su Internet. Non impostare `upstream-base-url` in `deploy/config/ntfy/server.yml`: invierebbe i
> metadati delle notifiche a ntfy.sh.

## 9. (Opzionale) Home Assistant via MCP

Moody controlla la casa solo tramite un server MCP, con policy *deny by default*
(`deploy/config/tool-policy.yaml`). Non fa mai scansioni della rete.

1. In Home Assistant aggiungi l'integrazione **"Model Context Protocol Server"**
   (*Impostazioni → Dispositivi e servizi → Aggiungi integrazione*).
2. In *Impostazioni → Assistenti vocali → Esponi* esponi ad Assist **solo** le entità che vuoi far
   controllare a Moody (luci, termostato). Serrature, allarmi e telecamere vanno lasciati fuori.
   Sono comunque bloccati da `deny_patterns`.
3. Crea un **token di accesso a lunga durata** dal tuo profilo HA (meglio se di un utente HA
   dedicato e non amministratore) e salvalo:
   ```bash
   umask 077; printf '%s' 'IL_TUO_TOKEN' > deploy/secrets/ha_token
   ```
4. In `deploy/.env`: `MOODY_HA_MCP_URL=http://homeassistant.lan:8123/api/mcp`
5. Avvia con l'override che dà al `brain` una rotta verso la LAN:
   ```bash
   cd deploy && docker compose -f compose.yaml -f compose.homeassistant.yaml up -d
   ```
6. Limita l'egress del container `brain` al solo IP di Home Assistant con `DOCKER-USER`
   ([07-sicurezza-home.md](07-sicurezza-home.md)).

## 10. Varianti

### Mac mini

Docker Desktop su macOS non accede alla GPU Apple. La soluzione pratica è eseguire **QVAC nativo**
(supporta macOS arm64) e lasciare in Docker il resto:

1. Installa Node.js 24 e copia la config adattando la cache:
   ```bash
   mkdir -p ~/moody-qvac/models
   sed 's#"/models"#"'"$HOME"'/moody-qvac/models"#' deploy/config/qvac/qvac.config.json > ~/moody-qvac/qvac.config.json
   npx @qvac/cli@0.20.0 serve --openai --no-default -c ~/moody-qvac/qvac.config.json \
     --host 127.0.0.1 --port 11435 --api-key-file deploy/secrets/qvac_api_key \
     --allowed-host host.docker.internal
   ```
2. In `deploy/.env` imposta `MOODY_LLM_URL=http://host.docker.internal:11435/v1`.
3. Crea `deploy/compose.override.yaml` per escludere il servizio `qvac` e dare a `brain` e
   `gateway` accesso all'host:
   ```yaml
   services:
     brain:
       depends_on: !override [wellbeing]    # richiede Docker Compose >= 2.24.4
       networks: [core, ai, tools, lan]
     gateway:
       depends_on: !override [brain]
       environment:
         MOODY_SPEECH_URL: http://host.docker.internal:11435/v1
     qvac:
       profiles: [disabled]
   ```

> ⚠️ **Compromesso:** il `brain` esce dalle reti `internal` e QVAC gira sull'host, fuori dal
> container read-only e con la cache KV su disco (`~/.qvac/kv-cache`, conservata fino a 24 ore).
> Lascialo in ascolto solo su `127.0.0.1`, attiva il firewall di macOS e, se possibile, FileVault.
> La superficie d'attacco è più ampia rispetto alla configurazione Linux: per una struttura usa Linux.

### Enterprise: vLLM per il solo LLM

QVAC serve tutti i modelli da un unico processo. Con le GPU da data center e molti turni
contemporanei puoi spostare il **solo LLM** su un server OpenAI-compatibile come **vLLM**
(Apache-2.0), lasciando a QVAC trascrizione, voce ed embedding. vLLM non è
incluso nel compose: aggiungilo in un override sulla rete `ai` (immagine `vllm/vllm-openai` con
versione fissata, modello con licenza Apache-2.0) e imposta:

```bash
MOODY_LLM_BACKEND=openai
MOODY_LLM_URL=http://vllm:8000/v1
MOODY_LLM_MODEL=<nome del modello servito da vLLM>
```

Embedding della knowledge base: per default seguono `MOODY_LLM_URL`, quindi andrebbero a vLLM.
Per lasciarli a QVAC indicali esplicitamente (il brain usa la stessa chiave
`deploy/secrets/qvac_api_key`; `qvac` è già sulla rete `ai`):

```bash
MOODY_EMBED_BACKEND=openai
MOODY_EMBED_URL=http://qvac:11435/v1
MOODY_EMBED_MODEL=moody-embed
```

Se cambi modello di embedding la knowledge base viene reindicizzata automaticamente al riavvio
del brain.

> ℹ️ Il guard model opzionale (`MOODY_GUARD_MODEL`, Granite Guardian) parla l'API di **Ollama**, non
> quella di QVAC: se lo vuoi, aggiungi un piccolo servizio Ollama sulla rete `ai` e punta
> `MOODY_GUARD_URL` a quello.

---

Prossimo passo → [04 · PKI e identità](04-pki-identita.md), poi [05 · Setup del dispositivo](05-setup-device.md)
