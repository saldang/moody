# 12 · Protocollo edge ⇄ gateway (`moody.v1`)

Specifica del protocollo tra dispositivo e gateway. È volutamente piccolo: messaggi di controllo
JSON nei frame di testo, audio PCM grezzo nei frame binari. Serve a chi vuole portare Moody su
un'altra scheda, scrivere un client di test o fare una revisione di sicurezza.

## Prerequisiti

Conoscenza di base di WebSocket e TLS. Implementazioni di riferimento:
`firmware/main/main.c`, `firmware/main/link.c` (dispositivo) e `server/moody/gateway/` (gateway).

---

## 1. Trasporto

| Aspetto | Valore |
|---|---|
| URL | `wss://<host>:8443/v1/ws` |
| Sottoprotocollo | `moody.v1` (obbligatorio: senza, HTTP 400) |
| TLS | 1.2 (solo ECDHE‑ECDSA + AES‑GCM/ChaCha20) o 1.3; **certificato client obbligatorio** firmato dalla `device-ca` |
| Autorizzazione | prima dell'upgrade: CN registrata e abilitata in `devices.yaml`, seriale non revocato → altrimenti **HTTP 403** |
| Una connessione per dispositivo | una seconda connessione con lo stesso certificato chiude la prima (codice 4009) e lascia un evento `device_duplicate_connection` |
| Keepalive | ping ogni 15 s (dispositivo) / 20 s (gateway) |
| Inattività | chiusura dopo 300 s senza messaggi |

## 2. Limiti imposti dal gateway

| Limite | Valore | Motivo |
|---|---|---|
| Frame | 8 KiB | memoria, DoS |
| Messaggio di controllo | 1 KiB | parsing sicuro |
| Durata di un'enunciazione | 15 s (480 KB) | DoS, privacy |
| Audio fuori da `listen_start` … `listen_end` | **scartato** | l'audio è accettato solo in una finestra esplicita |
| Audio < 0,5 s o silenzio (RMS) | ignorato, nessuna trascrizione | evita trascrizioni inutili |

## 3. Formato audio

PCM **signed 16‑bit little endian, mono, 16 kHz**, in entrambe le direzioni. Il gateway converte
l'uscita di Piper (di solito 22,05 kHz) a 16 kHz e la invia in blocchi da 4 KiB.

## 4. Messaggi dispositivo → gateway

| `type` | Campi | Quando |
|---|---|---|
| `hello` | `fw` (versione), `proto` (1) | subito dopo la connessione |
| `listen_start` | `follow_up?` (bool) | wake word o tocco: inizia la finestra di ascolto. Senza `follow_up` il gateway apre una **nuova conversazione** (la memoria breve non passa da un'interazione all'altra); con `follow_up: true` (riapertura automatica dopo una domanda di Moody) resta nella stessa |
| *(binario)* | PCM | solo durante la finestra |
| `listen_end` | — | fine parlato (VAD on‑device) o tocco |
| `abort` | — | annulla ascolto/risposta (tocco durante la risposta, nessuno ha parlato) |

## 5. Messaggi gateway → dispositivo

| `type` | Campi | Significato |
|---|---|---|
| `hello_ack` | `session`, `proto`, `ota?` = `{version, path}` | connessione accettata; eventuale aggiornamento disponibile |
| `state` | `value`: `thinking` \| `idle` \| `error` | stato della pipeline |
| `stt` | `display` | trascrizione da mostrare (ASCII, accenti come `e'`) |
| `reply` | `display` | testo della risposta da mostrare |
| `tts_start` | `rate` (16000) | stanno per arrivare frame audio |
| *(binario)* | PCM | voce sintetizzata |
| `tts_end` | `follow_up` (bool) | fine audio; se `true` il dispositivo riapre l'ascolto per 6 s |

I testi per il display sono convertiti in ASCII dal gateway perché i font integrati di LVGL non
contengono le lettere accentate.

## 6. Sequenza tipica

```text
D → G   {"type":"hello","fw":"0.1.0","proto":1}
G → D   {"type":"hello_ack","session":"9f2c…","proto":1}
        … "Hi ESP" …
D → G   {"type":"listen_start"}
D → G   <PCM> <PCM> <PCM> …
D → G   {"type":"listen_end"}
G → D   {"type":"state","value":"thinking"}
G → D   {"type":"stt","display":"che attivita' ci sono domani?"}
G → D   {"type":"reply","display":"Domani alle 10 c'e' la passeggiata nel parco. Vuoi un promemoria?"}
G → D   {"type":"tts_start","rate":16000}
G → D   <PCM> <PCM> …
G → D   {"type":"tts_end","follow_up":true}
D → G   {"type":"listen_start","follow_up":true}   ← finestra di follow-up (6 s), stessa conversazione
```

Promemoria proattivi: ogni 30 s il gateway chiede al brain i promemoria scaduti per quel
dispositivo (mai durante le `quiet_hours` o mentre l'utente parla) e li invia come
`reply` + `tts_start` … `tts_end`.

## 7. Endpoint OTA

`GET https://<host>:8443/v1/firmware/moody_edge.bin` sulla stessa porta, con lo **stesso mTLS e la
stessa autorizzazione** del WebSocket. Il gateway lo offre in `hello_ack` solo se la versione in
`deploy/firmware/version.txt` è **maggiore** di quella dichiarata dal dispositivo; il dispositivo
rifiuta comunque i downgrade e, in release, le immagini non firmate.

## 8. API interne (per completezza)

| Da → a | Endpoint | Auth |
|---|---|---|
| gateway → brain | `POST /v1/turn` `{subject, session_id, text}` → `{reply, end_session, category}` | mTLS `service-ca` (+ Bearer OIDC in enterprise) |
| gateway → brain | `GET /v1/notifications?subject=` → `{items: [...]}` | come sopra |
| brain → wellbeing | MCP Streamable HTTP su `https://wellbeing:8090/mcp` | mTLS `service-ca`, protezione DNS‑rebinding |
| gateway → whisper/piper | protocollo Wyoming su TCP | rete docker `core` interna |

`category` può valere `chat`, `tool`, `confirm`, `self_harm`, `medical_emergency`,
`prompt_injection`, `too_long`, `guard:<rischio>`, `error`.

---

Prossimo passo → torna all'[indice della documentazione](README.md)
