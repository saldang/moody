# 10 · Licenze e scelte consapevoli (MIT)

Il codice di questo repository è distribuito con **licenza MIT**. Una licenza permissiva è una buona scelta
per un progetto che vuole essere replicato da privati, maker, aziende e strutture di assistenza, ma impone di
**scegliere con cura le dipendenze**: un solo componente copyleft collegato nel modo sbagliato, o un modello con
licenza non commerciale, può rendere impossibile usare o distribuire il progetto come previsto. Questo documento
elenca ogni componente, come viene usato e cosa comporta.

> ⚠️ **Attenzione**: questa è un'analisi tecnica fatta in buona fede, **non è una consulenza legale**.
> Le licenze cambiano: verifica sempre la versione che stai usando, soprattutto prima di distribuire dispositivi
> o usare Moody in ambito commerciale.

---

## 1. Concetti chiave

- **Licenza permissiva** (MIT, BSD, Apache-2.0): puoi usare, modificare e ridistribuire, anche in prodotti chiusi,
  mantenendo copyright e testo della licenza. Apache-2.0 aggiunge una licenza esplicita sui brevetti e l'obbligo di
  riportare i file `NOTICE`.
- **Copyleft forte** (GPL-3.0, AGPL-3.0): chi distribuisce un'opera *derivata* deve renderne disponibile il sorgente
  con la stessa licenza. L'AGPL estende l'obbligo all'uso via rete.
- **Opera derivata vs aggregazione**: collegare staticamente o dinamicamente una libreria GPL nello stesso
  programma crea, secondo l'interpretazione prevalente, un'opera derivata. **Programmi separati** che comunicano
  tramite socket, pipe o protocolli di rete con interfacce generiche sono una semplice *aggregazione*: ognuno
  mantiene la propria licenza.
- **Licenze dei modelli**: i pesi dei modelli AI hanno licenze proprie, spesso diverse da quelle del codice che li
  esegue (licenze "community", "responsible AI", non commerciali).
- **Distribuire** è il momento che conta: usare un software GPL internamente non attiva obblighi; **consegnare un
  dispositivo** con firmware GPL ai residenti invece sì.

Le scelte di Moody seguono tre regole:

1. tutto ciò che è **collegato** al nostro codice (librerie Python, componenti firmware) è permissivo;
2. i componenti copyleft girano come **servizi separati** (container) raggiunti via protocollo di rete;
3. i **modelli** di default hanno licenze permissive (Apache-2.0 / MIT) che consentono anche l'uso commerciale.

---

## 2. Componenti

### 2.1 Codice Moody e librerie Python (collegate)

| Componente | Ruolo | Licenza | Uso | Implicazioni |
|------------|-------|---------|-----|--------------|
| Moody (questo repo) | gateway, brain, wellbeing MCP, PKI, firmware, script | **MIT** | — | mantieni copyright e licenza nelle copie |
| websockets | WSS del gateway | BSD-3-Clause | importata | permissiva |
| FastAPI | API del brain | MIT | importata | permissiva |
| uvicorn | server ASGI | BSD-3-Clause | importata | permissiva |
| httpx (e httpx2, dipendenza dell'SDK MCP) | client HTTP | BSD-3-Clause | importata | permissiva |
| wyoming | protocollo verso STT/TTS | MIT | importata | permissiva |
| mcp (Python SDK) | client/server MCP | MIT | importata | permissiva |
| pydantic | validazione | MIT | importata | permissiva |
| PyYAML | configurazione | MIT | importata | permissiva |
| cryptography | TLS, PKI, Fernet | Apache-2.0 OR BSD-3-Clause | importata | permissiva (NOTICE Apache se scegli quella) |
| PyJWT | verifica token OIDC | MIT | importata | permissiva |
| numpy | ricampionamento audio, RAG | BSD-3-Clause | importata | permissiva |
| pyserial | provisioning USB (extra `pki`) | BSD-3-Clause | importata, solo strumenti | permissiva |

Le licenze sono annotate accanto a ogni dipendenza in `server/pyproject.toml`.

### 2.2 Firmware (collegato nel binario del dispositivo)

| Componente | Ruolo | Licenza | Implicazioni |
|------------|-------|---------|--------------|
| ESP-IDF | SDK, FreeRTOS, mbedTLS, driver | Apache-2.0 (FreeRTOS MIT, mbedTLS Apache-2.0) | includere licenze/NOTICE quando distribuisci il binario |
| espressif/esp-box-3 (BSP) | supporto hardware del BOX-3 | Apache-2.0 | come sopra |
| espressif/esp_websocket_client | client WSS | Apache-2.0 | come sopra |
| esp_codec_dev, esp_lvgl_port | audio codec, porting LVGL | Apache-2.0 | come sopra |
| LVGL | interfaccia grafica | MIT | includere il copyright |
| **ESP-SR** (WakeNet "Hi ESP", AFE) | wake word on-device | **"ESPRESSIF MIT License"** | vedi sotto |

**ESP-SR**: il testo della licenza (verificato sulla versione 2.6.2 del registry) concede i permessi MIT
*"for use on all ESPRESSIF SYSTEMS products"*. Su un ESP32-S3 l'uso è quindi consentito, anche commerciale, ma la
licenza **non è OSI** perché limita l'hardware: non puoi portare quel codice o quei modelli su chip di altri produttori.
Il componente non è copiato nel repository: viene scaricato dal component manager durante la build.

Alternativa completamente open: **microWakeWord** (Apache-2.0, modelli TFLite Micro) per un wake word portabile.
Richiede l'integrazione di TensorFlow Lite Micro (Apache-2.0) nel firmware: non è implementata in Moody 0.1.

### 2.3 Servizi separati (container, comunicazione via rete)

| Componente | Ruolo | Licenza | Uso | Implicazioni |
|------------|-------|---------|-----|--------------|
| Ollama | runtime LLM (home) | MIT | container, HTTP | permissiva |
| llama.cpp | motore dentro Ollama / alternativa | MIT | indiretto | permissiva |
| vLLM | runtime LLM (enterprise, opzionale) | Apache-2.0 | container, API OpenAI-compatibile | permissiva |
| faster-whisper | STT | MIT | dentro `rhasspy/wyoming-whisper` | permissiva |
| wyoming-faster-whisper | server Wyoming STT | MIT | container | permissiva |
| **Piper** (OHF-Voice `piper1-gpl`) | TTS | **GPL-3.0** | dentro `rhasspy/wyoming-piper` 2.x, container separato via protocollo Wyoming | **nessun collegamento** con il nostro codice → aggregazione; il repo resta MIT. Se ridistribuisci l'immagine, rispetta la GPL (sorgente disponibile upstream) |
| espeak-ng | fonemizzazione per Piper | GPL-3.0 | dentro il container Piper | come sopra |
| wyoming-piper | server Wyoming TTS | MIT | container | permissiva |
| ntfy | notifiche di aiuto | Apache-2.0 / GPL-2.0 (doppia) | container, HTTP | scegli Apache-2.0 |
| Keycloak | OIDC (enterprise) | Apache-2.0 | container | permissiva |
| PostgreSQL | DB di Keycloak | PostgreSQL License | container | permissiva |
| Home Assistant (opzionale) | domotica via MCP | Apache-2.0 | servizio esterno dell'utente | permissiva |

> ℹ️ **Nota storica su Piper**: il progetto originale `rhasspy/piper` era MIT ed è stato archiviato; il successore
> `OHF-Voice/piper1-gpl` è GPL-3.0. Moody non importa Piper e non ne include codice: dialoga con il container
> tramite Wyoming, un protocollo generico basato su eventi JSON su socket TCP
> (`server/moody/gateway/speech.py`).

### 2.4 Modelli (scaricati a runtime, non inclusi nel repo)

| Modello | Ruolo | Licenza | Uso commerciale |
|---------|-------|---------|-----------------|
| **Qwen3** (`qwen3:8b`, `qwen3:4b`) | LLM di default | Apache-2.0 | sì |
| **bge-m3** | embedding RAG | MIT | sì |
| **IBM Granite Guardian** (`granite3-guardian`) | classificatore di sicurezza opzionale | Apache-2.0 | sì |
| Whisper (pesi OpenAI, conversioni faster-whisper) | STT | MIT | sì |
| **Voci Piper** (es. `it_IT-paola-medium`) | TTS | **variabile per voce** | verifica il `MODEL_CARD` della voce: alcuni dataset sono non commerciali o richiedono attribuzione |

> ⚠️ **Attenzione**: prima di un uso in struttura apri il `MODEL_CARD` della voce scelta (`PIPER_VOICE`) e annota
> licenza e attribuzione richiesta. Cambia voce se la licenza del dataset non consente il tuo caso d'uso.

### 2.5 Componenti evitati o segnalati

| Componente | Licenza | Perché non è il default |
|------------|---------|-------------------------|
| Llama (Meta) | Llama Community License | non OSI, clausole d'uso e limiti per grandi aziende; restrizioni passate per l'UE su alcune versioni multimodali |
| Gemma (Google) | Gemma Terms of Use | termini propri con politica d'uso vietato vincolante |
| openWakeWord: **modelli pre-addestrati** | CC BY-NC-SA 4.0 | **non commerciale**: inadatti a una struttura o a un prodotto (il codice è Apache-2.0) |
| ESPHome: runtime C++ del firmware | GPL-3.0 (parte Python MIT) | consegnare ai residenti dispositivi con firmware ESPHome obbligherebbe a offerta del sorgente e diritti GPL sul binario: per questo Moody ha un **firmware proprio su ESP-IDF** (Apache-2.0) |
| Grafana | AGPL-3.0 | non incluso; usabile come servizio separato se accetti l'AGPL |
| Microsoft Presidio | MIT | licenza compatibile, ma non usato: per coerenza con l'obiettivo "senza stack Microsoft" e per restare leggeri Moody ha un redattore PII proprio (`server/moody/common/pii.py`) |

---

## 3. Se distribuisci dispositivi (casa → regalo, struttura → residenti)

Distribuire il binario del firmware attiva gli obblighi delle licenze permissive:

1. **Elenco delle licenze**: prepara una pagina o un libretto "Licenze open source" con i testi di Apache-2.0 (e i
   file `NOTICE` dei componenti ESP-IDF che li hanno), MIT di LVGL, Moody e FreeRTOS, e il testo della
   **ESPRESSIF MIT License** di ESP-SR.
2. **Come raccoglierle**: dopo la build, i componenti scaricati sono in `firmware/managed_components/*/LICENSE*`;
   ESP-IDF include le sue licenze nel proprio albero. Uno script che copia questi file in una cartella `licenses/`
   da allegare alla documentazione è sufficiente.
3. **Dove renderle disponibili**: nel manuale consegnato con il dispositivo, su una pagina web della struttura o
   tramite un QR code sulla scheda in camera.
4. **Server e container**: se fornisci il server già installato, includi anche le licenze delle immagini usate
   (Piper GPL-3.0 e espeak-ng GPL-3.0 richiedono che il sorgente corrispondente sia disponibile: indica dove
   ottenerlo, ad esempio i repository upstream alla versione usata).
5. **Marchi**: "Moody" è il nome del progetto; non usare marchi di terzi (Espressif, Home Assistant…) in modo che
   suggerisca un'approvazione ufficiale.

---

## 4. Aggiungere una nuova dipendenza: checklist

- [ ] Qual è la licenza **esatta** della versione che userai (file `LICENSE`, metadati del pacchetto, model card)?
- [ ] È permissiva (MIT, BSD, Apache-2.0, ISC, PostgreSQL, Zlib)? → ok se **collegata**.
- [ ] È copyleft (GPL, LGPL, AGPL, MPL)? → solo come **servizio separato** via rete, mai importata nel nostro codice
      né nel firmware. LGPL/MPL richiedono comunque una valutazione specifica.
- [ ] È un **modello**? Licenza dei pesi, eventuali restrizioni d'uso, attribuzione, uso commerciale, dati di addestramento.
- [ ] Ha restrizioni di campo d'uso o di hardware (come ESP-SR)? Documentale qui.
- [ ] Aggiungi la licenza come commento in `server/pyproject.toml` o nel manifest del componente firmware.
- [ ] Aggiorna le tabelle di questo documento.
- [ ] Esegui `pip-audit` e valuta la manutenzione del progetto (rilasci recenti, issue di sicurezza).

---

**Prossimo passo →** [11 · Red teaming](11-red-teaming.md)
