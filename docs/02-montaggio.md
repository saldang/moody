# 02 · Montaggio

Come assemblare il dispositivo ESP32-S3-BOX-3 e preparare il server e la rete: dalla scatola alla
collocazione in casa o in camera. Il montaggio fisico richiede pochi minuti. La parte importante è
**dove** e **come** collocare il dispositivo, perché è un oggetto con microfoni nello spazio
privato di una persona. Collocazione, mute hardware ed etichettatura senza nomi fanno parte delle
misure di privacy, non sono dettagli estetici.

## Prerequisiti

- Il materiale della [lista della spesa](01-acquisto.md).
- Un cacciavite a croce piccolo (solo se usi un involucro o supporto avvitato).
- Per l'enterprise: la planimetria con la copertura Wi-Fi della VLAN IoT.

---

## Parte A: il dispositivo ESP32-S3-BOX-3

### 1. Apertura della confezione e verifica

1. Controlla il contenuto: unità principale BOX-3 (display, microfoni, speaker), **BOX-3-DOCK**,
   eventuali accessori (bracket, cavi).
2. Verifica che non ci siano segni di manomissione (sigilli, viti graffiate). In ambito enterprise
   annota il lotto e il numero di serie nel registro asset, **mai** associato al nome di un
   residente in questo registro tecnico.
3. Se nella confezione trovi la scheda **BOX-3-SENSOR** (radar e sensori ambientali), **non
   montarla**: Moody non usa il rilevamento di presenza e movimento. Motivazioni in
   [01-acquisto.md](01-acquisto.md#perché-lesp32-s3-box-3-e-non-il-dispositivo-originale).

### 2. Aggancio al dock

1. Allinea il connettore PCIe-style sul retro dell'unità principale con lo slot del **BOX-3-DOCK**.
2. Spingi con decisione finché l'unità non è ben in sede. Non deve oscillare.
3. Il dock fornisce la porta USB-C di alimentazione e dati e la base d'appoggio.

### 3. Collegamento USB-C

- **Per flash e provisioning** usa il cavo **dati** collegato al PC
  (vedi [05-setup-device.md](05-setup-device.md)).
- **Per l'uso quotidiano** usa l'alimentatore 5 V / 2 A. Il dispositivo si accende appena riceve
  alimentazione.

> 💡 **Suggerimento:** se dopo la connessione al PC non compare alcuna porta seriale
> (`/dev/ttyACM0` su Linux, `/dev/cu.usbmodem*` su macOS), quasi sempre il problema è il cavo,
> che porta solo l'alimentazione.

### 4. Verifica del pulsante mute hardware

Il BOX-3 ha un **pulsante mute** sul lato superiore che disattiva i microfoni a livello hardware.

1. Premi il pulsante: deve accendersi l'**indicatore rosso**.
2. Con il mute attivo, prova a dire "Hi ESP" (dopo il setup del firmware): il dispositivo **non**
   deve reagire.
3. Premi di nuovo per riattivare i microfoni.

> ⚠️ **Attenzione:** mostra questo pulsante alla persona che userà il dispositivo e spiegale che
> con la luce rossa *nessun suono può essere ascoltato*, nemmeno se il software avesse un difetto.
> È la garanzia di privacy più comprensibile che possiamo offrire.

### 5. Collocazione

| Regola | Perché |
|---|---|
| Altezza tra **80 e 150 cm** (comodino, mensola, scrivania) | Il display va visto e toccato da seduti o da sdraiati, i microfoni vanno lasciati liberi |
| Ad almeno **2 m da TV, radio, cappa e lavastoviglie** | Il rumore continuo riduce la precisione della wake word e della trascrizione e causa attivazioni accidentali |
| **Mai in bagno** | È lo spazio più intimo e l'umidità danneggia l'elettronica. Per le emergenze in bagno esistono i campanelli di chiamata dedicati |
| Non rivolto verso la finestra o verso il letto di un'altra persona (camere doppie) | Rispetto della privacy di terzi |
| Segnale Wi-Fi buono (almeno −67 dBm) sulla **rete IoT** | Connessioni instabili significano risposte interrotte |
| Lontano da fonti di calore e dalla luce solare diretta | Durata della batteria tampone e del display, leggibilità |
| Presa elettrica vicina, senza prolunghe volanti | Sicurezza (inciampo) |

---

## Parte B: specifiche enterprise (senior living)

### 6. Supporto fisso o involucro

- Usa un **supporto o involucro stampato in 3D in PETG** con bordi arrotondati, fissato al mobile
  con viti o biadesivo strutturale. Riduce cadute, urti e spostamenti.
- Lascia **liberi** i fori dei microfoni, la griglia dello speaker, il pulsante mute e la porta
  USB-C.
- L'involucro **non deve coprire** l'indicatore rosso del mute.

### 7. Gestione dei cavi (anti-inciampo)

1. Fai passare il cavo lungo il bordo del mobile e fissalo con fermacavi adesivi.
2. Il cavo non deve **mai** attraversare le zone di passaggio, in particolare tra letto e bagno.
3. Se possibile usa prese a muro dietro il mobile e raccogli il cavo in eccesso con una fascetta.

### 8. Etichettatura: asset tag sì, nomi mai

- Applica sotto la base un'**etichetta asset tag** con QR e ID tecnico del dispositivo
  (es. `moody-a1b2c3`, lo stesso CN del certificato).
- **Non scrivere mai** sul dispositivo o sull'etichetta il nome del residente, il numero di camera
  o informazioni sanitarie.
- L'associazione *ID dispositivo → pseudonimo (`res-001`)* sta in `deploy/config/devices.yaml`.
  L'associazione *pseudonimo → persona/camera* sta **solo** nel sistema gestionale della
  struttura, fuori da Moody (vedi [08-sicurezza-enterprise.md](08-sicurezza-enterprise.md)).

### 9. Igiene e pulizia

1. Scollega l'alimentazione.
2. Inumidisci un panno in microfibra con **alcol isopropilico al 70%**.
3. Passa il panno su display, scocca e supporto, senza far entrare liquido nei fori.
4. **Non spruzzare mai** prodotti direttamente sul dispositivo e non usare candeggina o solventi
   aggressivi.
5. Lascia asciugare 2 minuti prima di ricollegare.

Quando un residente lascia la struttura: **reset di fabbrica** (tieni premuto lo schermo per 10
secondi: credenziali e certificato vengono cancellati e il dispositivo torna in modalità
provisioning), **revoca del certificato**, sanificazione, poi nuovo provisioning. Procedura completa
in [08-sicurezza-enterprise.md](08-sicurezza-enterprise.md).

### 10. Accessibilità

- **Tocco per parlare:** chi ha difficoltà a pronunciare "Hi ESP" (afasia, accento marcato, voce
  debole) può **toccare lo schermo** per iniziare l'ascolto. Mostra questo gesto durante la
  consegna.
- Il display usa **caratteri grandi e alto contrasto**. Posiziona il dispositivo in modo che lo
  schermo non abbia riflessi.
- Per le persone ipovedenti contano soprattutto la voce e il segnale dello stato. Regola il volume
  insieme alla persona durante la consegna.
- Consegna una **scheda cartacea** con caratteri grandi: come si parla con Moody, come si usa il
  mute, cosa Moody *non* è (non sostituisce il campanello di chiamata né il 112).

---

## Parte C: server e rete

### 11. Montaggio del server

1. **Casa:** posiziona il mini PC in un luogo ventilato, non chiuso in un mobile senza aria.
   Collegalo all'UPS se ne hai uno.
2. **Struttura:** monta il server in rack in un locale tecnico chiuso a chiave e collegato all'UPS
   con la scheda di rete (arresto automatico). Usa entrambi gli alimentatori su linee diverse,
   se disponibili.
3. Collega il server via **cavo Ethernet** (non Wi-Fi) alla porta dello switch o del router che
   porterai sulla VLAN server.

### 12. Impostazioni BIOS/UEFI

| Impostazione | Valore | Perché |
|---|---|---|
| TPM 2.0 (fTPM/PTT) | **Abilitato** | Sblocco automatico della cifratura disco legato all'hardware (vedi [03-setup-ambiente.md](03-setup-ambiente.md)) |
| Secure Boot | **Abilitato** | Avvio solo di bootloader firmati (Debian e Ubuntu sono supportati) |
| Password amministratore BIOS | **Impostata** | Impedisce di disattivare Secure Boot o di avviare da USB |
| Avvio da USB/rete | Disabilitato dopo l'installazione | Riduce gli attacchi fisici |
| Wake-on-LAN | **Disabilitato** | Non serve e allarga la superficie d'attacco |
| Porte inutilizzate (seriale, Thunderbolt se non usato) | Disabilitate | Superficie d'attacco minima |
| Ripristino dopo blackout | "Power on" / "Last state" | Il server riparte da solo dopo un'interruzione di corrente |

### 13. Rete: VLAN e SSID per l'IoT

Configura sul router/AP (casa) o su switch e controller Wi-Fi (struttura):

| Rete | Chi c'è | Accesso |
|---|---|---|
| **LAN principale / Admin** | PC, telefoni, amministratore | Può raggiungere il server via SSH (22) e ntfy (8088) |
| **VLAN IoT** (SSID dedicato, es. `casa-iot`) | dispositivi Moody | Può raggiungere **solo** `server:8443`. Niente Internet, niente LAN |
| **VLAN server** (opzionale in casa) | server Moody | Riceve 8443 dalla IoT, 22 dall'admin |

1. Crea l'SSID IoT con **WPA3-Personal** (o WPA2/WPA3 misto se il router non supporta solo WPA3) e
   una password lunga e casuale. In una struttura preferisci **PPSK** (una chiave per dispositivo)
   o 802.1X.
2. Abilita l'**isolamento dei client** sull'SSID IoT: i dispositivi non devono parlarsi tra loro.
3. Blocca l'uscita verso Internet della VLAN IoT. Il firmware di Moody parla solo con il gateway.
4. Prenota un IP statico (DHCP reservation) per il server e crea il nome DNS `moody.lan`
   (dettagli in [03-setup-ambiente.md](03-setup-ambiente.md)).

Le regole firewall complete, per casa ed enterprise, sono in [07-sicurezza-home.md](07-sicurezza-home.md)
e [08-sicurezza-enterprise.md](08-sicurezza-enterprise.md).

---

Prossimo passo → [03 · Setup dell'ambiente server](03-setup-ambiente.md)
