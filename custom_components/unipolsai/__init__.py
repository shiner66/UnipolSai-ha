"""Integrazione UnipolSai per Home Assistant."""
import logging
from pathlib import Path
import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.setup import async_when_setup

from .const import DOMAIN
from .coordinator import UnipolSaiCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["device_tracker", "sensor", "button", "binary_sensor"]

_VERSION = "1.5.0"
_CARD_URL = f"/{DOMAIN}/{_VERSION}/unipolsai-vehicle-card.js"
_CARD_PATH = Path(__file__).parent / "frontend" / "unipolsai-vehicle-card.js"


async def _async_register_lovelace_resource(hass: HomeAssistant, _component: str = "") -> None:
    """Aggiunge la card alle risorse Lovelace (storage mode).

    Questo garantisce che Lovelace carichi lo script *prima* di tentare di
    renderizzare le card, eliminando il race condition del 'custom element
    not found' al primo caricamento.
    """
    try:
        from homeassistant.components.lovelace.resources import ResourceStorageCollection  # noqa: PLC0415

        lovelace_data = hass.data.get("lovelace")
        if lovelace_data is None:
            return

        # HA può esporre le risorse come dict o come attributo dell'oggetto
        if isinstance(lovelace_data, dict):
            resources = lovelace_data.get("resources")
        else:
            resources = getattr(lovelace_data, "resources", None)

        if not isinstance(resources, ResourceStorageCollection):
            # Modalità YAML: add_extra_js_url è l'unica strada
            return

        await resources.async_load()

        # Rimuove eventuali entry obsolete dello stesso dominio (versione precedente)
        stale = [
            item["id"]
            for item in resources.async_items()
            if item.get("url", "").startswith(f"/{DOMAIN}/")
            and item.get("url") != _CARD_URL
        ]
        for item_id in stale:
            try:
                await resources.async_delete_item(item_id)
                _LOGGER.debug("UnipolSai: rimossa risorsa Lovelace obsoleta (id=%s)", item_id)
            except Exception:  # noqa: BLE001
                pass

        # Aggiunge la versione corrente se non è già presente
        already = any(item.get("url") == _CARD_URL for item in resources.async_items())
        if not already:
            await resources.async_create_item({"res_type": "module", "url": _CARD_URL})
            _LOGGER.debug("UnipolSai: card aggiunta alle risorse Lovelace (%s)", _CARD_URL)

    except Exception as exc:  # noqa: BLE001
        # Non fatale: add_extra_js_url fa da fallback in modalità YAML
        _LOGGER.debug("UnipolSai: registrazione risorsa Lovelace non riuscita: %s", exc)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Registra il percorso statico e inietta la Lovelace card nel frontend."""
    await hass.http.async_register_static_paths([
        StaticPathConfig(url_path=_CARD_URL, path=str(_CARD_PATH), cache_headers=False)
    ])

    # Fallback per modalità YAML (lovelace non usa storage)
    add_extra_js_url(hass, _CARD_URL)

    # Registrazione affidabile via risorse Lovelace (storage mode).
    # async_when_setup chiama subito se lovelace è già pronto, altrimenti aspetta.
    async_when_setup(hass, "lovelace", _async_register_lovelace_resource)

    _LOGGER.debug("UnipolSai: card registrata su %s", _CARD_URL)
    return True

SERVICE_SET_TARGET_AREA = "set_target_area"
SERVICE_DISABLE_TARGET_AREA = "disable_target_area"
SERVICE_SET_SPEED_LIMIT = "set_speed_limit"
SERVICE_SET_USAGES_PERIOD = "set_usages_period"

# Il campo targa è opzionale: se omesso il servizio agisce su tutte le auto configurate.
_TARGA_FIELD = vol.Optional("targa")

SET_TARGET_AREA_SCHEMA = vol.Schema({
    _TARGA_FIELD: str,
    vol.Required("latitude"): cv.latitude,
    vol.Required("longitude"): cv.longitude,
    vol.Required("radius"): vol.All(int, vol.Range(min=100, max=5000)),
})

SET_SPEED_LIMIT_SCHEMA = vol.Schema({
    _TARGA_FIELD: str,
    vol.Required("speed_limit"): vol.All(int, vol.Range(min=50, max=150)),
})

DISABLE_TARGET_AREA_SCHEMA = vol.Schema({
    _TARGA_FIELD: str,
})

SET_USAGES_PERIOD_SCHEMA = vol.Schema({
    _TARGA_FIELD: str,
    vol.Required("start_date"): cv.date,
    vol.Required("end_date"): cv.date,
})


def _get_coordinators(hass: HomeAssistant, targa: str | None) -> list[UnipolSaiCoordinator]:
    """Restituisce i coordinator corrispondenti alla targa, o tutti se non specificata."""
    all_coords = list(hass.data.get(DOMAIN, {}).values())
    if not targa:
        return all_coords
    targa_norm = targa.upper().replace(" ", "")
    return [c for c in all_coords if c.targa == targa_norm]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Inizializza l'integrazione per un veicolo."""
    coordinator = UnipolSaiCoordinator(
        hass,
        username=entry.data["username"],
        password=entry.data["password"],
        targa=entry.data["targa"],
        scan_interval=entry.options.get("scan_interval", entry.data.get("scan_interval", 5)),
    )

    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Registra i servizi solo la prima volta
    if not hass.services.has_service(DOMAIN, SERVICE_SET_TARGET_AREA):

        async def handle_set_target_area(call: ServiceCall) -> None:
            """Imposta la target area per uno o tutti i veicoli.

            Parametri:
              targa (opzionale): targa del veicolo (es. AB123CD). Se omessa, agisce su tutti.
              latitude: latitudine del centro zona
              longitude: longitudine del centro zona
              radius: raggio in metri (100–5000)

            Esempio:
              service: unipolsai.set_target_area
              data:
                targa: AB123CD
                latitude: 40.5578515
                longitude: 14.9281384
                radius: 500
            """
            for coord in _get_coordinators(hass, call.data.get("targa")):
                await coord.async_set_target_area(
                    lat=call.data["latitude"],
                    lon=call.data["longitude"],
                    radius=call.data["radius"],
                    active=True,
                )

        async def handle_disable_target_area(call: ServiceCall) -> None:
            """Disattiva la target area per uno o tutti i veicoli.

            Parametri:
              targa (opzionale): targa del veicolo. Se omessa, agisce su tutti.

            Esempio:
              service: unipolsai.disable_target_area
              data:
                targa: AB123CD
            """
            for coord in _get_coordinators(hass, call.data.get("targa")):
                await coord.async_disable_target_area()

        async def handle_set_speed_limit(call: ServiceCall) -> None:
            """Imposta il limite di velocità per uno o tutti i veicoli.

            Parametri:
              targa (opzionale): targa del veicolo. Se omessa, agisce su tutti.
              speed_limit: limite in km/h (50–150)

            Esempio:
              service: unipolsai.set_speed_limit
              data:
                targa: AB123CD
                speed_limit: 90
            """
            for coord in _get_coordinators(hass, call.data.get("targa")):
                await coord.async_set_speed_limit(call.data["speed_limit"])

        async def handle_set_usages_period(call: ServiceCall) -> None:
            """Imposta il periodo delle statistiche di guida.

            Parametri:
              targa (opzionale): targa del veicolo. Se omessa, agisce su tutti.
              start_date: data inizio (YYYY-MM-DD)
              end_date: data fine (YYYY-MM-DD)

            Esempio — statistiche del mese corrente:
              service: unipolsai.set_usages_period
              data:
                targa: AB123CD
                start_date: "2026-03-01"
                end_date: "2026-03-31"

            Esempio — ultima settimana:
              service: unipolsai.set_usages_period
              data:
                start_date: "{{ (now() - timedelta(days=7)).strftime('%Y-%m-%d') }}"
                end_date: "{{ now().strftime('%Y-%m-%d') }}"
            """
            start = call.data["start_date"].strftime("%Y-%m-%d")
            end = call.data["end_date"].strftime("%Y-%m-%d")
            for coord in _get_coordinators(hass, call.data.get("targa")):
                await coord.async_set_usages_period(start, end)

        hass.services.async_register(DOMAIN, SERVICE_SET_TARGET_AREA, handle_set_target_area, schema=SET_TARGET_AREA_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_DISABLE_TARGET_AREA, handle_disable_target_area, schema=DISABLE_TARGET_AREA_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_SET_SPEED_LIMIT, handle_set_speed_limit, schema=SET_SPEED_LIMIT_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_SET_USAGES_PERIOD, handle_set_usages_period, schema=SET_USAGES_PERIOD_SCHEMA)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Rimuove l'integrazione per un veicolo."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: UnipolSaiCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()

    # Rimuovi i servizi solo quando non ci sono più veicoli configurati
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_SET_TARGET_AREA)
        hass.services.async_remove(DOMAIN, SERVICE_DISABLE_TARGET_AREA)
        hass.services.async_remove(DOMAIN, SERVICE_SET_SPEED_LIMIT)
        hass.services.async_remove(DOMAIN, SERVICE_SET_USAGES_PERIOD)

    return unload_ok
