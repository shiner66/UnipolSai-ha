/**
 * UnipolSai Vehicle Card — Lovelace Custom Card
 * Version: 1.4.0
 * Mappa dinamica per la posizione dei veicoli UnipolSai.
 * Supporta istanze multiple (una card per veicolo, o auto-rilevamento).
 *
 * Configurazione YAML:
 *   type: custom:unipolsai-vehicle-card
 *   targa: AB123CD       # opzionale — se omesso rileva tutti i veicoli UnipolSai
 *   zoom: 15             # opzionale — livello di zoom iniziale (default: 15)
 *   height: 300          # opzionale — altezza mappa in px (default: 300)
 */

(function () {
  'use strict';

  const CARD_VERSION = '1.4.0';
  const LEAFLET_VERSION = '1.9.4';
  const CDN_BASE = `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist`;

  // ── Leaflet loader (singleton) ─────────────────────────────────────────────
  let _leafletPromise = null;

  function _loadLeaflet() {
    if (_leafletPromise) return _leafletPromise;
    if (window.L && window.L.map) {
      _leafletPromise = Promise.resolve(window.L);
      return _leafletPromise;
    }
    _leafletPromise = new Promise((resolve, reject) => {
      if (!document.querySelector('link[href*="leaflet"]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = `${CDN_BASE}/leaflet.css`;
        link.integrity = 'sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=';
        link.crossOrigin = '';
        document.head.appendChild(link);
      }
      const script = document.createElement('script');
      script.src = `${CDN_BASE}/leaflet.js`;
      script.integrity = 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV/XN/WLs=';
      script.crossOrigin = '';
      script.onload = () => resolve(window.L);
      script.onerror = () => reject(new Error('Impossibile caricare Leaflet dal CDN'));
      document.head.appendChild(script);
    });
    return _leafletPromise;
  }

  // ── Utility ────────────────────────────────────────────────────────────────
  function _slugify(str) {
    return String(str)
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '') // rimuove accenti (è→e, à→a, ecc.)
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '');
  }

  /**
   * Costruisce gli entity_id a partire dalla targa.
   * Rispecchia la nomenclatura usata dall'integrazione Python:
   *   "Crediti Car Finder AB123CD" → sensor.crediti_car_finder_ab123cd
   */
  function _entityIds(targa) {
    const t = _slugify(targa);
    return {
      tracker:    `device_tracker.auto_${t}`,
      credits:    `sensor.crediti_car_finder_${t}`,
      lastUpdate: `sensor.ultimo_aggiornamento_gps_${t}`,
      button:     `button.aggiorna_posizione_gps_${t}`,
      pending:    `binary_sensor.aggiornamento_gps_in_corso_${t}`,
      address:    `sensor.indirizzo_${t}`,
      speed:      `sensor.velocita_${t}`,
    };
  }

  function _fmtDatetime(isoStr) {
    if (!isoStr || isoStr === 'unknown' || isoStr === 'unavailable') return '—';
    try {
      const d = new Date(isoStr);
      return d.toLocaleString('it-IT', {
        day: '2-digit', month: '2-digit',
        hour: '2-digit', minute: '2-digit',
      });
    } catch (_) {
      return isoStr;
    }
  }

  function _safeState(state) {
    if (!state || state === 'unknown' || state === 'unavailable') return null;
    return state;
  }

  /** SVG car icon per Leaflet marker. */
  function _carIcon(L, isMoving, isPending) {
    const color = isPending ? '#FF9800' : (isMoving ? '#2196F3' : '#4CAF50');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="40" height="40">
      <circle cx="20" cy="20" r="18" fill="${color}" opacity="0.92" stroke="white" stroke-width="2"/>
      <path d="M9 19l2-6h18l2 6v8H9v-8zm2 1v5h18v-5H11zm2-1h14l-1.5-4h-11L13 19zm1.5 4a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm11 0a1.5 1.5 0 110 3 1.5 1.5 0 010-3z" fill="white"/>
      ${isPending ? '<circle cx="32" cy="10" r="5" fill="#FF9800" stroke="white" stroke-width="1.5"/><text x="32" y="14" text-anchor="middle" font-size="7" fill="white" font-weight="bold">…</text>' : ''}
    </svg>`;
    return L.divIcon({
      html: svg,
      className: 'unipolsai-marker',
      iconSize: [40, 40],
      iconAnchor: [20, 20],
      popupAnchor: [0, -22],
    });
  }

  // ── Styles ─────────────────────────────────────────────────────────────────
  const STYLES = `
    :host { display: block; }
    ha-card { overflow: hidden; font-family: var(--paper-font-body1_-_font-family, sans-serif); }

    /* Header */
    .card-header {
      display: flex; align-items: center; gap: 8px;
      padding: 14px 16px 10px;
      font-size: 1.05em; font-weight: 600;
      color: var(--primary-text-color);
      border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.12));
    }
    .card-header ha-icon { color: var(--primary-color); --mdc-icon-size: 22px; }

    /* Map */
    #map-container {
      width: 100%;
      background: var(--secondary-background-color, #f5f5f5);
      position: relative;
    }
    .map-loading, .map-error {
      display: flex; align-items: center; justify-content: center;
      height: 100%; padding: 24px;
      color: var(--secondary-text-color); font-size: 0.9em; text-align: center;
    }
    .map-error { color: var(--error-color, #db4437); }

    /* Vehicle panels */
    .vehicles-info { padding: 8px 12px 12px; display: flex; flex-direction: column; gap: 8px; }

    .vehicle-panel {
      border: 1px solid var(--divider-color, rgba(0,0,0,.12));
      border-radius: 10px; overflow: hidden;
      background: var(--card-background-color, white);
    }

    .vehicle-header {
      display: flex; align-items: center; gap: 8px;
      padding: 9px 12px;
      background: var(--secondary-background-color, #f5f5f5);
      cursor: pointer; transition: background 0.15s;
      user-select: none;
    }
    .vehicle-header:hover { background: var(--secondary-background-color, #ececec); filter: brightness(0.97); }
    .vehicle-header ha-icon { color: var(--primary-color); --mdc-icon-size: 18px; flex-shrink: 0; }

    .targa-badge {
      font-weight: 700; font-size: 0.88em; letter-spacing: 1.5px;
      color: var(--primary-color);
      background: rgba(var(--rgb-primary-color, 33,150,243), 0.12);
      padding: 2px 8px; border-radius: 4px; white-space: nowrap;
    }
    .address-text {
      font-size: 0.82em; color: var(--secondary-text-color);
      flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }

    /* Stats row */
    .stats-row {
      display: flex; flex-wrap: wrap; gap: 6px;
      padding: 8px 12px;
    }
    .chip {
      display: inline-flex; align-items: center; gap: 4px;
      font-size: 0.8em; color: var(--secondary-text-color);
      background: var(--secondary-background-color, #f5f5f5);
      border-radius: 20px; padding: 3px 9px;
      white-space: nowrap;
    }
    .chip ha-icon { --mdc-icon-size: 13px; }
    .chip.credits-ok  { color: var(--primary-color); }
    .chip.credits-low { color: var(--warning-color, #ff9800); }
    .chip.credits-none { color: var(--error-color, #db4437); }
    .chip.pending {
      color: #2196F3; font-weight: 500;
      animation: blink 1.4s ease-in-out infinite;
    }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.4} }

    /* Update button */
    .btn-update {
      display: flex; align-items: center; justify-content: center; gap: 6px;
      width: calc(100% - 24px); margin: 0 12px 12px;
      padding: 9px 16px;
      background: var(--primary-color); color: var(--text-primary-color, #fff);
      border: none; border-radius: 8px; cursor: pointer;
      font-size: 0.88em; font-weight: 500;
      transition: opacity .2s, transform .1s;
    }
    .btn-update:hover:not([disabled]) { opacity: .88; }
    .btn-update:active:not([disabled]) { transform: scale(.98); }
    .btn-update[disabled] { opacity: .45; cursor: not-allowed; }
    .btn-update ha-icon { --mdc-icon-size: 15px; }

    /* Leaflet overrides inside shadow root */
    .leaflet-container { font-family: inherit; }
    .leaflet-popup-content-wrapper { border-radius: 8px; }
  `;

  // ── Main Card Class ────────────────────────────────────────────────────────
  class UnipolSaiVehicleCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._config = null;
      this._hass = null;
      this._map = null;
      this._L = null;
      this._markers = {};       // targa → Leaflet marker
      this._vehicles = [];      // targas to show
      this._initializing = false;
      this._ready = false;
    }

    // HA chiama questo per la configurazione di default nel visual editor
    static getStubConfig() {
      return { targa: '' };
    }

    setConfig(config) {
      if (!config) throw new Error('Configurazione mancante');
      this._config = config;
      this._vehicles = config.targa
        ? [String(config.targa).toUpperCase()]
        : [];
      // Reset al cambio config
      if (this._ready) {
        this._ready = false;
        this._initializing = false;
        this._map = null;
        this._L = null;
        this._markers = {};
      }
    }

    set hass(hass) {
      this._hass = hass;
      if (!this._config?.targa) {
        this._autoDiscover();
      }
      if (!this._ready && !this._initializing && this._vehicles.length > 0) {
        this._init();
      } else if (this._ready) {
        this._update();
      }
    }

    get hass() { return this._hass; }

    /** Rileva automaticamente i veicoli UnipolSai cercando il pattern targa nell'attributo. */
    _autoDiscover() {
      const found = [];
      for (const [eid, state] of Object.entries(this._hass.states)) {
        if (!eid.startsWith('device_tracker.auto_')) continue;
        const t = state.attributes?.targa;
        if (t && !found.includes(t.toUpperCase())) {
          found.push(t.toUpperCase());
        }
      }
      // Fallback: cerca entità con unique_id pattern unipolsai_*_tracker tramite entity_id
      if (found.length === 0) {
        for (const eid of Object.keys(this._hass.states)) {
          if (!eid.startsWith('device_tracker.auto_')) continue;
          // estrai targa dall'entity_id (device_tracker.auto_ab123cd → AB123CD)
          const candidate = eid.replace('device_tracker.auto_', '').toUpperCase();
          // verifica che esista il sensore crediti corrispondente
          const credEid = `sensor.crediti_car_finder_${_slugify(candidate)}`;
          if (this._hass.states[credEid]) {
            if (!found.includes(candidate)) found.push(candidate);
          }
        }
      }
      if (JSON.stringify(found) !== JSON.stringify(this._vehicles)) {
        this._vehicles = found;
        // Se cambia il numero di veicoli, re-init
        if (this._ready) {
          this._ready = false;
          this._initializing = false;
          this._map = null;
          this._L = null;
          this._markers = {};
        }
      }
    }

    async _init() {
      if (this._initializing || this._vehicles.length === 0) return;
      this._initializing = true;

      this._renderSkeleton();

      try {
        const L = await _loadLeaflet();
        this._L = L;
        // Inietta CSS Leaflet nel shadow root
        if (!this.shadowRoot.querySelector('link[href*="leaflet"]')) {
          const link = document.createElement('link');
          link.rel = 'stylesheet';
          link.href = `${CDN_BASE}/leaflet.css`;
          this.shadowRoot.appendChild(link);
        }
        this._initMap(L);
        this._ready = true;
        this._update();
      } catch (e) {
        this._showMapError(`Mappa non disponibile: ${e.message}<br><small>Verifica la connessione internet.</small>`);
      } finally {
        this._initializing = false;
      }
    }

    _renderSkeleton() {
      const mapH = this._config?.height ?? 300;
      const root = this.shadowRoot;
      root.innerHTML = `
        <style>${STYLES}</style>
        <ha-card>
          <div class="card-header">
            <ha-icon icon="mdi:car-multiple"></ha-icon>
            <span>UnipolSai Telematica</span>
          </div>
          <div id="map-container" style="height:${mapH}px">
            <div class="map-loading">⏳ Caricamento mappa…</div>
          </div>
          <div class="vehicles-info" id="vehicles-info"></div>
        </ha-card>
      `;
    }

    _initMap(L) {
      const container = this.shadowRoot.getElementById('map-container');
      if (!container) return;
      container.innerHTML = '';

      const mapDiv = document.createElement('div');
      mapDiv.style.cssText = 'width:100%;height:100%;';
      container.appendChild(mapDiv);

      this._map = L.map(mapDiv, {
        zoom: this._config?.zoom ?? 15,
        zoomControl: true,
        attributionControl: true,
      });

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(this._map);

      // Forza ridimensionamento dopo init
      setTimeout(() => { if (this._map) this._map.invalidateSize(); }, 250);
    }

    _update() {
      if (!this._hass || !this._map || !this._ready) return;
      const hass = this._hass;
      const L = this._L;
      const infoEl = this.shadowRoot.getElementById('vehicles-info');
      if (!infoEl) return;

      infoEl.innerHTML = '';
      const bounds = [];

      for (const targa of this._vehicles) {
        const ids = _entityIds(targa);
        const tracker    = hass.states[ids.tracker];
        const credSt     = hass.states[ids.credits];
        const updSt      = hass.states[ids.lastUpdate];
        const btnSt      = hass.states[ids.button];
        const pendSt     = hass.states[ids.pending];
        const addrSt     = hass.states[ids.address];
        const speedSt    = hass.states[ids.speed];

        const lat        = tracker?.attributes?.latitude;
        const lon        = tracker?.attributes?.longitude;
        const address    = _safeState(addrSt?.state)
                        ?? _safeState(tracker?.attributes?.indirizzo)
                        ?? '';
        const credits    = _safeState(credSt?.state);
        const maxCred    = credSt?.attributes?.crediti_totali ?? 5;
        const lastUpd    = _safeState(updSt?.state);
        const speed      = _safeState(speedSt?.state);
        const isPending  = pendSt?.state === 'on';
        const credNum    = credits !== null ? parseInt(credits, 10) : null;
        const btnDisabled = !btnSt || btnSt.state === 'unavailable' || isPending;

        // ── Aggiorna marker sulla mappa ──────────────────────────────────
        if (lat != null && lon != null) {
          const pos = [lat, lon];
          bounds.push(pos);
          const isMoving = speed !== null && parseFloat(speed) > 0;
          const icon = _carIcon(L, isMoving, isPending);

          if (this._markers[targa]) {
            this._markers[targa].setLatLng(pos).setIcon(icon);
            this._markers[targa]
              .getPopup()
              ?.setContent(`<b>${targa}</b>${address ? '<br>' + address : ''}`);
          } else {
            this._markers[targa] = L.marker(pos, { icon })
              .addTo(this._map)
              .bindPopup(`<b>${targa}</b>${address ? '<br>' + address : ''}`);
          }
        }

        // ── Chip crediti ─────────────────────────────────────────────────
        let credClass = 'credits-ok';
        let credLabel = credits !== null ? `${credits}/${maxCred} crediti` : '?/? crediti';
        if (credNum !== null) {
          if (credNum === 0) credClass = 'credits-none';
          else if (credNum <= 1) credClass = 'credits-low';
        }

        // ── Panel HTML ───────────────────────────────────────────────────
        const speedChip = speed !== null
          ? `<span class="chip">
               <ha-icon icon="mdi:speedometer"></ha-icon>
               ${parseFloat(speed).toFixed(0)} km/h
             </span>`
          : '';

        const pendingChip = isPending
          ? `<span class="chip pending">
               <ha-icon icon="mdi:satellite-uplink"></ha-icon>
               Aggiornamento GPS…
             </span>`
          : '';

        const panel = document.createElement('div');
        panel.className = 'vehicle-panel';
        panel.innerHTML = `
          <div class="vehicle-header" title="Centra mappa su ${targa}">
            <ha-icon icon="mdi:car"></ha-icon>
            <span class="targa-badge">${targa}</span>
            <span class="address-text">${address || 'Posizione non disponibile'}</span>
          </div>
          <div class="stats-row">
            <span class="chip ${credClass}">
              <ha-icon icon="mdi:credit-card-check-outline"></ha-icon>
              ${credLabel}
            </span>
            <span class="chip">
              <ha-icon icon="mdi:clock-outline"></ha-icon>
              ${_fmtDatetime(lastUpd)}
            </span>
            ${speedChip}
            ${pendingChip}
          </div>
          <button class="btn-update" ${btnDisabled ? 'disabled' : ''}>
            <ha-icon icon="mdi:crosshairs-gps"></ha-icon>
            ${isPending ? 'Aggiornamento in corso…' : 'Aggiorna posizione GPS'}
          </button>
        `;

        // Click header → centra la mappa sul veicolo
        if (lat != null && lon != null) {
          panel.querySelector('.vehicle-header').addEventListener('click', () => {
            this._map.setView([lat, lon], this._config?.zoom ?? 15, { animate: true });
            if (this._markers[targa]) this._markers[targa].openPopup();
          });
        }

        // Click button → press dell'entità button
        panel.querySelector('.btn-update').addEventListener('click', () => {
          if (!btnDisabled) this._pressButton(ids.button);
        });

        infoEl.appendChild(panel);
      }

      // ── Adatta vista mappa ───────────────────────────────────────────────
      if (bounds.length === 1) {
        this._map.setView(bounds[0], this._config?.zoom ?? 15, { animate: true });
      } else if (bounds.length > 1) {
        this._map.fitBounds(bounds, { padding: [50, 50], animate: true, maxZoom: 16 });
      }
      setTimeout(() => { if (this._map) this._map.invalidateSize(); }, 100);
    }

    _pressButton(entityId) {
      if (!this._hass) return;
      this._hass.callService('button', 'press', { entity_id: entityId });
    }

    _showMapError(html) {
      const container = this.shadowRoot?.getElementById('map-container');
      if (container) container.innerHTML = `<div class="map-error">⚠️ ${html}</div>`;
    }

    getCardSize() {
      const mapH = this._config?.height ?? 300;
      return Math.ceil(mapH / 50) + this._vehicles.length * 3;
    }
  }

  // ── Registrazione ──────────────────────────────────────────────────────────
  if (!customElements.get('unipolsai-vehicle-card')) {
    customElements.define('unipolsai-vehicle-card', UnipolSaiVehicleCard);
  }

  window.customCards = window.customCards || [];
  if (!window.customCards.find(c => c.type === 'unipolsai-vehicle-card')) {
    window.customCards.push({
      type: 'unipolsai-vehicle-card',
      name: 'UnipolSai Vehicle Card',
      description: 'Mappa dinamica dei veicoli UnipolSai con aggiornamento GPS live, crediti rimanenti e ultimo aggiornamento.',
      preview: true,
      documentationURL: 'https://github.com/shiner66/UnipolSai-ha',
    });
  }

  console.info(
    `%c UNIPOLSAI-VEHICLE-CARD %c v${CARD_VERSION} `,
    'color:#fff;background:#e31837;font-weight:bold;padding:2px 4px;',
    'color:#e31837;background:#fff;font-weight:bold;padding:2px 4px;border:1px solid #e31837;',
  );
})();
