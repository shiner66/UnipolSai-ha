"""Integrazione UnipolSai per Home Assistant."""
import logging
from pathlib import Path
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import UnipolSaiCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["device_tracker", "sensor", "button", "binary_sensor"]

_CARD_URL = f"/{DOMAIN}/unipolsai-vehicle-card.js"
_CARD_PATH = Path(__file__).parent / "frontend" / "unipolsai-vehicle-card.js"


async def _async_register_lovelace_resource(hass: HomeAssistant, url: str) -> None:
    """Aggiunge la card alle risorse Lovelace (storage mode) se non già presente."""
    try:
        from homeassistant.components.lovelace.resources import ResourceStorageCollection

        lovelace = hass.data.get("lovelace")
        if not lovelace:
            return

        resources = lovelace.get("resources")
        if not isinstance(resources, ResourceStorageCollection):
            return

        for item in resources.async_items():
            if item.get("url") == url:
                _LOGGER.debug("UnipolSai: risorsa Lovelace già presente")
                return

        await resources.async_create_item({"res_type": "module", "url": url})
        _LOGGER.info("UnipolSai: card aggiunta alle risorse Lovelace: %s", url)

    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("UnipolSai: Lovelace storage non disponibile (%s), uso fallback", err)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Registra il percorso statico e inietta la Lovelace card nel frontend."""
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths([
            StaticPathConfig(
                url_path=_CARD_URL,
                path=_CARD_PATH,
                cache_headers=False,
            )
        ])
        _LOGGER.debug("UnipolSai: percorso statico registrato su %s", _CARD_URL)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("UnipolSai: impossibile registrare il percorso statico: %s", err)

    # Fallback: inietta tramite frontend.add_extra_js_url (pre-2024 HA)
    try:
        from homeassistant.components import frontend
        frontend.add_extra_js_url(hass, _CARD_URL)
    except Exception:  # noqa: BLE001
        pass

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
    # Registra la card nelle risorse Lovelace (lovelace è già caricato a questo punto)
    hass.async_create_task(_async_register_lovelace_resource(hass, _CARD_URL))

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
