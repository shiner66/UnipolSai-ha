# Changelog — UnipolSai Telematica

Tutte le modifiche significative a questo progetto vengono documentate qui.
Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/)
e il versioning segue [Semantic Versioning](https://semver.org/lang/it/).

---

## [1.5.3] — 2026-09-30

### Corretto
- Sostituito il server pubblico `tile.openstreetmap.org`, che può rifiutare le
  richieste del frontend Home Assistant con `403` per la propria tile usage
  policy, con lo stile vettoriale Liberty di OpenFreeMap: nessuna API key e
  nomi delle strade visibili. MapLibre GL JS 5.24.0 e l'adapter Leaflet 0.1.4
  sono inclusi nell'integrazione, senza dipendenze CDN. Se OpenFreeMap non
  completa il caricamento, la card passa automaticamente a OpenTopoMap.
- Eliminata una race condition all'avvio che poteva ricaricare dallo storage
  una vecchia risorsa Lovelace e lasciare attiva la card con le tile CARTO.
- La registrazione della card rimuove ora tutte le versioni obsolete e gli
  eventuali duplicati, mantenendo una sola risorsa per la versione corrente.

---

## [1.5.2] — 2026-09-30

### Corretto
- Sostituito l'endpoint CARTO che mostrava `API KEY REQUIRED` con le tile
  standard OpenStreetMap: nessuna chiave richiesta, nomi di strade e località
  visibili e attribuzione corretta.
- La mappa valida ora coordinate e configurazione, rimuove i marker obsoleti,
  libera le istanze Leaflet quando la card viene rimossa o riconfigurata e non
  annulla più pan e zoom dell'utente a ogni aggiornamento di Home Assistant.
- Sanitizzati nomi veicolo, targhe e indirizzi prima di inserirli nei popup e
  nel pannello; il pulsante GPS viene disabilitato anche a crediti esauriti.
- I binary sensor per auto spostata e uscita dalla zona ora segnalano davvero
  il nuovo evento per un ciclo di aggiornamento, senza falsi positivi al riavvio.
- Ripristinato il menu Opzioni sulle versioni Home Assistant 2025.12 e
  successive; la modifica dell'intervallo di scansione ricarica ora l'entry.
- Il periodo impostato con `set_usages_period` resta attivo nei poll successivi.
- Il reverse geocoding aggiorna subito i listener anche dopo un fix GPS live,
  accetta coordinate pari a zero e non invia più la targa nel `User-Agent`;
  rimossi inoltre chiave contratto e numero polizza dai log.
- Le richieste GPS live vengono serializzate e il pulsante si disabilita subito,
  evitando che un doppio click consumi più crediti per lo stesso aggiornamento.
- Le date di scadenza e prossima rata vengono normalizzate in valori `date`
  validi per Home Assistant; corretti anche i link mappa con coordinate zero.

### Modificato
- Riutilizzata la sessione HTTP condivisa di Home Assistant e chiusi in modo
  ordinato i task di polling/geocoding durante l'unload.
- Registrazione della card compatibile sia con la vecchia API static path sia
  con `StaticPathConfig`; rimossa dal manifest la chiave non valida
  `homeassistant` (la versione minima resta dichiarata in `hacs.json`).
- Il setup ripulisce coordinator e task se il caricamento delle piattaforme
  fallisce o viene annullato; la card attende ora il frontend, così le
  installazioni headless possono continuare a usare sensori e servizi.

---

## [1.5.1] — 2026-03-27

### Corretto
- **"Custom element not found"** al primo caricamento dopo restart di HA:
  la card viene ora registrata come risorsa Lovelace nativa (stesso meccanismo
  di HACS) invece di affidarsi solo a `add_extra_js_url`. Lovelace attende il
  caricamento di tutte le risorse prima di renderizzare i pannelli, eliminando
  il race condition. `add_extra_js_url` rimane come fallback per la modalità
  YAML.
- Pulizia automatica delle risorse Lovelace obsolete alla versione precedente
  al momento dell'aggiornamento dell'integrazione.

---

## [1.5.0] — 2026-03-23

### Aggiunto
- **Lovelace card**: supporto lista veicoli con nome tramite il nuovo parametro
  `vehicles` (array di `{targa, name}`). Backward-compat: `targa` singola e
  auto-discovery continuano a funzionare invariati.
- **Nomi veicoli** mostrati in grassetto nell'intestazione del pannello e nel
  popup della mappa. La targa diventa badge secondario affiancato al nome.
- **Tile layer CartoDB Voyager** al posto di OpenStreetMap standard: mappa più
  moderna e leggera.
- **Angoli arrotondati** sul contenitore della mappa (`border-radius: 12px`).
- **Popup Leaflet moderno**: shadow, niente bordo brutto, tipografia pulita.

### Modificato
- `manifest.json`, `__init__.py`, JS: versione bump `1.4.0` → `1.5.0`.
- `__init__.py`: `_VERSION` allineato al JS — cambia l'URL del resource statico,
  forza il browser a ricaricare il file JS aggiornato invece di usare la cache.
- `services.yaml`: `step: 0.000001` → `step: any` per latitudine/longitudine
  (fix warning HA su versioni recenti).
- `README.md`: documentata la configurazione `vehicles`, tabella parametri
  completa, aggiornati riferimenti al tile layer CartoDB.

---

## [1.4.0] — 2026-03-23

### Aggiunto
- **Lovelace custom card** `unipolsai-vehicle-card`: scheda dinamica con mappa
  interattiva OpenStreetMap/Leaflet che mostra la posizione di ogni veicolo.
  - Supporto **multi-veicolo**: se `targa` non è configurata, la card rileva
    automaticamente tutti i veicoli UnipolSai installati.
  - **Marker colorato** sul veicolo: verde = fermo, blu = in movimento,
    arancione = aggiornamento GPS in corso.
  - **Chip informativo** con crediti Car Finder rimanenti (es. `3/5 crediti`)
    con indicazione visiva gialla/rossa quando si esauriscono.
  - **Chip ultimo aggiornamento GPS** con data/ora in formato italiano.
  - **Chip velocità** istantanea (km/h).
  - **Pulsante "Aggiorna posizione GPS"** integrato nella card: invia
    direttamente la richiesta live alla scatola nera (consuma 1 credito).
    Disabilitato automaticamente quando un aggiornamento è già in corso o
    i crediti sono esauriti.
  - Click sull'intestazione del veicolo → centra la mappa e apre il popup.
  - Configurazione minima: `type: custom:unipolsai-vehicle-card` (zero config).
  - Parametri opzionali: `targa`, `zoom` (default 15), `height` (default 300 px).
- **Auto-inject nel frontend**: la card è parte dell'integrazione e viene
  caricata automaticamente da HA via `frontend.add_extra_js_url`. Nessuna
  risorsa Lovelace da aggiungere manualmente — basta riavviare HA e fare
  hard refresh del browser.

### Modificato
- `__init__.py`: aggiunto `async_setup` per registrare il percorso statico HTTP
  della card Lovelace al caricamento del dominio.
- `manifest.json`: versione bump `1.3.1` → `1.4.0`.
- `README.md`: aggiunta sezione completa **Lovelace Card** con istruzioni,
  esempi YAML e screenshot della scheda.

---

## [1.3.1] — 2026-03

### Corretto
- **Sensori contratto**: implementato il flusso corretto in 3 step:
  1. `GET /contesto-utente/v2/me/polizze` → `chiaveContratto` + metadati polizza
  2. `POST /contratti/v2/polizze/titolo/recuperoTitoli` → `timbroEffettivoPagamento`
  3. `GET /contratti/v4/polizze/{chiave}` con tutti i query params necessari
- Risolto il mancato caricamento dei sensori numero polizza, scadenza,
  prossima rata e premio annuo.

---

## [1.3.0] — 2026-03

### Aggiunto
- Sensori contratto assicurativo: numero polizza, scadenza, prossima rata,
  premio annuo lordo.
- Servizio `unipolsai.set_usages_period` per statistiche su periodo custom.
- Sensori statistiche di guida: distanza totale, ore di guida, km città,
  extraurbano, autostrada, notturni.

---

## [1.2.0]

### Aggiunto
- Servizi `unipolsai.set_target_area` e `unipolsai.disable_target_area`.
- Servizio `unipolsai.set_speed_limit`.
- Sensori target area: stato zona e raggio.
- Binary sensor `auto_uscita_dalla_zona`.

---

## [1.1.0]

### Aggiunto
- Geocodifica inversa via Nominatim (OpenStreetMap): sensore `indirizzo`.
- Binary sensor `auto_spostata_a_motore_spento` (anti-furto).
- Supporto più veicoli: ogni entry è indipendente.

---

## [1.0.0]

### Prima versione
- `device_tracker` con posizione GPS.
- Sensori: velocità, posizione, direzione, ultimo aggiornamento GPS,
  crediti Car Finder.
- `button.aggiorna_posizione_gps` — fix live (consuma 1 credito).
- Binary sensor `aggiornamento_gps_in_corso`.
- Polling configurabile (1–60 min), fast-polling durante richieste live.
- Token JWT con auto-refresh.
