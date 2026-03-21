"""Integrazione UnipolSai per Home Assistant."""
import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import UnipolSaiCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["device_tracker", "sensor", "button", "binary_sensor"]

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
