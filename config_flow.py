"""Device tracker GPS per UnipolSai."""
import logging
from datetime import datetime

from homeassistant.components.device_tracker import TrackerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UnipolSaiCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    coordinator: UnipolSaiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([UnipolSaiTracker(coordinator, entry)])


class UnipolSaiTracker(CoordinatorEntity, TrackerEntity):
    """Tracker GPS del veicolo UnipolSai."""

    def __init__(self, coordinator: UnipolSaiCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_tracker"
        self._attr_name = f"Auto {coordinator.targa}"
        self._attr_icon = "mdi:car"

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        if self.coordinator.data:
            return self.coordinator.data.get("lat")
        return None

    @property
    def longitude(self) -> float | None:
        if self.coordinator.data:
            return self.coordinator.data.get("lon")
        return None

    @property
    def location_accuracy(self) -> int:
        if self.coordinator.data:
            # accuracy: 1=alta, 2=media, 3=bassa → convertiamo in metri
            acc_map = {1: 10, 2: 50, 3: 200}
            return acc_map.get(self.coordinator.data.get("accuracy", 3), 200)
        return 200

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        attrs = {
            "indirizzo": data.get("address"),
            "cap": data.get("zipCode"),
            "velocita_kmh": data.get("speed"),
            "direzione": data.get("heading"),
            "accuratezza": data.get("accuracy"),
            "targa": self.coordinator.targa,
        }
        # Converti timestamp Unix in datetime leggibile
        ts = data.get("date")
        if ts:
            attrs["ultimo_aggiornamento"] = datetime.fromtimestamp(ts / 1000).strftime("%d/%m/%Y %H:%M:%S")

        # Info crediti Car Finder
        fruizioni = data.get("dailyFruitions", {})
        if fruizioni:
            attrs["richieste_oggi"] = fruizioni.get("current", 0)
            attrs["max_richieste_giornaliere"] = fruizioni.get("max", 5)

        return attrs

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.targa)},
            "name": f"UnipolSai - {self.coordinator.targa}",
            "manufacturer": "UnipolSai",
            "model": "Scatola Nera Telematica",
        }
