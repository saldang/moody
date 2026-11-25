# 01 · Acquisto: la lista della spesa

Questa pagina elenca tutto ciò che serve per replicare Moody, in due configurazioni: **Home**
(una persona, una casa, un dispositivo) ed **Enterprise** (una struttura senior living con
dispositivi da dare ai residenti). Per ogni componente trovi a cosa serve, un prezzo indicativo
e le alternative. Le scelte di hardware seguono la stessa logica del software: *privacy e
sicurezza by design*. Niente telecamera, mute hardware, tutto il calcolo in locale.

> ℹ️ **Prezzi indicativi, novembre 2026**, IVA inclusa, in euro. Cambiano molto in base al
> canale e al periodo: usali per stimare il budget, non come preventivo.

## Prerequisiti

- Una connessione a Internet, **solo per la prima installazione** (download di immagini Docker e
  modelli). Dopo il bootstrap Moody funziona offline (vedi [03-setup-ambiente.md](03-setup-ambiente.md)).
- Un PC (Linux, macOS o Windows con WSL2) per compilare e flashare il firmware. Può essere lo
  stesso server.

---

## Perché l'ESP32-S3-BOX-3 (e non il dispositivo originale)

Il progetto originale usava un dispositivo ESP32-S3 / SenseCAP da circa 40 €. Noi partiamo dalla
stessa famiglia di chip (ESP32-S3), ma come riferimento scegliamo l'**Espressif ESP32-S3-BOX-3**:

| Caratteristica | Perché conta per Moody |
|---|---|
| ESP32-S3 con 16 MB flash + 16 MB PSRAM | Bastano per wake word on-device (ESP-SR WakeNet9), buffer audio, TLS e OTA A/B |
| Display touch da 2,4" | Mostra lo stato (in ascolto, sto pensando…) e permette il **tocco per parlare** |
| 2 microfoni + speaker con codec audio | Sono già integrati e non serve saldare nulla |
| **Pulsante mute hardware** con indicatore rosso | La persona può spegnere i microfoni con certezza fisica, senza fidarsi del software |
| **Nessuna telecamera** | Privacy by design: un sensore che non c'è non può essere abusato |
| Supporto ufficiale in ESP-IDF (BSP `espressif/esp-box-3`) | Firmware riproducibile, Secure Boot v2 e Flash Encryption supportati |

> ⚠️ **Attenzione: SenseCAP Watcher e altri dispositivi con telecamera.** Il SenseCAP Watcher
> (anche lui ESP32-S3) ha una telecamera. Se decidi di usarlo, il firmware di Moody non la
> utilizza, ma **copri fisicamente l'obiettivo** (adesivo opaco) e spiegalo alla persona. In una
> struttura, un dispositivo con telecamera in camera da letto richiede una valutazione d'impatto
> (DPIA) molto più pesante: vedi [09-privacy-by-design.md](09-privacy-by-design.md).

> ⚠️ **BOX-3-SENSOR: sconsigliato.** Alcuni kit includono o vendono a parte la scheda
> *BOX-3-SENSOR* (radar di presenza a 24 GHz, sensore di temperatura e umidità, IR). Il radar
> rileva la presenza e i movimenti delle persone nella stanza: è un dato comportamentale che Moody
> **non usa e non vuole raccogliere**. Usa il dock standard (BOX-3-DOCK). Se hai già la
> BOX-3-SENSOR, lasciala nella scatola.

---

## Tier HOME: un dispositivo, una casa

### Dispositivo e accessori

| # | Componente | Q.tà | Prezzo indicativo | Note |
|---|---|---|---|---|
| 1 | **ESP32-S3-BOX-3** (kit con BOX-3-DOCK) | 1 | 50–60 € | Va bene la versione "BOX-3" standard. Evita i bundle con BOX-3-SENSOR |
| 2 | Cavo USB-C **dati** (non solo ricarica), 1–2 m | 1 | 8 € | Serve per flash e provisioning. Molti cavi economici trasportano solo l'alimentazione |
| 3 | Alimentatore USB 5 V / 2 A (marchiato CE) | 1 | 10 € | Per l'uso quotidiano. Uno di qualità evita reset e ronzii nell'audio |

### Server: scegli **una** opzione

Il server esegue gateway, brain e **[QVAC di Tether](13-qvac.md)**, che serve LLM, embedding,
riconoscimento vocale (TranscribePsy) e sintesi vocale (Supertonic 3). Il fattore che più incide su
qualità e velocità è la memoria (e la potenza) disponibile per il modello linguistico.

**Requisiti minimi dello stack QVAC di default**: i modelli occupano circa **5 GB di RAM**
(Qwen3‑4B ~2,5 GB, bge‑m3 ~0,6 GB, TranscribePsy ~0,3 GB, Supertonic 3 ~0,13 GB, più la cache KV in
RAM); servono quindi **16 GB di RAM come minimo, 32 GB consigliati**. L'immagine Docker di QVAC pesa
circa 5,3 GB, i modelli circa 4 GB su disco. Su Linux QVAC usa la CPU o la GPU tramite Vulkan
(supporto NVIDIA in Docker sperimentale, vedi [13 · QVAC](13-qvac.md)).

| Opzione | Prezzo | Modello consigliato (alias `moody-llm` in QVAC) | Pro | Contro |
|---|---|---|---|---|
| **A. Mini PC AMD Ryzen 7 8845HS / 7840HS, 32 GB RAM, NVMe 1 TB** *(consigliata)* | 450–600 € | Qwen3‑4B (`QWEN3_4B_INST_Q4_K_M`, default) | Buon equilibrio tra costo, consumi (15–35 W) e silenziosità. Gira solo su CPU | Le risposte richiedono diversi secondi, di più quando il modello chiama uno strumento |
| **B. Mini PC Intel N150, 16 GB RAM** *(budget)* | 180–250 € | Qwen3‑4B (lento) oppure **BotPsy‑0.8B** di Tether (~4× più veloce, strumenti meno affidabili) | Economico, consuma 6–10 W | Lento; con 16 GB sei al minimo. La qualità dell'italiano cala con i modelli piccoli |
| **C. Desktop + GPU NVIDIA RTX 3060 12 GB usata** | 250 € (GPU usata) + PC | Qwen3‑8B (`QWEN3_8B_INST_Q4_K_M`), chiamate agli strumenti più affidabili | Molto più veloce, puoi riusare un PC esistente | Consumo e rumore maggiori. GPU in QVAC via Vulkan (`compose.gpu.yaml`, sperimentale); in alternativa Ollama con CUDA (`compose.classic.yaml`) |
| **D. Apple Mac mini M4, 16 GB** | 700 € | Qwen3‑4B | Silenzioso, efficiente; QVAC supporta macOS arm64 nativamente | Docker su macOS **non** accede alla GPU: QVAC va eseguito nativamente, fuori da Docker, e si perde parte dell'isolamento di rete (vedi [03-setup-ambiente.md](03-setup-ambiente.md#mac-mini)) |
| **E. NVIDIA Jetson Orin Nano Super Dev Kit 8 GB** | 280 € | BotPsy‑0.8B o Qwen3‑1.7B | Molto efficiente (7–25 W), con GPU | ARM64 con JetPack: sistema "di nicchia", 8 GB condivisi tra CPU e GPU sono sotto il minimo consigliato per lo stack completo |

> ℹ️ **Prestazioni misurate** (test di questo progetto, macchina virtuale con 4 vCPU, solo CPU):
> trascrizione 0,1–0,3 s per 2–3 s di audio; turni dell'LLM 25–45 s senza strumenti e 50–75 s con
> una chiamata a uno strumento; frasi di emergenza 0,5 s (guardrail deterministico, senza LLM).
> Su un mini PC Ryzen a 8 core o con una GPU la latenza è molto più bassa: misurala sul tuo hardware.

> 💡 **Suggerimento:** se non sai cosa scegliere prendi l'opzione A. Con un SSD NVMe di almeno
> 512 GB hai spazio per modelli, immagini Docker e backup locali cifrati.

### Rete (fortemente consigliato)

| # | Componente | Prezzo | Note |
|---|---|---|---|
| 4 | Router/AP con supporto **VLAN** e SSID separato per IoT, compatibile OpenWrt (es. GL.iNet Flint 2 o equivalenti) | 80–150 € | Isola il dispositivo Moody (e gli altri IoT) dalla rete dei PC e dei telefoni. Vedi [07-sicurezza-home.md](07-sicurezza-home.md) |
| 5 | UPS piccolo (600–850 VA), opzionale | 70–120 € | Evita corruzioni del filesystem e spegnimenti durante le notti con blackout |

### Totale stimato HOME

| Configurazione | Totale indicativo |
|---|---|
| Budget: BOX-3 + Mini PC N150 + accessori | **~260–330 €** |
| Consigliata: BOX-3 + Mini PC Ryzen 32 GB + router VLAN | **~600–820 €** |
| Performance: BOX-3 + desktop esistente + RTX 3060 usata + router VLAN | **~400–480 €** (escluso il PC) |

Dispositivi aggiuntivi in casa (un BOX-3 per stanza) costano circa 70 € l'uno, alimentatore incluso.
Il server resta uno solo.

---

## Tier ENTERPRISE: struttura senior living

Esempio di dimensionamento: **50 residenti**, un dispositivo per appartamento o camera, più il
**10% di scorte** (sostituzioni rapide, guasti, dispositivi in sanificazione).

### Dispositivi per i residenti

| # | Componente | Q.tà | Prezzo unitario | Totale | Note |
|---|---|---|---|---|---|
| 1 | ESP32-S3-BOX-3 (con BOX-3-DOCK) | 55 | 50–60 € | 2.750–3.300 € | 50 + 5 scorte. Per grandi quantità chiedi un'offerta a distributori (Mouser, DigiKey) o allo store Espressif |
| 2 | Alimentatore 5 V / 2 A con cavo lungo (2–3 m) | 55 | 12 € | 660 € | Cavo lungo per arrivare alla presa senza prolunghe |
| 3 | Cavi USB-C dati per provisioning (postazione IT) | 5 | 8 € | 40 € | Restano in laboratorio, non nelle camere |
| 4 | **Supporto o involucro stampato in 3D** (PETG, bordi arrotondati, fissaggio con viti o biadesivo 3M) | 55 | 6–15 € | 330–825 € | Impedisce cadute e furti accidentali. Il PETG resiste ai detergenti alcolici meglio del PLA |
| 5 | Fermacavi, canaline adesive | 55 kit | 4 € | 220 € | Anti-inciampo, vedi [02-montaggio.md](02-montaggio.md) |
| 6 | **Etichette asset tag** (QR + codice dispositivo, **senza nomi**) | 1 rotolo | 30 € | 30 € | Riportano solo l'ID tecnico (`moody-xxxxxx`) |
| 7 | Materiale di pulizia: alcol isopropilico 70%, panni in microfibra | – | – | 50 € | Mai spruzzare direttamente sul dispositivo |

### Server e infrastruttura

| # | Componente | Q.tà | Prezzo indicativo | Note |
|---|---|---|---|---|
| 8 | **Server GPU** 1U/2U o tower: CPU 16+ core, **64–128 GB RAM ECC**, **2× NVMe in mirror (RAID1)**, 2 alimentatori | 1 (o 2 per HA) | 6.000–9.000 € cad. | Con l'alta affidabilità servono due nodi, uno attivo e uno in standby |
| 9 | GPU **NVIDIA L4 24 GB** (bassi consumi, 72 W, data center) **oppure** RTX 4000 Ada 20 GB | 1 per nodo | 2.500–3.500 € | Esegue il LLM (QVAC con Vulkan, oppure vLLM/Ollama con CUDA) e la trascrizione |
| 10 | UPS rack 1500–3000 VA con scheda di rete | 1 | 800–1.500 € | Arresto pulito automatico |
| 11 | **Switch gestito** con VLAN e PoE per gli AP | 1–2 | 400–1.200 € | VLAN dedicata ai dispositivi Moody |
| 12 | Wi-Fi enterprise: AP con **WPA3** e **PPSK** (una chiave per dispositivo) o 802.1X | secondo planimetria | 150–400 € per AP | Con PPSK puoi revocare un singolo dispositivo anche a livello Wi-Fi |
| 13 | Custodia della CA: **portatile offline dedicato** (cifrato, mai in rete) **oppure YubiHSM 2** | 1 | 400 € / ~650 € | Protegge la chiave della CA dei dispositivi, vedi [04-pki-identita.md](04-pki-identita.md) |
| 14 | NAS o storage per backup cifrati (fuori dal rack o in altra sede) | 1 | 600–1.500 € | Backup di segreti, PKI e database cifrato |

### Totale stimato ENTERPRISE (50 residenti)

| Voce | Singolo nodo | Alta affidabilità (2 nodi) |
|---|---|---|
| Dispositivi e accessori (righe 1–7) | ~4.100–5.100 € | ~4.100–5.100 € |
| Server + GPU (righe 8–9) | ~8.500–12.500 € | ~17.000–25.000 € |
| Rete, UPS, CA, backup (righe 10–14) | ~2.500–5.500 € | ~3.000–6.000 € |
| **Totale hardware** | **~15.000–23.000 €** | **~24.000–36.000 €** |

Questi totali **non includono**: cablaggio, installazione degli AP, ore di IT e formazione dello staff,
consulenza legale e DPO per la DPIA.

### Dimensionamento indicativo: conversazioni contemporanee

Una "conversazione contemporanea" è un turno vocale in elaborazione nello stesso istante. In una
struttura con 50 residenti, raramente parlano più di 3–5 persone nello stesso secondo.

| Hardware LLM | Modello | Backend | Turni contemporanei con latenza accettabile (< 3 s) |
|---|---|---|---|
| Mini PC Ryzen, solo CPU | Qwen3‑4B | QVAC | 1 (latenza di diversi secondi) |
| RTX 3060 12 GB | Qwen3‑8B | QVAC (Vulkan) o Ollama (`OLLAMA_NUM_PARALLEL=2–4`) | 2–4 |
| NVIDIA L4 24 GB | modello 8B | vLLM | 8–15 |
| RTX 4000 Ada 20 GB | modello 8B | vLLM | 6–12 |
| 2× L4 (due nodi) | modello 8B | vLLM | 16–30 (o 8–15 con failover) |

> ℹ️ Sono stime di massima, non misure (tranne la riga CPU, vedi sopra). Anche la trascrizione usa CPU
> o GPU. Per molti turni contemporanei vLLM (`MOODY_LLM_BACKEND=openai`) resta l'opzione più
> collaudata per il solo LLM. Misura con il tuo carico reale
> prima di comprare il secondo nodo.

---

## Dove comprare

- **Store ufficiale Espressif** (su marketplace internazionali): il canale più diretto per il BOX-3.
- **Distributori di elettronica** (Mouser, DigiKey, Farnell): fattura, tracciabilità, quantità.
  Sono la scelta giusta per l'enterprise.
- **Amazon e grandi marketplace**: comodi per accessori e alimentatori. Controlla il marchio CE e
  diffida dei cloni senza marchio.
- **Server e GPU**: rivenditori di server certificati (garanzia NBD) per l'enterprise. Per casa va
  bene il mercato dell'usato, ma solo per la GPU (RTX 3060).

> ⚠️ **Attenzione: catena di fornitura.** Per l'enterprise acquista da canali ufficiali e, alla
> consegna, **riflasha sempre** il firmware con la tua build firmata prima di consegnare il
> dispositivo a un residente (vedi [05-setup-device.md](05-setup-device.md)). Non fidarti mai del
> firmware preinstallato.

---

Prossimo passo → [02 · Montaggio](02-montaggio.md)
