# UnipolSai Telematica — Home Assistant Custom Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/shiner66/UnipolSai-ha.svg)](https://github.com/shiner66/UnipolSai-ha/releases)
[![Changelog](https://img.shields.io/badge/Changelog-CHANGELOG.md-blue.svg)](CHANGELOG.md)

Integrazione non ufficiale per Home Assistant che espone i dati della scatola nera **UnipolSai Unibox** come entità native.

> **Disclaimer:** Questa è un'integrazione non ufficiale, sviluppata tramite analisi del traffico dell'app mobile UnipolSai. Non è affiliata né approvata da UnipolSai S.p.A. Usala a tua discrezione e nel rispetto dei Termini di Servizio di UnipolSai.

---

## Funzionalità

### Sensori GPS
| Entità | Descrizione |
|--------|-------------|
| `device_tracker` | Posizione GPS su mappa |
| `sensor.velocita` | Velocità istantanea (km/h) |
| `sensor.indirizzo` | Indirizzo leggibile (OpenStreetMap) |
| `sensor.posizione` | Codice strada dall'API |
| `sensor.direzione` | Direzione di marcia |
| `sensor.ultimo_aggiornamento_gps` | Timestamp ultimo fix GPS |
| `sensor.crediti_car_finder` | Crediti richieste GPS live rimanenti oggi |

### Controllo veicolo
| Entità | Descrizione |
|--------|-------------|
| `button.aggiorna_posizione_gps` | Fix GPS in tempo reale (consuma 1 credito) |
| `sensor.limite_velocita` | Limite velocità impostato (km/h) |
| `sensor.zona_consentita` | Stato target area (attiva/disattivata) |
| `sensor.raggio_zona` | Raggio zona consentita (m) |

### Notifiche e allarmi
| Entità | Descrizione |
|--------|-------------|
| `binary_sensor.aggiornamento_gps_in_corso` | ON mentre la scatola elabora un fix live |
| `binary_sensor.auto_spostata_a_motore_spento` | ON su nuovo evento anti-furto |
| `binary_sensor.auto_uscita_dalla_zona` | ON quando l'auto esce dalla target area |

### Statistiche di guida (periodo contrattuale)
| Entità | Descrizione |
|--------|-------------|
| `sensor.distanza_totale` | Km totali percorsi |
| `sensor.tempo_di_guida_totale` | Ore di guida totali |
| `sensor.km_citta` | Km percorsi in città |
| `sensor.km_extraurbano` | Km percorsi in extraurbano |
| `sensor.km_autostrada` | Km percorsi in autostrada |
| `sensor.km_notturni` | Km percorsi di notte |

### Contratto assicurativo
| Entità | Descrizione |
|--------|-------------|
| `sensor.numero_polizza` | Numero contratto assicurativo |
| `sensor.scadenza_polizza` | Data scadenza polizza |
| `sensor.premio_annuo_lordo` | Premio annuo + dettaglio per garanzia |
| `sensor.prossima_rata` | Data prossima rata |

---

## Lovelace Card — Mappa veicoli

L'integrazione include una **scheda Lovelace personalizzata** che mostra in un'unica vista:

- 🗺️ **Mappa interattiva** (CartoDB Voyager) con marker per ogni veicolo
- 🏷️ **Nome personalizzato** per ciascun veicolo (opzionale)
- 🔋 **Crediti Car Finder rimanenti** oggi (es. `3/5 crediti`)
- 🕐 **Timestamp ultimo aggiornamento GPS**
- 🚗 **Velocità istantanea**
- 🔄 **Pulsante "Aggiorna posizione GPS"** integrato per ogni veicolo
- Supporto **più veicoli** sullo stesso pannello

### Installazione della card

La card è **parte dell'integrazione** e si attiva automaticamente al riavvio di Home Assistant dopo l'installazione. Non è necessario aggiungere risorse manualmente né scaricare file separati.

Dopo il riavvio, esegui un **hard refresh** del browser (Ctrl+Shift+R su desktop, oppure svuota la cache su iOS Safari) per caricare il nuovo modulo JS.

### Configurazione YAML della card

#### Auto-discovery — rileva tutti i veicoli UnipolSai automaticamente
Lascia la configurazione vuota: la card trova e mostra tutti i veicoli registrati nell'integrazione.

```yaml
type: custom:unipolsai-vehicle-card
```

#### Singolo veicolo (backward-compat)
```yaml
type: custom:unipolsai-vehicle-card
targa: AB123CD
```

#### Lista veicoli con nome personalizzato
Il modo consigliato quando hai più veicoli: puoi assegnare un nome leggibile a ciascuno e controllare l'ordine di visualizzazione dei pannelli.

```yaml
type: custom:unipolsai-vehicle-card
vehicles:
  - targa: AB123CD
    name: Auto di Mario
  - targa: GG687PM
    name: Auto di Lucia
```

#### Tutte le opzioni disponibili
```yaml
type: custom:unipolsai-vehicle-card
vehicles:
  - targa: AB123CD
    name: Auto di Mario    # opzionale — se omesso mostra solo la targa
  - targa: GG687PM
    name: Auto di Lucia
zoom: 15                   # livello di zoom iniziale della mappa (default: 15)
height: 350                # altezza della mappa in pixel (default: 300)
```

### Parametri di configurazione

| Parametro | Tipo | Default | Descrizione |
|-----------|------|---------|-------------|
| `vehicles` | lista | — | Lista di veicoli da mostrare (formato consigliato) |
| `vehicles[].targa` | stringa | — | Targa del veicolo (es. `AB123CD`) |
| `vehicles[].name` | stringa | — | Nome leggibile del veicolo (opzionale) |
| `targa` | stringa | — | Singola targa — backward compat, equivale a `vehicles` con un elemento senza nome |
| `zoom` | intero | `15` | Livello di zoom iniziale della mappa (1–20) |
| `height` | intero | `300` | Altezza della mappa in pixel |

> **Priorità config:** `vehicles` > `targa` singola > auto-discovery (se nessuno dei due è impostato)

### Come funziona la card

| Elemento | Descrizione |
|----------|-------------|
| **Marker verde** | Veicolo fermo |
| **Marker blu** | Veicolo in movimento |
| **Marker arancione** | Aggiornamento GPS live in corso |
| **Nome veicolo** (se configurato) | Mostrato in grassetto nell'intestazione del pannello e nel popup della mappa |
| **Badge targa** | Sempre visibile nel pannello, affianca il nome se presente |
| **Chip crediti arancione** | 1 credito rimanente — attenzione |
| **Chip crediti rosso** | Crediti esauriti — il pulsante di aggiornamento è disabilitato |
| **Click sull'intestazione** | Centra la mappa sul veicolo e apre il popup |
| **Pulsante Aggiorna** | Invia richiesta fix GPS live (consuma 1 credito) |
| **Chip "Aggiornamento GPS…"** | Animato, visibile mentre il fix è in elaborazione |

> **Nota:** La mappa richiede connessione internet per caricare le tiles CartoDB Voyager. In reti isolate la mappa potrebbe non essere disponibile.

---

## Installazione

### Via HACS (consigliato)
1. Assicurati di avere [HACS](https://hacs.xyz) installato
2. Vai su **HACS → Integrazioni → ⋮ → Repository personalizzati**
3. Aggiungi l'URL: `https://github.com/shiner66/UnipolSai-ha`
4. Seleziona la categoria **Integration** e clicca **Aggiungi**
5. Cerca "UnipolSai" in HACS e clicca **Scarica**
6. Riavvia Home Assistant
7. Vai su **Impostazioni → Dispositivi e Servizi → Aggiungi integrazione** → cerca "UnipolSai"

### Manuale
1. Copia la cartella `custom_components/unipolsai` nella directory `config/custom_components/` del tuo Home Assistant
2. Riavvia Home Assistant
3. Vai su **Impostazioni → Dispositivi e Servizi → Aggiungi integrazione**
4. Cerca "UnipolSai" e segui la configurazione

---

## Configurazione

Durante il setup inserisci:
- **Email**: la stessa usata per l'app UnipolSai
- **Password**: password dell'app
- **Targa**: targa del veicolo (es. `AB123CD`)
- **Intervallo aggiornamento**: frequenza polling GPS in minuti (default: 5)

### Più veicoli
Ripeti il processo di aggiunta integrazione per ogni veicolo. Ogni auto (anche con credenziali diverse) è configurata come entry indipendente.

### Modifica impostazioni
Dopo il setup, usa il menu ⚙️ dell'integrazione nelle Impostazioni per modificare l'intervallo di polling senza reinstallare.

---

## Servizi Home Assistant

### `unipolsai.set_target_area`
Imposta la zona di monitoraggio. L'auto notifica se esce dal perimetro.
```yaml
service: unipolsai.set_target_area
data:
  targa: AB123CD        # opzionale se hai un solo veicolo
  latitude: 40.5578515
  longitude: 14.9281384
  radius: 500           # metri (100–5000)
```

### `unipolsai.disable_target_area`
Disattiva la zona di monitoraggio.
```yaml
service: unipolsai.disable_target_area
data:
  targa: AB123CD        # opzionale
```

### `unipolsai.set_speed_limit`
Imposta il limite di velocità. La scatola nera notifica se viene superato.
```yaml
service: unipolsai.set_speed_limit
data:
  targa: AB123CD        # opzionale
  speed_limit: 90       # km/h (50–150)
```

---

## Automatismi di esempio

### Notifica push auto rubata
```yaml
automation:
  - alias: "UnipolSai - Auto spostata a motore spento"
    trigger:
      platform: event
      event_type: unipolsai_car_moved_engine_off
    action:
      service: notify.mobile_app_tuo_telefono
      data:
        title: "⚠️ Auto {{ trigger.event.data.targa }} spostata!"
        message: >
          Velocità: {{ trigger.event.data.speed_kmh }} km/h
        data:
          url: "https://maps.google.com/?q={{ trigger.event.data.latitude }},{{ trigger.event.data.longitude }}"
          push:
            interruption-level: critical
```

### Notifica superamento limite velocità
```yaml
automation:
  - alias: "UnipolSai - Limite velocità superato"
    trigger:
      platform: event
      event_type: unipolsai_speed_limit_exceeded
    action:
      service: notify.mobile_app_tuo_telefono
      data:
        title: "🚨 Limite superato ({{ trigger.event.data.speed_limit_kmh }} km/h)"
        message: "Velocità rilevata: {{ trigger.event.data.speed_kmh }} km/h"
```

### Imposta zona automaticamente quando esci di casa
```yaml
automation:
  - alias: "UnipolSai - Imposta zona quando esci"
    trigger:
      platform: zone
      entity_id: person.loris
      zone: zone.home
      event: leave
    action:
      service: unipolsai.set_target_area
      data:
        latitude: "{{ state_attr('zone.home', 'latitude') }}"
        longitude: "{{ state_attr('zone.home', 'longitude') }}"
        radius: 500
```

---

## Note tecniche

- Il **token JWT** ha durata di 1 ora e viene rinnovato automaticamente
- I **crediti Car Finder** (max 5/giorno) vengono usati solo dal pulsante "Aggiorna posizione GPS". Il polling normale usa `update=false` e non li consuma
- I **dati contratto** vengono aggiornati ogni ora, indipendentemente dall'intervallo di polling GPS
- La **geocodifica inversa** usa Nominatim (OpenStreetMap) gratuitamente, senza API key
- La **mappa** usa le tiles CartoDB Voyager; la libreria Leaflet 1.9.4 è bundled nel JS, nessun CDN richiesto
- Gli **header dell'app** (`x-ibm-client-id`, ecc.) sono credenziali dell'applicazione mobile pubblica UnipolSai, non credenziali personali

---

## Changelog

Vedi [CHANGELOG.md](CHANGELOG.md) per la storia completa delle versioni.

---

## Licenza

MIT License — vedi [LICENSE](LICENSE)
