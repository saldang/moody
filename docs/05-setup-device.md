# 05 · Setup del dispositivo (firmware, provisioning, hardening)

Questo documento porta una ESP32‑S3‑BOX‑3 nuova fino a un dispositivo Moody funzionante e messo in
sicurezza: compilazione del firmware, flash in modalità sviluppo, **provisioning** (la chiave privata
nasce sul dispositivo e non lo lascia mai), verifica, poi **hardening di produzione** con
**Secure Boot V2 + Flash Encryption (release) + NVS encryption** e aggiornamenti **OTA firmati**.

## Prerequisiti

- BOX‑3 montata ([02 · Montaggio](02-montaggio.md)) e cavo USB‑C **dati**.
- Server avviato e PKI creata ([03](03-setup-ambiente.md), [04](04-pki-identita.md)).
- Docker sul PC di build (oppure ESP‑IDF v5.5 installato localmente).
- Su Linux, permesso di accesso alla seriale: `sudo usermod -aG dialout $USER` (poi logout/login).
- Una rete Wi‑Fi a 2,4 GHz per i dispositivi (meglio la SSID/VLAN IoT, vedi [07](07-sicurezza-home.md)).

> ⚠️ **Attenzione**: la Parte B (release) **brucia eFuse in modo irreversibile**. Fai prima tutta la
> Parte A, verifica che funzioni, e prova la Parte B su **un solo** dispositivo.

---

## Parte A · Sviluppo

### A1. Compilare il firmware

Il firmware vive in `firmware/` (C, ESP‑IDF v5.5). Le dipendenze sono fissate in
`firmware/main/idf_component.yml` e `firmware/dependencies.lock`.

```bash
cd firmware
docker run --rm -v "$PWD":/project -w /project espressif/idf:v5.5.6 \
  idf.py set-target esp32s3 build
```

La prima build scarica i componenti dal registry Espressif (BSP BOX‑3, ESP‑SR, websocket client,
LVGL) e dura qualche minuto. Il risultato è in `firmware/build/` (`moody_edge.bin` ≈ 2,1 MB +
`srmodels.bin` con il modello della wake word).

### A2. Flash (sviluppo)

Collega la BOX‑3 via USB‑C. Su Linux la porta è di solito `/dev/ttyACM0`.

```bash
# Linux: passa la porta seriale al container
docker run --rm --device=/dev/ttyACM0 -v "$PWD":/project -w /project espressif/idf:v5.5.6 \
  idf.py -p /dev/ttyACM0 flash
```

Su macOS/Windows Docker non vede le porte USB: installa esptool sul PC (`pip install esptool`) e
flasha i binari prodotti dalla build:

```bash
cd firmware/build
python -m esptool --chip esp32s3 -p /dev/cu.usbmodem1101 -b 460800 write_flash "@flash_args"
```

Al riavvio lo schermo mostra **"Configurazione"** e l'ID del dispositivo (es. `moody-a1b2c3`):
non è ancora configurato.

### A3. Provisioning

Il provisioning avviene via USB con `firmware/tools/provision.py`, dal **server** (o dal PC che
custodisce la `device-ca`):

```bash
.venv/bin/python firmware/tools/provision.py \
  --port /dev/ttyACM0 \
  --ssid Moody-IoT \
  --gateway wss://moody.lan:8443/v1/ws \
  --subject res-001
# chiede la password Wi-Fi senza mostrarla (oppure: MOODY_WIFI_PASSWORD=... nell'ambiente)
```

Cosa succede, passo per passo:

| # | Host | Dispositivo |
|---|---|---|
| 1 | `ID` | risponde con ID e versione firmware |
| 2 | `GENKEY` | genera una chiave **ECDSA P‑256** con il TRNG hardware, la salva in NVS, restituisce solo la **CSR** |
| 3 | firma la CSR con la `device-ca` (controlla che la CN coincida con l'ID) | — |
| 4 | invia certificato, `service-ca`, SSID, password, URL del gateway (e NTP, se indicato) | salva tutto in NVS (cifrata in release) |
| 5 | `COMMIT` | verifica che non manchi nulla e si riavvia |
| 6 | con `--subject`, aggiunge il dispositivo a `deploy/config/devices.yaml` | — |

> ℹ️ Il provisioning è possibile **solo** su un dispositivo non configurato (nuovo o dopo factory
> reset): un dispositivo in uso non può essere "dirottato" verso un altro gateway via USB.

Opzioni utili:

- `--ntp 192.168.20.1` se la rete IoT non può raggiungere `pool.ntp.org` (vedi Troubleshooting).
- `--days 180` per certificati più brevi.
- Senza `--subject`, lo script stampa il blocco da incollare in `devices.yaml`. Il `subject` è uno
  **pseudonimo** (`res-001`): mai nomi, stanze o altri dati personali.

### A4. Verifica

1. La BOX‑3 si riavvia: "Connessione" → "Sincronizzo l'ora..." → **"Moody — Di' "Hi ESP" oppure
   tocca lo schermo"**.
2. Sul server: `docker compose -f deploy/compose.yaml logs gateway | grep device_connected`.
3. Di' **"Hi ESP"** (pronuncia inglese, *"hai i‑es‑pi"*) oppure **tocca lo schermo**: compare il
   **bordo rosso** (microfono attivo) e la scritta "Ti ascolto". Prova: *"Che attività ci sono
   domani?"*.

| Gesto | Effetto |
|---|---|
| "Hi ESP" | apre l'ascolto (max 12 s; si chiude dopo 0,8 s di silenzio) |
| Tocco breve da fermo | apre l'ascolto (utile per chi non riesce a usare la wake word) |
| Tocco mentre ascolta | chiude l'ascolto e invia |
| Tocco mentre parla/pensa | interrompe la risposta |
| Pressione prolungata **10 s** | **factory reset**: cancella Wi‑Fi, certificato e chiave, torna in "Configurazione" |
| Tasto Mute (fisico) | disattiva i microfoni via hardware |

---

## Parte B · Release (produzione)

Obiettivo: solo firmware **firmato da te** può avviarsi, la flash è **illeggibile** fuori dal chip,
le credenziali in NVS sono **cifrate**, JTAG e la lettura via USB sono **disabilitati**.

### B1. Chiave di firma Secure Boot

```bash
cd firmware
docker run --rm -v "$PWD":/project -w /project espressif/idf:v5.5.6 \
  espsecure.py generate_signing_key --version 2 --scheme rsa3072 secure_boot_signing_key.pem
```

> ⚠️ **Attenzione**: questa chiave è la radice di fiducia di tutta la flotta.
> - **Persa** → non potrai più aggiornare i dispositivi.
> - **Rubata** → chiunque può firmare firmware che i tuoi dispositivi accetteranno.
>
> Conservala **offline** (due copie cifrate), non nel repository (`.gitignore` la esclude). In
> enterprise usa un HSM o una macchina di firma dedicata e la firma remota di ESP‑IDF.

### B2. Build release

```bash
docker run --rm -v "$PWD":/project -w /project espressif/idf:v5.5.6 \
  idf.py -B build-release -D SDKCONFIG=build-release/sdkconfig \
         -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.release" build
```

`sdkconfig.defaults.release` attiva:

| Opzione | Effetto |
|---|---|
| `CONFIG_SECURE_BOOT_V2_ENABLED` (RSA‑3072) | bootloader e app devono essere firmati con la tua chiave |
| `CONFIG_SECURE_FLASH_ENC_ENABLED` + `MODE_RELEASE` (AES‑256) | flash cifrata con chiave generata nel chip e non leggibile; niente più flash in chiaro via USB |
| `CONFIG_SECURE_ENABLE_SECURE_ROM_DL_MODE` | la ROM USB/UART non permette di leggere la flash |
| `CONFIG_NVS_ENCRYPTION` | NVS (Wi‑Fi, chiave privata, certificati) cifrata con chiavi in `nvs_keys` |
| `CONFIG_SECURE_SIGNED_ON_UPDATE` | anche gli aggiornamenti OTA devono essere firmati |
| Log al minimo, panic silenzioso | meno informazioni utili a un attaccante |

JTAG viene disabilitato via eFuse dalla flash encryption in release mode.

### B3. Primo flash di un dispositivo nuovo

Con Secure Boot V2 il bootloader va scritto **una volta**, separatamente dall'app:

```bash
docker run --rm --device=/dev/ttyACM0 -v "$PWD":/project -w /project espressif/idf:v5.5.6 \
  bash -c 'idf.py -B build-release -D SDKCONFIG=build-release/sdkconfig -p /dev/ttyACM0 bootloader-flash \
        && idf.py -B build-release -D SDKCONFIG=build-release/sdkconfig -p /dev/ttyACM0 flash'
```

Al **primo avvio** il bootloader:

1. registra negli eFuse l'impronta della tua chiave pubblica (Secure Boot);
2. genera la chiave di flash encryption **dentro il chip** e cifra la flash sul posto (circa un
   minuto: **non scollegare**);
3. blocca gli eFuse (JTAG off, download mode sicuro) e riavvia;
4. l'app genera le chiavi NVS e mostra "Configurazione".

Poi esegui il provisioning esattamente come in **A3**: la chiave privata del dispositivo viene
generata e salvata direttamente nella NVS cifrata.

> ⚠️ **Attenzione**: da questo momento **non puoi più flashare via USB**. Gli aggiornamenti passano
> solo dall'OTA firmata (B4). Se la chiave di firma va persa, il dispositivo resta con il firmware
> che ha.

### B4. Aggiornamenti OTA firmati

Il gateway offre il firmware ai dispositivi già autenticati (stessa connessione mTLS) e il
dispositivo installa solo versioni **più nuove** e **firmate**:

1. Aumenta la versione in `firmware/sdkconfig.defaults` (`CONFIG_APP_PROJECT_VER="0.1.1"`): è
   l'unica fonte della versione.
2. Ricompila in release (B2).
3. Pubblica l'immagine sul server:

   ```bash
   cp firmware/build-release/moody_edge.bin deploy/firmware/moody_edge.bin
   echo "0.1.1" > deploy/firmware/version.txt
   docker compose -f deploy/compose.yaml restart gateway   # i dispositivi si ricollegano
   ```

4. Al `hello`, il gateway risponde con `ota: {version, path}`; il dispositivo scarica
   `https://moody.lan:8443/v1/firmware/moody_edge.bin` con il proprio certificato, verifica la firma
   e si riavvia sul nuovo slot (`ota_0`/`ota_1`).
5. **Rollback automatico**: la nuova versione si conferma solo dopo aver raggiunto il gateway
   (`hello_ack`). Se si riavvia prima, il bootloader torna alla versione precedente.

Nei log: `ota_offered` e `firmware_download` (gateway).

> ℹ️ Con i firmware di **sviluppo** (senza Secure Boot) la firma non viene verificata: usa l'OTA
> solo in laboratorio finché non passi alla release.

---

## Factory reset e dismissione

- **Sul dispositivo**: tieni premuto lo schermo per 10 secondi → cancella Wi‑Fi, certificato e
  chiave privata → torna in "Configurazione".
- **Sul server**: revoca il seriale (`python -m moody.pki revoke ...`) e rimuovi o disattiva la voce
  in `devices.yaml`. In una struttura, cancella anche i dati del residente (vedi
  [08 · Sicurezza enterprise](08-sicurezza-enterprise.md)).

## Troubleshooting

| Sintomo | Causa probabile | Soluzione |
|---|---|---|
| `provision.py`: *device not in provisioning mode* | dispositivo già configurato, monitor seriale aperto, porta sbagliata | factory reset (10 s), chiudi `idf.py monitor`, verifica la porta |
| Resta su "Sincronizzo l'ora..." | NTP bloccato sulla rete IoT (il TLS verifica le date dei certificati) | consenti NTP verso il router/server, oppure reprovisiona con `--ntp <ip>` |
| "Server non raggiungibile" | firewall su 8443, DNS `moody.lan` non risolto, nome host diverso dal SAN del certificato | `openssl s_client -connect moody.lan:8443` dal PC, rigenera il cert del gateway con il nome giusto |
| Log gateway `device_rejected` | dispositivo non in `devices.yaml`, disattivato o seriale revocato | aggiungi/abilita la voce (ricarica a caldo) |
| La wake word non risponde | tasto Mute attivo, rumore di fondo, pronuncia | controlla il LED del Mute, pronuncia "hai i‑es‑pi", oppure usa il tocco |
| Risposte lente | modello troppo grande per il server | vedi [06 · Running](06-running.md) |

## Altre schede

Il firmware usa il BSP `espressif/esp-box-3`. Per un'altra scheda ESP32‑S3 con microfono, speaker e
display basta un BSP compatibile (`esp-bsp`), adattando `audio.c` (canali microfono) e `ui.c`
(risoluzione). Evita schede con **fotocamera** (es. SenseCAP Watcher, M5Stack CoreS3) o, se le usi,
disattivala e coprila: Moody non ne ha bisogno.

---

Prossimo passo → [06 · Running](06-running.md)
