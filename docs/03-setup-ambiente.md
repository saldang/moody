# 03 · Setup dell'ambiente server

Come preparare il server che ospita Moody, passo dopo passo: sistema operativo cifrato e
aggiornato, firewall, Docker, configurazione con `setup.sh` (PKI privata, segreti, `.env`),
download dei modelli **una volta sola** e funzionamento offline, notifiche ntfy e, se vuoi,
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
| Segnaposto per i token ntfy e Home Assistant | `deploy/secrets/ntfy_token`, `ha_token` | Vengono riempiti più avanti |
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
| `MOODY_LLM_MODEL` | `qwen3:8b` | Con un hardware modesto usa `qwen3:4b` |
| `WHISPER_MODEL` | `small-int8` | `tiny-int8`/`base-int8` su CPU deboli, `medium-int8` con GPU |
| `PIPER_VOICE` | `it_IT-paola-medium` | Controlla la licenza nella MODEL_CARD della voce ([10-licenze.md](10-licenze.md)) |
| `MOODY_EMBED_MODEL` | `bge-m3` | Lascialo vuoto per disattivare la knowledge base |
| `MOODY_GUARD_MODEL` | *(vuoto)* | Es. `granite3-guardian:2b` per un secondo filtro di sicurezza |
| `MOODY_RETENTION_DAYS` | `30` | Conservazione massima del diario dell'umore e dei promemoria |
| `MOODY_LOG_TRANSCRIPTS` | `false` | Tienilo `false` in produzione |
| `MOODY_ESCALATION` | `ask` | `auto` invia la notifica di aiuto senza chiedere conferma (default in enterprise) |
| `MOODY_GATEWAY_BIND` / `MOODY_NTFY_BIND` | `0.0.0.0` / `127.0.0.1` | Interfacce su cui ascoltano le porte pubblicate |

## 7. Download dei modelli (una sola volta) e poi offline

A runtime i container di Ollama, Whisper e Piper stanno solo su reti Docker `internal: true`,
**senza accesso a Internet**. Per scaricare i modelli serve un passaggio dedicato:

```bash
./scripts/bootstrap-models.sh          # con GPU: MOODY_GPU=1 ./scripts/bootstrap-models.sh
```

Lo script:

1. avvia `ollama`, `whisper` e `piper` con l'override `compose.bootstrap.yaml`, che aggiunge
   temporaneamente una rete `egress`;
2. esegue `ollama pull` di `MOODY_LLM_MODEL`, `MOODY_EMBED_MODEL` ed eventualmente di
   `MOODY_GUARD_MODEL`;
3. attende che Whisper e Piper scarichino il modello STT e la voce;
4. ricrea i tre container **senza** la rete `egress`.

I modelli restano nei volumi Docker `ollama`, `whisper` e `piper`. Per cambiare modello o voce,
aggiorna `.env` e rilancia lo script.

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

Docker Desktop su macOS non accede alla GPU Apple. La soluzione pratica è eseguire **Ollama
nativo** e lasciare in Docker il resto:

1. Installa Ollama per macOS, poi scarica i modelli: `ollama pull qwen3:8b && ollama pull bge-m3`.
2. In `deploy/.env` imposta `MOODY_LLM_URL=http://host.docker.internal:11434`.
3. Crea `deploy/compose.override.yaml` per escludere il servizio `ollama` e dare al `brain`
   accesso all'host:
   ```yaml
   services:
     brain:
       depends_on: !override [wellbeing]    # richiede Docker Compose >= 2.24.4
       networks: [core, ai, tools, lan]
     ollama:
       profiles: [disabled]
   ```

> ⚠️ **Compromesso:** il `brain` esce dalle reti `internal` e Ollama ascolta sull'host. Configura
> Ollama perché ascolti solo su `127.0.0.1`/interfaccia Docker e attiva il firewall di macOS. La
> superficie d'attacco è più ampia rispetto alla configurazione Linux: per una struttura usa Linux.

### Enterprise: vLLM al posto di Ollama

Con le GPU da data center conviene un server OpenAI-compatibile come **vLLM** (Apache-2.0). Non è
incluso nel compose: aggiungilo in un override sulla rete `ai` (immagine `vllm/vllm-openai` con
versione fissata, modello con licenza Apache-2.0) e imposta:

```bash
MOODY_LLM_BACKEND=openai
MOODY_LLM_URL=http://vllm:8000/v1
MOODY_LLM_MODEL=<nome del modello servito da vLLM>
```

Embedding della knowledge base: per default seguono `MOODY_LLM_BACKEND`/`MOODY_LLM_URL`, quindi con
`openai` vengono chiesti a `/v1/embeddings`. vLLM serve un modello per istanza: avvia una seconda
istanza per `bge-m3` (MIT) e indicala esplicitamente:

```bash
MOODY_EMBED_BACKEND=openai
MOODY_EMBED_URL=http://vllm-embed:8000/v1
MOODY_EMBED_MODEL=BAAI/bge-m3
```

> ℹ️ Il guard model opzionale (`MOODY_GUARD_MODEL`, Granite Guardian) parla l'API di **Ollama**: se
> lo vuoi anche con vLLM, mantieni un piccolo servizio Ollama e punta `MOODY_GUARD_URL` a quello.

---

Prossimo passo → [04 · PKI e identità](04-pki-identita.md), poi [05 · Setup del dispositivo](05-setup-device.md)
