"""Sensori UnipolSai: GPS, target area, contratto, statistiche di guida."""
import logging
from datetime import datetime, timezone, date

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfSpeed, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UnipolSaiCoordinator

_LOGGER = logging.getLogger(__name__)

DIREZIONE_MAP = {
    "N": "Nord", "NE": "Nord-Est", "E": "Est", "SE": "Sud-Est",
    "S": "Sud", "SW": "Sud-Ovest", "W": "Ovest", "NW": "Nord-Ovest",
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    coordinator: UnipolSaiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        # GPS
        UnipolSaiSpeedSensor(coordinator, entry),
        UnipolSaiAddressSensor(coordinator, entry),
        UnipolSaiGeocodedAddressSensor(coordinator, entry),
        UnipolSaiHeadingSensor(coordinator, entry),
        UnipolSaiLastUpdateSensor(coordinator, entry),
        UnipolSaiCarFinderCreditsSensor(coordinator, entry),
        # Target area
        UnipolSaiTargetAreaStatusSensor(coordinator, entry),
        UnipolSaiTargetAreaRadiusSensor(coordinator, entry),
        # Speed limit
        UnipolSaiSpeedLimitSensor(coordinator, entry),
        # Contratto
        UnipolSaiContractNumberSensor(coordinator, entry),
        UnipolSaiContractExpirySensor(coordinator, entry),
        UnipolSaiAnnualPremiumSensor(coordinator, entry),
        UnipolSaiNextRataSensor(coordinator, entry),
        # Statistiche di guida (vehicleUsages)
        UnipolSaiTotalDistanceSensor(coordinator, entry),
        UnipolSaiTotalDrivingTimeSensor(coordinator, entry),
        UnipolSaiCityDistanceSensor(coordinator, entry),
        UnipolSaiExtraUrbanDistanceSensor(coordinator, entry),
        UnipolSaiHighwayDistanceSensor(coordinator, entry),
        UnipolSaiNightDrivingDistanceSensor(coordinator, entry),
    ])


class _BaseSensor(CoordinatorEntity, SensorEntity):
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


# ==============================================================
# Sensori GPS
# ==============================================================

class UnipolSaiSpeedSensor(_BaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_speed"
        self._attr_name = f"Velocità {coordinator.targa}"
        self._attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR
        self._attr_icon = "mdi:speedometer"
        self._attr_device_class = SensorDeviceClass.SPEED

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("speed")


class UnipolSaiAddressSensor(_BaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_address"
        self._attr_name = f"Posizione {coordinator.targa}"
        self._attr_icon = "mdi:map-marker"

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        address = data.get("address", "")
        zipcode = data.get("zipCode", "")
        return f"{address}, {zipcode}".strip(", ") or None


class UnipolSaiGeocodedAddressSensor(_BaseSensor):
    """Indirizzo leggibile via reverse geocoding OpenStreetMap."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_geocoded_address"
        self._attr_name = f"Indirizzo {coordinator.targa}"
        self._attr_icon = "mdi:map-marker-check"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.geocoded_address


class UnipolSaiCarFinderCreditsSensor(_BaseSensor):
    """Crediti Car Finder disponibili oggi."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_car_finder_credits"
        self._attr_name = f"Crediti Car Finder {coordinator.targa}"
        self._attr_icon = "mdi:credit-card-check"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.available_credits

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "crediti_usati": self.coordinator.used_credits,
            "crediti_totali": self.coordinator.max_credits,
        }


class UnipolSaiHeadingSensor(_BaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_heading"
        self._attr_name = f"Direzione {coordinator.targa}"
        self._attr_icon = "mdi:compass"

    @property
    def native_value(self):
        heading = (self.coordinator.data or {}).get("heading")
        return DIREZIONE_MAP.get(heading, heading) if heading else None


class UnipolSaiLastUpdateSensor(_BaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_last_update"
        self._attr_name = f"Ultimo aggiornamento GPS {coordinator.targa}"
        self._attr_icon = "mdi:clock-outline"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        ts = (self.coordinator.data or {}).get("date")
        if ts:
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return None


class UnipolSaiSpeedLimitSensor(_BaseSensor):
    """Limite di velocità impostato sulla scatola nera (km/h). None = disattivo."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_speed_limit"
        self._attr_name = f"Limite velocità {coordinator.targa}"
        self._attr_icon = "mdi:speedometer-slow"
        self._attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR

    @property
    def native_value(self):
        sl = self.coordinator.speed_limit_data
        if not sl:
            return None
        # La struttura esatta dipende dall'API — proviamo i campi più comuni
        return sl.get("speedLimit") or sl.get("speed") or sl.get("value")

    @property
    def extra_state_attributes(self) -> dict:
        sl = self.coordinator.speed_limit_data or {}
        return {"stato": sl.get("status"), "raw": sl}


# ==============================================================
# Sensori Target Area
# ==============================================================

class UnipolSaiTargetAreaStatusSensor(_BaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_target_area_status"
        self._attr_name = f"Zona consentita {coordinator.targa}"
        self._attr_icon = "mdi:map-marker-radius"

    @property
    def native_value(self) -> str:
        ta = self.coordinator.target_area
        if not ta:
            return "non configurata"
        return "attiva" if ta.get("status") == "active" else "disattivata"

    @property
    def extra_state_attributes(self) -> dict:
        ta = self.coordinator.target_area or {}
        lat, lon = ta.get("lat"), ta.get("lon")
        return {
            "latitudine": lat,
            "longitudine": lon,
            "raggio_m": ta.get("radius"),
            "maps_url": f"https://www.google.com/maps?q={lat},{lon}" if lat and lon else None,
        }


class UnipolSaiTargetAreaRadiusSensor(_BaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_target_area_radius"
        self._attr_name = f"Raggio zona {coordinator.targa}"
        self._attr_icon = "mdi:radius-outline"
        self._attr_native_unit_of_measurement = "m"

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.target_area or {}).get("radius")


# ==============================================================
# Sensori Contratto
# ==============================================================

class _ContractBaseSensor(_BaseSensor):
    @property
    def _cd(self) -> dict:
        return self.coordinator.contract_data or {}

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.contract_data)


class UnipolSaiContractNumberSensor(_ContractBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_contract_number"
        self._attr_name = f"Numero polizza {coordinator.targa}"
        self._attr_icon = "mdi:file-document"

    @property
    def native_value(self) -> str | None:
        return self._cd.get("numero_contratto")

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "stato": self._cd.get("stato"),
            "agenzia": self._cd.get("agenzia"),
            "frazionamento": self._cd.get("frazionamento"),
        }


class UnipolSaiContractExpirySensor(_ContractBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_contract_expiry"
        self._attr_name = f"Scadenza polizza {coordinator.targa}"
        self._attr_icon = "mdi:calendar-alert"
        self._attr_device_class = SensorDeviceClass.DATE

    @property
    def native_value(self):
        val = self._cd.get("data_scadenza")
        if val:
            try:
                return datetime.strptime(val, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return val
        return None

    @property
    def extra_state_attributes(self) -> dict:
        val = self._cd.get("data_scadenza")
        giorni = None
        if val:
            try:
                giorni = (datetime.strptime(val, "%Y-%m-%d").date() - date.today()).days
            except (ValueError, TypeError):
                pass
        return {
            "data_effetto": self._cd.get("data_effetto"),
            "giorni_alla_scadenza": giorni,
        }


class UnipolSaiAnnualPremiumSensor(_ContractBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_annual_premium"
        self._attr_name = f"Premio annuo lordo {coordinator.targa}"
        self._attr_icon = "mdi:cash"
        self._attr_native_unit_of_measurement = "€"

    @property
    def native_value(self) -> float | None:
        return self._cd.get("premio_lordo_annuo")

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "premio_rca": self._cd.get("premio_rca"),
            "premio_furto": self._cd.get("premio_furto"),
            "premio_incendio": self._cd.get("premio_incendio"),
        }


class UnipolSaiNextRataSensor(_ContractBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_next_rata"
        self._attr_name = f"Prossima rata {coordinator.targa}"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_device_class = SensorDeviceClass.DATE

    @property
    def native_value(self):
        val = self._cd.get("prossima_rata")
        if val:
            try:
                return datetime.strptime(val, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return val
        return None


# ==============================================================
# Statistiche utilizzo veicolo (vehicleUsages, dateRange=g)
# Distanze in metri → convertiamo in km
# Tempi in secondi → convertiamo in ore
# ==============================================================

class _UsageSensor(_BaseSensor):
    """Base per sensori vehicleUsages."""

    @property
    def _vu(self) -> dict:
        return self.coordinator.vehicle_usages or {}

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.vehicle_usages)

    @staticmethod
    def _m_to_km(meters) -> float | None:
        """Converti metri in km con 1 decimale."""
        if meters is None:
            return None
        return round(meters / 1000, 1)

    @staticmethod
    def _s_to_h(seconds) -> float | None:
        """Converti secondi in ore con 1 decimale."""
        if seconds is None:
            return None
        return round(seconds / 3600, 1)


class UnipolSaiTotalDistanceSensor(_UsageSensor):
    """Distanza totale percorsa nel periodo contrattuale."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_total_distance"
        self._attr_name = f"Distanza totale {coordinator.targa}"
        self._attr_icon = "mdi:map-marker-distance"
        self._attr_native_unit_of_measurement = "km"

    @property
    def native_value(self) -> float | None:
        return self._m_to_km(self._vu.get("totalDistance"))

    @property
    def extra_state_attributes(self) -> dict:
        vu = self._vu
        from datetime import datetime
        from_ts = vu.get("fromDate")
        to_ts = vu.get("statisticsDate")
        return {
            "dal": datetime.fromtimestamp(from_ts / 1000).strftime("%d/%m/%Y") if from_ts else None,
            "al": datetime.fromtimestamp(to_ts / 1000).strftime("%d/%m/%Y") if to_ts else None,
            "giorni_analizzati": vu.get("totalDaysUsedForAnalysis"),
            "provincia_principale": vu.get("higherMileageProvinceFullName"),
            "lun_km": self._m_to_km(vu.get("mondayDrivingDistance")),
            "mar_km": self._m_to_km(vu.get("tuesdayDrivingDistance")),
            "mer_km": self._m_to_km(vu.get("wednesdayDrivingDistance")),
            "gio_km": self._m_to_km(vu.get("thursdayDrivingDistance")),
            "ven_km": self._m_to_km(vu.get("fridayDrivingDistance")),
            "sab_km": self._m_to_km(vu.get("saturdayDrivingDistance")),
            "dom_km": self._m_to_km(vu.get("sundayDrivingDistance")),
        }


class UnipolSaiTotalDrivingTimeSensor(_UsageSensor):
    """Tempo di guida totale nel periodo contrattuale (ore)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_total_driving_time"
        self._attr_name = f"Tempo di guida totale {coordinator.targa}"
        self._attr_icon = "mdi:steering"
        self._attr_native_unit_of_measurement = UnitOfTime.HOURS

    @property
    def native_value(self) -> float | None:
        return self._s_to_h(self._vu.get("totalDrivingTime"))

    @property
    def extra_state_attributes(self) -> dict:
        vu = self._vu
        return {
            "ore_diurne": self._s_to_h(vu.get("daylightDrivingTime")),
            "ore_notturne": self._s_to_h(
                (vu.get("totalDrivingTime") or 0) - (vu.get("daylightDrivingTime") or 0)
            ),
            "ore_citta": self._s_to_h(vu.get("cityDrivingTime")),
            "ore_extraurbano": self._s_to_h(vu.get("extraUrbanDrivingTime")),
            "ore_autostrada": self._s_to_h(vu.get("highwayDrivingTime")),
            "lun_h": self._s_to_h(vu.get("mondayDrivingTime")),
            "mar_h": self._s_to_h(vu.get("tuesdayDrivingTime")),
            "mer_h": self._s_to_h(vu.get("wednesdayDrivingTime")),
            "gio_h": self._s_to_h(vu.get("thursdayDrivingTime")),
            "ven_h": self._s_to_h(vu.get("fridayDrivingTime")),
            "sab_h": self._s_to_h(vu.get("saturdayDrivingTime")),
            "dom_h": self._s_to_h(vu.get("sundayDrivingTime")),
        }


class UnipolSaiCityDistanceSensor(_UsageSensor):
    """Distanza percorsa in città."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_city_distance"
        self._attr_name = f"Km città {coordinator.targa}"
        self._attr_icon = "mdi:city"
        self._attr_native_unit_of_measurement = "km"

    @property
    def native_value(self) -> float | None:
        return self._m_to_km(self._vu.get("cityDrivingDistance"))


class UnipolSaiExtraUrbanDistanceSensor(_UsageSensor):
    """Distanza percorsa in extraurbano."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_extraurban_distance"
        self._attr_name = f"Km extraurbano {coordinator.targa}"
        self._attr_icon = "mdi:road"
        self._attr_native_unit_of_measurement = "km"

    @property
    def native_value(self) -> float | None:
        return self._m_to_km(self._vu.get("extraUrbanDrivingDistance"))


class UnipolSaiHighwayDistanceSensor(_UsageSensor):
    """Distanza percorsa in autostrada."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_highway_distance"
        self._attr_name = f"Km autostrada {coordinator.targa}"
        self._attr_icon = "mdi:highway"
        self._attr_native_unit_of_measurement = "km"

    @property
    def native_value(self) -> float | None:
        return self._m_to_km(self._vu.get("highwayDrivingDistance"))


class UnipolSaiNightDrivingDistanceSensor(_UsageSensor):
    """Distanza percorsa di notte (totalDistance - daylightDrivingDistance)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"unipolsai_{coordinator.targa}_night_distance"
        self._attr_name = f"Km notturni {coordinator.targa}"
        self._attr_icon = "mdi:weather-night"
        self._attr_native_unit_of_measurement = "km"

    @property
    def native_value(self) -> float | None:
        vu = self._vu
        total = vu.get("totalDistance")
        daylight = vu.get("daylightDrivingDistance")
        if total is None or daylight is None:
            return None
        return self._m_to_km(total - daylight)
