const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const cardPath = path.join(
  __dirname,
  '..',
  'custom_components',
  'unipolsai',
  'frontend',
  'unipolsai-vehicle-card.js',
);

function loadCardClass() {
  const source = fs.readFileSync(cardPath, 'utf8');
  const marker = '/* ── UnipolSai Vehicle Card';
  const cardSource = source
    .slice(source.indexOf('(function () {', source.indexOf(marker)))
    .replace(
      'const CARD_MODULE_URL = import.meta.url;',
      "const CARD_MODULE_URL = 'https://example.test/unipolsai/1.5.5/unipolsai-vehicle-card.js';",
    );
  const registry = new Map();
  const documentStub = {};

  class HTMLElementStub {
    attachShadow() {
      const shadowRoot = {
        getElementById: () => null,
        replaceChildren() {},
      };
      this.shadowRoot = shadowRoot;
      return shadowRoot;
    }
  }

  const context = {
    HTMLElement: HTMLElementStub,
    clearTimeout,
    console: { info() {}, warn() {}, error() {} },
    customElements: {
      define: (name, constructor) => registry.set(name, constructor),
      get: name => registry.get(name),
    },
    document: documentStub,
    setTimeout,
    URL,
    window: { customCards: [] },
  };
  vm.runInNewContext(cardSource, context, { filename: cardPath });
  const Card = registry.get('unipolsai-vehicle-card');
  Card.testDocument = documentStub;
  return Card;
}

function initializeMap(Card, { states, vehicles, zoom }) {
  const card = new Card();
  const mapContainer = {
    appendChild() {},
    innerHTML: '',
  };
  card.shadowRoot.getElementById = id => (id === 'map-container' ? mapContainer : null);
  card._hass = { states };
  card._vehicles = vehicles;
  card._config = { zoom };
  card._scheduleInvalidate = () => {};

  const events = [];
  let center;
  let currentZoom;
  const map = {
    getCenter() {
      events.push('getCenter');
      if (!center) throw new Error('Leaflet center is not initialized');
      return { lat: center[0], lng: center[1] };
    },
    getZoom() {
      if (currentZoom === undefined) throw new Error('Leaflet zoom is not initialized');
      return currentZoom;
    },
    setView(nextCenter, nextZoom) {
      events.push('setView');
      center = [...nextCenter];
      currentZoom = nextZoom;
      return this;
    },
  };
  const L = { map: () => map };

  card._addVectorLayer = () => {
    events.push('addVectorLayer');
    map.getCenter(); // L'adapter MapLibre lo legge sincronicamente in addTo().
    map.getZoom();
  };

  const originalCreateElement = Card.testDocument.createElement;
  Card.testDocument.createElement = () => ({ style: {} });
  try {
    card._initMap(L);
  } finally {
    Card.testDocument.createElement = originalCreateElement;
  }

  return { center, currentZoom, events };
}

test('sets the first valid tracker position before adding MapLibre', () => {
  const Card = loadCardClass();
  const result = initializeMap(Card, {
    states: {
      'device_tracker.auto_invalid': {
        attributes: { latitude: '', longitude: 12.5 },
      },
      'device_tracker.auto_valid': {
        attributes: { latitude: 40.5578515, longitude: 14.9281384 },
      },
    },
    vehicles: [{ targa: 'INVALID' }, { targa: 'VALID' }],
    zoom: 17,
  });

  assert.deepEqual(result.center, [40.5578515, 14.9281384]);
  assert.equal(result.currentZoom, 17);
  assert.deepEqual(result.events, ['setView', 'addVectorLayer', 'getCenter']);
});

test('uses a valid world view when no tracker position is available', () => {
  const Card = loadCardClass();
  const result = initializeMap(Card, {
    states: {},
    vehicles: [{ targa: 'MISSING' }],
    zoom: 18,
  });

  assert.deepEqual(result.center, [0, 0]);
  assert.equal(result.currentZoom, 2);
  assert.deepEqual(result.events, ['setView', 'addVectorLayer', 'getCenter']);
});
