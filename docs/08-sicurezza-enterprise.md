# 08 · Sicurezza in ambito enterprise (senior living, dispositivi ai residenti)

Questa guida riguarda l'adozione di Moody in una **struttura**: residenze per anziani, senior living,
RSA, co-housing assistito, dove i dispositivi vengono **consegnati ai residenti** e gestiti da un'organizzazione.
Il contesto cambia molto rispetto a casa: persone potenzialmente vulnerabili, dati relativi al benessere
(categoria particolare ex art. 9 GDPR), molti dispositivi, personale che ruota, obblighi legali e
contrattuali. Le misure di [07-sicurezza-home.md](07-sicurezza-home.md) restano tutte valide: qui si
aggiungono governance, processi e scala.

> ⚠️ **Attenzione**: Moody **non è** un sistema di chiamata infermieristica, **non è** un sistema di
> allarme sociale certificato (famiglia EN 50134) e **non è** un dispositivo medico. Non deve sostituire
> campanelli di chiamata, telesoccorso o dispositivi certificati già presenti in struttura. Va presentato,
> contrattualizzato e documentato come **assistente di benessere** complementare.

---

## 1. Governance

### 1.1 Ruoli privacy

| Ruolo | Chi, tipicamente | Responsabilità per Moody |
|-------|------------------|--------------------------|
| **Titolare del trattamento** | l'ente gestore della struttura | decide finalità e mezzi, approva la DPIA, risponde ai residenti |
| **Responsabile del trattamento** (art. 28) | eventuale fornitore che installa/gestisce il server | contratto di nomina (DPA), istruzioni documentate, sub-responsabili autorizzati |
| **DPO** | interno o esterno | parere sulla DPIA, punto di contatto, verifica periodica |
| **Persone autorizzate** (art. 29) | staff tecnico, coordinatori | accesso minimo necessario, formazione, riservatezza |

Poiché Moody gira **interamente on-premise** e non usa cloud, la catena di responsabili può essere molto corta.
Se un fornitore gestisce il server da remoto, va nominato responsabile e l'accesso deve passare da VPN con MFA.

### 1.2 Documentazione obbligatoria

- **DPIA (art. 35)**: obbligatoria. Ricorrono più criteri delle linee guida WP248: interessati vulnerabili,
  dati relativi alla salute/benessere, tecnologia innovativa (AI), monitoraggio sistematico potenziale.
  Uno schema di DPIA è in [09-privacy-by-design.md](09-privacy-by-design.md#7-schema-di-dpia).
- **Registro dei trattamenti (ROPA, art. 30)**: aggiungi la voce "Assistente vocale di benessere Moody"
  con categorie di dati, retention (`MOODY_RETENTION_DAYS`), misure di sicurezza (questo documento).
- **Informativa (artt. 13-14)** in formato *easy-read* + **modulo di consenso esplicito** per il diario
  dell'umore (art. 9.2.a).
- **Valutazione AI Act**: dichiarazione di trasparenza (il sistema dichiara di essere un'AI), verifica che
  non venga usato per riconoscimento delle emozioni o valutazione del personale (vedi
  [09-privacy-by-design.md](09-privacy-by-design.md#5-eu-ai-act)).
- **Intended purpose** scritto e firmato: "assistente di benessere non medico".

---

## 2. Onboarding del residente e consenso informato

1. **Presentazione dal vivo**, con il dispositivo in mano: cosa fa, cosa non fa, come si spegne il microfono
   (tasto mute), che cosa succede dopo "Hi ESP", che non c'è fotocamera.
2. **Valutazione della capacità** di comprendere e decidere, secondo le procedure già in uso in struttura.
   Se la persona non è in grado, il consenso coinvolge chi ne ha titolo (tutore, **amministratore di sostegno**
   con poteri adeguati) e la persona viene comunque informata e ascoltata nella misura possibile.
3. **Consenso granulare**:
   - uso dell'assistente (conversazione, informazioni sulle attività, promemoria);
   - diario dell'umore (dato di categoria particolare → consenso esplicito separato);
   - escalation automatica allo staff in caso di frasi di emergenza/crisi (`MOODY_ESCALATION=auto`).
4. **Diritto di dire no**: rifiutare Moody, o una sua funzione, **non deve comportare alcuna riduzione
   dei servizi** di assistenza. Va scritto nell'informativa.
5. **Revoca in ogni momento**, anche a voce ("cancella i miei dati") o tramite lo staff.
6. **Revisione periodica** (es. ogni 6 mesi o al cambiare delle condizioni): la persona vuole ancora il dispositivo?

> 💡 **Suggerimento**: prepara una scheda A4 a caratteri grandi, con pittogrammi, da lasciare in camera:
> "Moody ascolta solo dopo *Hi ESP* o se tocchi lo schermo · Tasto rosso = microfono spento ·
> Non chiama il 112 · Per emergenze usa il campanello".

---

## 3. Pseudonimi e inventario

Moody non conosce i nomi. L'architettura lo impone:

- in `deploy/config/devices.yaml` ogni dispositivo ha un `subject` **pseudonimo** (`res-001`, …);
- la tabella **pseudonimo ↔ persona/camera** vive **fuori da Moody**, nel sistema gestionale/clinico della
  struttura, accessibile solo a chi ne ha bisogno;
- le notifiche di aiuto via ntfy contengono **solo** lo pseudonimo e un motivo breve
  (`request_help` in `server/moody/wellbeing_mcp/server.py`): lo staff risale alla camera dal proprio sistema.

Inventario asset consigliato (foglio o CMDB), **senza dati personali**:

| Asset tag | CN dispositivo | Seriale cert | Scadenza cert | Firmware | Pseudonimo | Stato |
|-----------|----------------|--------------|---------------|----------|------------|-------|
| MDY-0042 | moody-a1b2c3 | 3F9A…C1 | 2027-11-25 | 0.1.0-release | res-017 | assegnato |

Il seriale e la scadenza si leggono da `deploy/pki/issued.csv`, che `moody.pki sign-csr` aggiorna a ogni firma.

---

## 4. Ciclo di vita del dispositivo

```
 magazzino ─► provisioning ─► assegnazione ─► uso ─► (cambio camera / ricovero) ─► ritiro ─► reset ─► magazzino
                 │                                                                      │
                 └── firmware release firmato, CSR, cert, voce in devices.yaml           └── revoca cert + cancellazione dati
```

| Fase | Azioni | Chi |
|------|--------|-----|
| **Provisioning** | postazione dedicata (PC offline o con accesso solo alla CA), flash firmware **release** firmato, `firmware/tools/provision.py` (chiave generata sul dispositivo, CSR firmata dalla device CA), etichetta asset tag | tecnico IT |
| **Assegnazione** | consenso raccolto, aggiunta voce in `devices.yaml` con pseudonimo e `quiet_hours`, consegna con scheda informativa | coordinatore + IT |
| **Cambio camera** | nessuna azione su Moody (lo pseudonimo non contiene la camera): aggiorna solo la mappatura nel gestionale | coordinatore |
| **Ricovero ospedaliero / assenza lunga** | `enabled: false` in `devices.yaml`, dispositivo ritirato e custodito; i promemoria non vengono consegnati | coordinatore |
| **Uscita / decesso** | 1) revoca: `python -m moody.pki revoke <SERIALE>`; 2) cancellazione dati (vedi sotto); 3) factory reset (tocco prolungato 10 s); 4) pulizia e disinfezione; 5) rimozione voce da `devices.yaml` | IT + DPO informato |
| **Dismissione** | factory reset, revoca, smaltimento RAEE | IT |

**Cancellazione dei dati di un residente**:

- con il residente presente: "cancella i miei dati" → Moody chiede conferma (`erase_my_data` è nel livello
  `confirm`) → "sì";
- d'ufficio (uscita, decesso, revoca del consenso tramite staff): attualmente **non esiste ancora** un comando
  di amministrazione dedicato. Procedura temporanea: chiamare il tool `erase_my_data` per lo pseudonimo tramite
  uno script amministrativo che usa un certificato di servizio, oppure, in assenza di altri residenti da
  preservare, cancellare `deploy/data/wellbeing/`. Una CLI di amministrazione è nella roadmap.

> ⚠️ **Attenzione**: il backup segue la stessa retention. Documenta nella DPIA come la cancellazione si
> propaga ai backup (es. rotazione entro N giorni).

---

## 5. PKI su scala

La PKI minimale di `moody.pki` va bene per casa e piccole installazioni. In struttura:

| Requisito | Raccomandazione |
|-----------|-----------------|
| Radice offline | root CA su macchina air-gapped o HSM; online solo CA intermedie *issuing* |
| Emissione automatizzata | [step-ca](https://smallstep.com/docs/step-ca/) (Apache-2.0) con provisioner separati per dispositivi e servizi, oppure un HSM (es. YubiHSM 2) per le chiavi delle CA |
| Certificati brevi | servizi: 30-90 giorni con rinnovo automatico; dispositivi: 1 anno (default `--days 365`) o meno con rinnovo OTA (roadmap) |
| Separazione dei compiti | chi gestisce la CA non è chi gestisce il server; due persone per operazioni sulla root |
| Revoca | `revoked_serials` in `devices.yaml` (già supportato, hot reload); con step-ca valutare CRL/OCSP passivo |
| Due radici | mantenere separati device e service trust anchor, come fa già Moody |

> ℹ️ **Nota**: il gateway verifica i dispositivi contro un file di CA. Se adotti una gerarchia con intermedie,
> configura `MOODY_DEVICE_CA` con la catena appropriata e ripeti i test di connessione
> (vedi [04-pki-identita.md](04-pki-identita.md)).

---

## 6. Rete

- **VLAN IoT dedicata** ai dispositivi Moody (non condivisa con TV, ospiti o altri IoT).
- Wi‑Fi: **WPA3-Personal con PPSK** (una chiave per gruppo/dispositivo, se il tuo vendor lo supporta) oppure,
  meglio, **WPA2/WPA3-Enterprise EAP-TLS** riutilizzando i certificati dei dispositivi. ESP-IDF supporta
  EAP-TLS, ma il firmware Moody 0.1 implementa solo PSK: EAP-TLS è nella roadmap.
- **Client isolation** sull'SSID: i dispositivi non devono vedersi tra loro.
- **NAC / firewall**: la VLAN IoT raggiunge solo il gateway (TCP 8443) e l'NTP interno; nessun accesso a Internet.
- **Rete di gestione** separata per SSH, Keycloak admin, monitoraggio.
- ntfy raggiungibile solo dalla rete/VPN dello staff (tablet o smartphone di reparto).

---

## 7. Identità e accessi: Keycloak

`deploy/compose.enterprise.yaml` aggiunge Keycloak (Apache-2.0) e PostgreSQL:

```bash
./scripts/setup.sh --hostname moody.struttura.lan --ip 10.20.0.5 --enterprise
docker compose -f deploy/compose.yaml -f deploy/compose.enterprise.yaml up -d
```

Cosa cambia:

| Flusso | Prima (home) | Con enterprise |
|--------|--------------|----------------|
| gateway → brain | mTLS (service CA) | mTLS **+** token OIDC *client credentials* del client `moody-gateway`, audience `moody-brain`, durata 5 minuti |
| verifica nel brain | — | firma JWKS, `iss`, `aud`, `exp`, `azp ∈ MOODY_OIDC_ALLOWED_CLIENTS` (`server/moody/brain/auth.py`) |
| escalation | `ask` | `MOODY_ESCALATION=auto` di default: frasi di crisi notificano subito lo staff |

Raccomandazioni:

- console di amministrazione **solo tramite tunnel SSH** (`127.0.0.1:8444`, come nel compose):
  `ssh -L 8444:127.0.0.1:8444 utente@server` e poi `https://keycloak:8444` (mappa `keycloak` su `127.0.0.1` nel file hosts);
- **MFA (TOTP) obbligatoria** per gli account dello staff (il realm imposta già la policy OTP e una password policy);
- usa i ruoli predefiniti nel realm: `moody-operator` (gestione dispositivi, per una futura UI di amministrazione)
  e `moody-dpo` (accesso agli audit log); il codice 0.1 non espone ancora un'interfaccia che li usi;
- ruota `MOODY_GATEWAY_CLIENT_SECRET` periodicamente (aggiorna sia `deploy/.env` sia `deploy/secrets/gateway_client_secret`);
- federazione con l'IdP aziendale (LDAP/AD, SAML) possibile da Keycloak se la struttura ne ha uno.

---

## 8. Politica di escalation

| Evento | Comportamento di Moody | Requisito organizzativo |
|--------|------------------------|-------------------------|
| Frase di **emergenza** ("sono caduto", "dolore al petto") | risposta fissa che invita a chiamare il 112 + `request_help` con urgenza alta, **sempre** | qualcuno deve ricevere la notifica 24/7 |
| Frase di **crisi** (autolesionismo) | risposta fissa (112, Telefono Amico); con `auto` notifica subito, con `ask` chiede prima | protocollo clinico interno per la presa in carico |
| Richiesta esplicita di aiuto | tool `request_help` (policy `allow`) | idem |

Le notifiche passano da ntfy (`deploy/config/ntfy/server.yml`, `auth-default-access: deny-all`):
crea un utente in sola lettura per il dispositivo di reparto con `scripts/ntfy-setup.sh <utente>`.

> ⚠️ **Attenzione**: ntfy non garantisce la consegna come un sistema di chiamata certificato (rete, batteria,
> app chiusa). Il riconoscimento delle frasi è basato su regole e può fallire (falsi negativi e positivi).
> Il campanello di chiamata e le procedure esistenti restano il canale primario.

---

## 9. Formazione dello staff

- Cos'è e cosa non è Moody; limiti dei guardrail; nessuna diagnosi.
- Come rispondere a una notifica ntfy e come risalire alla persona dallo pseudonimo.
- Rispetto della privacy: lo staff **non** può chiedere a Moody cosa ha detto un residente (e Moody non lo sa:
  non conserva le conversazioni).
- Procedure di ciclo di vita (sezione 4), dispositivo smarrito, segnalazione incidenti.
- Pulizia del dispositivo: panno con alcol isopropilico 70%, mai spruzzare direttamente.

---

## 10. Logging e monitoraggio

I servizi emettono log JSON su stdout, già passati dal redattore PII. Eventi di audit presenti nel codice:

| Evento | Servizio | Significato |
|--------|----------|-------------|
| `device_connected` / `device_disconnected` | gateway | connessione di un dispositivo autorizzato |
| `device_rejected` | gateway | certificato sconosciuto, disabilitato o revocato (`reason`) |
| `device_duplicate_connection` | gateway | stesso dispositivo connesso due volte: possibile clonazione |
| `protocol_error` | gateway | messaggio non conforme al protocollo |
| `turn_completed` | gateway | turno vocale completato (categoria, latenza; **nessun testo**) |
| `safety_escalation` | brain | crisi o emergenza rilevata |
| `input_blocked` | brain | prompt injection o blocco del guard model |
| `tool_called` / `tool_confirmation_requested` / `tool_confirmed` | brain | uso dei tool |
| `mood_checkin`, `reminder_set`, `erase_subject`, `help_requested` | wellbeing | operazioni sui dati del benessere |

Raccomandazioni:

- inoltra i log a un SIEM o a uno stack di log self-hosted (es. Loki/Vector, rispettando le licenze:
  vedi [10-licenze.md](10-licenze.md)) usando il driver di logging Docker o un collector;
- **alert** su: picchi di `device_rejected`, qualunque `device_duplicate_connection`, `safety_escalation`
  (verifica che la notifica sia stata presa in carico), errori ripetuti del pipeline;
- **retention dei log** definita nella DPIA (es. 90 giorni) e accesso limitato al ruolo DPO/sicurezza;
- `MOODY_LOG_TRANSCRIPTS` deve restare `false` in produzione: abilitarlo è un nuovo trattamento da valutare.

---

## 11. Gestione degli incidenti e data breach

1. **Rileva e contieni**: revoca certificati, disabilita dispositivi, isola il server dalla rete se necessario.
2. **Valuta**: quali dati, quante persone, cifrati o no (il diario è cifrato; la chiave era compromessa?).
3. **Notifica al Garante entro 72 ore** (art. 33) se c'è rischio per i diritti degli interessati.
4. **Comunica agli interessati** (art. 34) se il rischio è elevato, con linguaggio comprensibile.
5. **Documenta** nel registro delle violazioni anche gli incidenti non notificati.
6. **Post-mortem**: correzione, aggiornamento della DPIA, nuovo red teaming.

---

## 12. Gestione delle vulnerabilità

- **Immagini pinnate** in `deploy/.env`; aggiornamenti deliberati dopo lettura dei changelog.
- `pip-audit` sulle dipendenze Python (incluso negli extra `dev` di `server/pyproject.toml`):
  `pip install -e "server[dev]" && pip-audit`.
- **Dependabot** o Renovate sul repository per pip, Docker e GitHub Actions.
- **SBOM** (opzionale): `syft` per generare l'elenco dei componenti delle immagini, `grype` per le CVE.
- Firmware: segui gli advisory di ESP-IDF; rilascia firmware firmati.
- Red teaming prima di ogni release e a ogni cambio di modello ([11-red-teaming.md](11-red-teaming.md)).
- Canale di segnalazione responsabile delle vulnerabilità (vedi `SECURITY.md` del repository).

---

## 13. NIS2 e continuità

- Una struttura sanitaria o socio-sanitaria può rientrare nel perimetro **NIS2** (D.Lgs. 138/2024) come soggetto
  importante o essenziale, a seconda di settore e dimensioni: verifica con il consulente. Se sì, Moody rientra
  nella gestione del rischio, nella gestione degli incidenti (notifica preliminare entro 24 h al CSIRT) e nella
  sicurezza della supply chain.
- **Alta disponibilità** (note, non implementata in 0.1):
  - il servizio è *best effort* per definizione (non è un sistema salvavita);
  - due server con configurazione identica e dispositivi che puntano a un nome DNS con failover;
  - stato minimo: solo `deploy/data/wellbeing/` (SQLite) va replicato/backuppato;
  - GPU dimensionata per i picchi (es. mattino): backend `openai` verso vLLM con `MOODY_LLM_BACKEND=openai`;
  - UPS e monitoraggio della salute dei container.

---

## 14. Checklist di revisione della sicurezza

**Governance**
- [ ] DPIA approvata con parere del DPO; voce nel ROPA; DPA con eventuali fornitori
- [ ] Informativa easy-read e consenso esplicito separato per il diario dell'umore
- [ ] Intended purpose "non medico" documentato; nessuna sostituzione dei sistemi di chiamata

**Dispositivi**
- [ ] Solo firmware **release** firmato in campo; chiave di firma in custodia controllata
- [ ] Inventario asset senza dati personali; procedure di ciclo di vita scritte e provate
- [ ] Factory reset e revoca eseguiti a ogni ritiro

**PKI e identità**
- [ ] Root offline o HSM; separazione dei compiti; certificati di servizio a breve durata
- [ ] Keycloak con MFA per lo staff; console solo via tunnel SSH; segreti ruotati

**Rete e server**
- [ ] VLAN IoT dedicata, client isolation, nessun accesso Internet dai dispositivi
- [ ] Runtime dei container senza Internet; firewall host e `DOCKER-USER`
- [ ] Disco cifrato, patch automatiche, accesso remoto solo via VPN + MFA

**Operatività**
- [ ] Escalation `auto` con ricezione notifiche 24/7 verificata periodicamente (test mensile)
- [ ] Log centralizzati, alert configurati, retention definita, `MOODY_LOG_TRANSCRIPTS=false`
- [ ] Procedura data breach 72 h e, se applicabile, NIS2 24 h
- [ ] pip-audit/Dependabot attivi; red teaming eseguito e archiviato a ogni release
- [ ] Staff formato; scheda informativa in ogni camera

---

**Prossimo passo →** [09 · Privacy by design](09-privacy-by-design.md)
