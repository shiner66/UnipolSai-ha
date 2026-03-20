"""Binary sensor UnipolSai: GPS in corso, auto spostata, uscita zona."""
import logging
from datetime import datetime

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UnipolSaiCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    coordinator: UnipolSaiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        UnipolSaiPendingSensor(coordinator, entry),
        UnipolSaiCarMovedSensor(coordinator, entry),
        UnipolSaiTargetAreaExitSensor(coordinator, entry),
    ])


class _BaseBinary(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator: UnipolSaiCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.targa)},
            "name": f"UnipolSai - {self.coordinator.targa}",
            "manufacturer": "UnipolSai",
            "model": "Scatola Nera Telematica",
        }


class UnipolSaiPendingSensor(_BaseBinary):
    """True mentre la scatola nera sta elaborando una richiesta GPS live."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_pending"
        self._attr_name = f"Aggiornamento GPS in corso {coordinator.targa}"
        self._attr_device_class = BinarySensorDeviceClass.RUNNING
        self._attr_icon = "mdi:satellite-uplink"

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_pending

    @property
    def extra_state_attributes(self) -> dict:
        fruizioni = (self.coordinator.data or {}).get("dailyFruitions", {})
        return {
            "crediti_usati_oggi": fruizioni.get("current"),
            "crediti_max_giornalieri": fruizioni.get("max", 5),
            "crediti_rimanenti": self.coordinator.available_credits,
        }


class UnipolSaiCarMovedSensor(_BaseBinary):
    """True se l'auto è stata spostata a motore spento (evento anti-furto)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_car_moved"
        self._attr_name = f"Auto spostata a motore spento {coordinator.targa}"
        self._attr_device_class = BinarySensorDeviceClass.MOTION
        self._attr_icon = "mdi:car-key"
        self._last_notified_id: str | None = None
        self._initialized: bool = False

    async def async_added_to_hass(self) -> None:
        """Inizializza l'ID al caricamento per evitare falsi positivi con notifiche storiche."""
        await super().async_added_to_hass()
        notif = self.coordinator.last_car_moved_notification
        if notif:
            self._last_notified_id = notif.get("id")
        self._initialized = True

    @property
    def is_on(self) -> bool:
        if not self._initialized:
            return False
        notif = self.coordinator.last_car_moved_notification
        if not notif:
            return False
        return notif.get("id") != self._last_notified_id

    def _handle_coordinator_update(self) -> None:
        notif = self.coordinator.last_car_moved_notification
        if notif:
            self._last_notified_id = notif.get("id")
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict:
        notif = self.coordinator.last_car_moved_notification
        if not notif:
            return {}
        lat, lon = notif.get("latitude"), notif.get("longitude")
        return {
            "data_evento": self.coordinator._fmt_ts(notif.get("eventDate", 0)),
            "latitudine": lat,
            "longitudine": lon,
            "velocita_kmh": notif.get("speed"),
            "accuratezza": notif.get("accuracy"),
            "maps_url": f"https://www.google.com/maps?q={lat},{lon}" if lat and lon else None,
        }


class UnipolSaiTargetAreaExitSensor(_BaseBinary):
    """True se l'auto è uscita dalla zona target area configurata."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_target_area_exit"
        self._attr_name = f"Auto uscita dalla zona {coordinator.targa}"
        self._attr_device_class = BinarySensorDeviceClass.MOTION
        self._attr_icon = "mdi:map-marker-alert"
        self._last_notified_id: str | None = None
        self._initialized: bool = False

    async def async_added_to_hass(self) -> None:
        """Inizializza l'ID al caricamento per evitare falsi positivi con notifiche storiche."""
        await super().async_added_to_hass()
        notif = self.coordinator.last_target_area_notification
        if notif:
            self._last_notified_id = notif.get("id")
        self._initialized = True

    @property
    def is_on(self) -> bool:
        if not self._initialized:
            return False
        notif = self.coordinator.last_target_area_notification
        if not notif:
            return False
        return notif.get("id") != self._last_notified_id

    def _handle_coordinator_update(self) -> None:
        notif = self.coordinator.last_target_area_notification
        if notif:
            self._last_notified_id = notif.get("id")
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict:
        notif = self.coordinator.last_target_area_notification
        if not notif:
            return {}
        lat, lon = notif.get("latitude"), notif.get("longitude")
        ta = self.coordinator.target_area or {}
        return {
            "data_evento": self.coordinator._fmt_ts(notif.get("eventDate", 0)),
            "latitudine_auto": lat,
            "longitudine_auto": lon,
            "velocita_kmh": notif.get("speed"),
            "maps_url": f"https://www.google.com/maps?q={lat},{lon}" if lat and lon else None,
            "zona_centro_lat": ta.get("lat"),
            "zona_centro_lon": ta.get("lon"),
            "zona_raggio_m": ta.get("radius"),
            "zona_stato": ta.get("status"),
        }
