"""Pulsante per richiedere un fix GPS live a UnipolSai."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UnipolSaiCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    coordinator: UnipolSaiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([UnipolSaiLivePositionButton(coordinator, entry)])


class UnipolSaiLivePositionButton(CoordinatorEntity, ButtonEntity):
    """Pulsante per richiedere aggiornamento GPS in tempo reale."""

    def __init__(self, coordinator: UnipolSaiCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_live_position"
        self._attr_name = f"Aggiorna posizione GPS {coordinator.targa}"
        self._attr_icon = "mdi:crosshairs-gps"

    @property
    def available(self) -> bool:
        """Non disponibile se già in attesa o se crediti esauriti."""
        if self.coordinator.is_pending:
            return False
        credits = self.coordinator.available_credits
        if credits is not None and credits <= 0:
            return False
        return True

    @property
    def extra_state_attributes(self) -> dict:
        credits = self.coordinator.available_credits
        return {
            "crediti_rimanenti_oggi": credits,
            "in_attesa_risposta": self.coordinator.is_pending,
        }

    async def async_press(self) -> None:
        """Invia richiesta fix GPS live alla scatola nera."""
        _LOGGER.info("UnipolSai: pulsante premuto, richiesta fix GPS live")
        await self.coordinator.async_request_live_position()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.targa)},
            "name": f"UnipolSai - {self.coordinator.targa}",
            "manufacturer": "UnipolSai",
            "model": "Scatola Nera Telematica",
        }
