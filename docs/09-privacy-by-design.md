# 09 · Privacy by design

Moody nasce per essere un assistente di benessere che **non sorveglia**. Questo documento collega l'art. 25
del GDPR (protezione dei dati fin dalla progettazione e per impostazione predefinita) e i sette principi di
*Privacy by Design* di Ann Cavoukian a **scelte concrete del codice**, elenca ogni dato trattato, spiega
come esercitare i diritti degli interessati e come Moody si posiziona rispetto all'**EU AI Act** e al
regolamento sui dispositivi medici. Chiude uno schema di DPIA e alcune linee guida etiche.

> ℹ️ **Nota**: questo documento descrive il comportamento del software. La conformità dipende anche da
> come lo installi e lo gestisci: vedi [07-sicurezza-home.md](07-sicurezza-home.md) e
> [08-sicurezza-enterprise.md](08-sicurezza-enterprise.md). Non è una consulenza legale.

---

## 1. I sette principi, in pratica

| Principio (Cavoukian) | Come lo applica Moody | Dove nel codice / configurazione |
|-----------------------|-----------------------|----------------------------------|
| **1. Proattivo, non reattivo** | Minacce analizzate prima di scrivere codice; guardrail deterministici per crisi/emergenze; red teaming ripetibile | `docs/07`, `server/moody/brain/guardrails.py`, `redteam/` |
| **2. Privacy come impostazione predefinita** | Nessuna trascrizione nei log; nessuna memoria conversazionale persistente; diario dell'umore usato **solo** se la persona lo chiede; retention 30 giorni; tool *deny by default* | `MOODY_LOG_TRANSCRIPTS=false`, `AgentSettings.session_ttl=600`, `MOODY_RETENTION_DAYS=30`, `deploy/config/tool-policy.yaml` |
| **3. Privacy incorporata nel progetto** | Wake word sul dispositivo: niente audio prima di "Hi ESP" o del tocco; nessuna fotocamera; pseudonimi al posto dei nomi; identità iniettata lato server | firmware ESP-SR, `gateway/server.py` (audio accettato solo tra `listen_start` e `listen_end`), `devices.yaml`, `brain/tools.py` (`INJECTED_PARAMS`) |
| **4. Funzionalità piena (positive-sum)** | Assistente utile (promemoria, attività, respirazione, domotica) **senza** cloud: tutto gira in locale con modelli open | `deploy/compose.yaml` (Ollama, faster-whisper, Piper locali) |
| **5. Sicurezza end-to-end, per tutto il ciclo di vita** | mTLS su ogni salto, due CA, Secure Boot + Flash Encryption, diario cifrato, retention automatica, cancellazione su richiesta, factory reset | `common/tls.py`, `moody/pki.py`, `wellbeing_mcp/store.py` |
| **6. Visibilità e trasparenza** | Codice aperto MIT; il sistema dichiara di essere un'AI; policy leggibili in YAML; eventi di audit documentati | `brain/prompts.py`, `docs/08` §10 |
| **7. Rispetto per l'utente** | Mute hardware; cancellazione a voce; nessuna inferenza emotiva; incoraggia i contatti umani; linguaggio semplice e risposte brevi | system prompt, `erase_my_data` |

---

## 2. Inventario dei dati

| Dato | Dove | Per quanto | Protezione | Base giuridica (indicativa) |
|------|------|------------|------------|-----------------------------|
| **Audio ambientale** prima del wake word | solo buffer circolare in RAM del dispositivo | millisecondi | non esce mai dal dispositivo | — (non trattato dal sistema) |
| **Audio della richiesta** (dopo wake word/tocco) | RAM del gateway | fino alla fine della trascrizione (max 15 s di audio) | TLS (mTLS) in transito; **mai scritto su disco** | esecuzione del servizio richiesto (art. 6.1.b) o consenso |
| **Trascrizione** | RAM del brain, cronologia di sessione | ≤ 10 minuti di inattività, max 6 scambi | non loggata (`MOODY_LOG_TRANSCRIPTS=false`) | come sopra |
| **Risposta e audio TTS** | RAM gateway | durata della risposta | TLS | come sopra |
| **Diario dell'umore** (punteggio 1-5, nota facoltativa ≤ 280 caratteri) | SQLite `deploy/data/wellbeing/` | `MOODY_RETENTION_DAYS` (default 30) | Fernet (AES + HMAC), pseudonimo hashato con HMAC, `secure_delete` | **categoria particolare** (benessere/salute): **consenso esplicito** art. 9.2.a |
| **Promemoria** (testo ≤ 200 caratteri, orario) | SQLite come sopra | fino alla consegna + 1 giorno, comunque entro la retention | come sopra | esecuzione del servizio / consenso; attenzione ai promemoria su farmaci (dato sanitario) |
| **Richieste di aiuto** | messaggio ntfy (pseudonimo + motivo breve) | `cache-duration: 24h` in ntfy | accesso ntfy `deny-all` + token | interesse vitale (art. 6.1.d / 9.2.c) o consenso, da definire in DPIA |
| **Log di audit** | stdout dei container (driver `local`, 3×10 MB) o SIEM | rotazione / policy definita | redazione PII automatica, nessun testo delle conversazioni, solo pseudonimi | legittimo interesse / obbligo di sicurezza (art. 32) |
| **Knowledge base** | `deploy/knowledge/` + indice `deploy/data/brain/knowledge.sqlite3` | finché presente | contenuti **non personali** per regola | — |
| **Certificati dei dispositivi** | dispositivo (NVS cifrata); `deploy/pki/issued.csv` (seriale, CN, scadenza) | validità del certificato | chiave privata solo sul dispositivo | sicurezza del sistema |
| **Registro dispositivi** | `deploy/config/devices.yaml` | finché il dispositivo è in uso | solo CN ↔ pseudonimo, **nessun nome** | sicurezza / esecuzione del servizio |

Cosa Moody **non** raccoglie: immagini, video, impronta vocale/biometria, posizione, contatti, cronologia
delle conversazioni, dati di presenza (il dock radar non va montato), telemetria verso terzi.

---

## 3. Elaborazione solo locale

- **Nessuna chiamata a servizi cloud** nel percorso dei dati: STT (faster-whisper), LLM (Ollama/vLLM),
  embedding (bge-m3), TTS (Piper) girano sul server della casa o della struttura.
- **Runtime offline**: le reti Docker `core`, `ai`, `tools` sono `internal`; i modelli vengono scaricati una
  volta con `scripts/bootstrap-models.sh` e poi i container sono ricreati senza Internet.
- **Nessuna telemetria** nel codice Moody. ntfy è configurato senza `upstream-base-url` (che inoltrerebbe
  metadati a ntfy.sh).

> ⚠️ **Attenzione**: se colleghi Home Assistant (`compose.homeassistant.yaml`) o usi un backend LLM remoto
> (`MOODY_LLM_BACKEND=openai` verso un servizio esterno), il perimetro cambia: aggiorna la DPIA.

---

## 4. Diritti degli interessati

| Diritto | Stato in Moody 0.1 |
|---------|--------------------|
| **Informazione** (artt. 13-14) | a cura del titolare; usa una versione easy-read (vedi [08](08-sicurezza-enterprise.md#2-onboarding-del-residente-e-consenso-informato)) |
| **Accesso / portabilità** (artt. 15, 20) | a voce si può chiedere il riepilogo dell'umore (`mood_summary`) e l'elenco dei promemoria (`list_reminders`). L'export completo esiste come funzione (`WellbeingStore.export_subject`) ma **non è ancora esposto** come tool vocale né come comando: in roadmap. Nel frattempo l'amministratore può estrarlo con uno script |
| **Cancellazione** (art. 17) | a voce: "cancella i miei dati" → conferma "sì" → tool `erase_my_data` (livello `confirm`) cancella diario e promemoria dello pseudonimo e fa `VACUUM`. Le conversazioni non vanno cancellate perché non sono conservate |
| **Rettifica** (art. 16) | un check-in errato si corregge con un nuovo check-in; i promemoria si annullano a voce (`cancel_reminder`). Rettifica puntuale del diario: roadmap |
| **Opposizione / revoca del consenso** (artt. 7, 21) | tasto mute, spegnimento, rinuncia al dispositivo senza conseguenze sui servizi; revoca del consenso al diario + cancellazione |
| **Decisioni automatizzate** (art. 22) | Moody non prende decisioni con effetti giuridici o analoghi; l'escalation allo staff è un avviso, la decisione resta umana |

---

## 5. EU AI Act

| Tema | Riferimento | Posizione di Moody |
|------|-------------|--------------------|
| **Trasparenza verso chi interagisce con un'AI** | art. 50.1 | Il system prompt (`server/moody/brain/prompts.py`) impone di dichiararsi un sistema di AI e non una persona; il red teaming verifica il caso (`ai-disclosure-01`). Informativa e scheda in camera lo ribadiscono |
| **Divieto di riconoscimento delle emozioni sul luogo di lavoro e negli istituti di istruzione** | art. 5.1.f | Moody **non deduce emozioni** da voce, volto o altri dati biometrici. Il "mood" è solo **auto-dichiarato** (punteggio 1-5 che la persona sceglie di dire). Il system prompt vieta di dedurre emozioni dalla voce. In una struttura, che è anche luogo di lavoro dello staff, questo evita di ricadere nel divieto e nei sistemi ad alto rischio dell'Allegato III |
| **Sistemi di riconoscimento delle emozioni / categorizzazione biometrica** (fuori dal divieto) | art. 50.3, Allegato III | non applicabile: nessuna elaborazione biometrica, nessuna identificazione del parlante |
| **Modelli GPAI** | capo V | Moody **usa** modelli open (Qwen3, Apache-2.0) come *deployer*: non immette sul mercato un GPAI; verifica le informazioni pubblicate dal fornitore del modello |
| **Alfabetizzazione AI** | art. 4 | formazione dello staff che usa o gestisce il sistema ([08](08-sicurezza-enterprise.md#9-formazione-dello-staff)) |

> ⚠️ **Attenzione**: aggiungere funzioni come analisi del tono di voce, rilevamento di depressione, punteggi di
> rischio o monitoraggio del personale cambierebbe radicalmente la classificazione (divieti o alto rischio).
> Non farlo senza una nuova valutazione.

### Non è un dispositivo medico (MDR 2017/745)

La qualificazione come dispositivo medico dipende dalla **destinazione d'uso dichiarata**. Moody non diagnostica,
non monitora parametri, non suggerisce terapie né dosaggi. Formula suggerita per documentazione e materiali:

> *"Moody è un assistente vocale per il benessere quotidiano e l'organizzazione personale (promemoria,
> informazioni sulle attività, esercizi di rilassamento, diario dell'umore auto-dichiarato). Non è un
> dispositivo medico, non fornisce diagnosi, non monitora condizioni cliniche, non sostituisce il parere
> del medico né i sistemi di chiamata o di emergenza. In caso di emergenza chiamare il 112."*

Le protezioni tecniche coerenti con questa destinazione d'uso:

- system prompt: niente diagnosi, sintomi, farmaci o dosaggi; invito a sentire medico, farmacista, staff;
- filtro di output: una risposta che contiene un dosaggio (`mg`, `compresse`… + frequenza) viene sostituita con
  un rinvio al medico (`DOSAGE_REPLY`);
- frasi di emergenza e crisi: risposta fissa, non generata dal modello.

### Persone vulnerabili

Anziani, persone con declino cognitivo o in solitudine richiedono attenzione particolare: linguaggio semplice,
nessuna pressione, nessuna funzione che crei dipendenza, consenso rivalutato nel tempo, coinvolgimento di
familiari o amministratori di sostegno quando previsto.

---

## 6. Linee guida etiche

1. **Le persone prima della macchina**: il system prompt chiede di incoraggiare contatti con familiari, amici,
   staff e attività di gruppo. Moody non si presenta mai come "amico" che sostituisce le relazioni.
2. **Nessuna dipendenza**: niente notifiche per "riportare" la persona a parlare con Moody; i messaggi proattivi
   sono solo i promemoria richiesti dalla persona, mai nelle `quiet_hours`.
3. **Dignità**: tono cortese, niente infantilizzazione, del "tu" solo se la persona lo usa.
4. **Nessun dark pattern**: niente gamification dell'umore, niente premi o colpevolizzazione, cancellazione
   facile quanto l'attivazione.
5. **Onestà sui limiti**: Moody dice quando non sa o non può, e rimanda a persone reali.
6. **Equità linguistica**: test con accenti e dialetti diversi; se lo STT sbaglia spesso con una persona,
   la soluzione è migliorare il modello o offrire alternative, non chiedere alla persona di "parlare meglio".

---

## 7. Schema di DPIA

Uno schema minimo da completare con il DPO (ispirato alle linee guida WP248 e al software PIA della CNIL):

1. **Descrizione del trattamento**: finalità (benessere, promemoria, informazioni, escalation), contesto
   (casa/struttura), interessati (residenti, eventualmente visitatori che parlano vicino al dispositivo), architettura
   ([00-architettura.md](00-architettura.md)), flussi (dispositivo → gateway → STT → brain → tool → TTS).
2. **Dati e retention**: tabella della sezione 2 di questo documento, adattata alla configurazione reale.
3. **Necessità e proporzionalità**: perché un assistente vocale; alternative meno invasive valutate; minimizzazione
   (wake word locale, niente fotocamera, niente memoria); basi giuridiche; informativa; diritti (sezione 4).
4. **Rischi per gli interessati**: accesso illegittimo, modifica indesiderata (azioni domotiche), perdita di dati,
   ascolto non voluto, risposte inappropriate a persone fragili, falsa sensazione di sicurezza (scambiare Moody per un
   sistema di emergenza), esclusione di chi rifiuta.
5. **Misure**: [07](07-sicurezza-home.md), [08](08-sicurezza-enterprise.md), guardrail, policy dei tool, formazione,
   procedure di ciclo di vita.
6. **Rischio residuo e piano d'azione**: cosa resta (es. falsi negativi nel riconoscimento delle crisi), chi lo
   monitora, quando si rivede.
7. **Parere del DPO e, se opportuno, degli interessati o dei loro rappresentanti** (comitato residenti, familiari).
8. **Revisione**: a ogni cambio di modello, di funzionalità o di contesto; almeno annuale.

---

**Prossimo passo →** [10 · Licenze e scelte consapevoli (MIT)](10-licenze.md)
