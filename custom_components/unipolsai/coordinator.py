"""DataUpdateCoordinator per UnipolSai."""
import logging
import asyncio
import time
from datetime import timedelta, datetime

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    BASE_URL,
    LOGIN_URL,
    CONTRATTI_TELEMATICI_URL,
    LAST_POSITION_URL,
    LAST_NOTIFICATIONS_URL,
    LAST_TARGET_AREA_URL,
    MODIFY_TARGET_AREA_URL,
    ENABLE_VAS_URL,
    CONTRACT_URL,
    VEHICLE_USAGES_URL,
    SPEED_LIMIT_URL,
    MODIFY_SPEED_LIMIT_URL,
    NOMINATIM_URL,
    APP_HEADERS,
    DEFAULT_SCAN_INTERVAL,
    EVENT_CAR_MOVED_ENGINE_OFF,
    EVENT_TARGET_AREA_EXIT,
    EVENT_SPEED_LIMIT_EXCEEDED,
)

_LOGGER = logging.getLogger(__name__)

FAST_POLL_INTERVAL = timedelta(seconds=10)
PENDING_TIMEOUT = 300
CONTRACT_REFRESH_INTERVAL = 3600  # 1 ora
GEOCODE_CACHE_DISTANCE = 0.001    # ~100m: non ri-geocodifica se ci si sposta poco


class UnipolSaiCoordinator(DataUpdateCoordinator):

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        targa: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ):
        self.username = username
        self.password = password
        self.targa = targa.upper().replace(" ", "")
        self._token = None
        self._session: aiohttp.ClientSession | None = None
        self._normal_interval = timedelta(minutes=scan_interval)
        self._pending_since: float | None = None
        self._fast_polling_task: asyncio.Task | None = None

        # Notifiche
        self._last_seen_car_moved_id: str | None = None
        self.last_car_moved_notification: dict | None = None
        self._last_seen_target_area_notif_id: str | None = None
        self.last_target_area_notification: dict | None = None
        self._last_seen_speed_limit_notif_id: str | None = None
        self.last_speed_limit_notification: dict | None = None

        # Target area
        self.target_area: dict | None = None

        # Speed limit
        self.speed_limit_data: dict | None = None  # {"speedLimit": 90, "status": "active"}

        # Contratto (chiave scoperta automaticamente, aggiornata ogni ora)
        self.contract_data: dict | None = None
        self._chiave_contratto: str | None = None
        self._contract_last_fetch: float = 0.0

        # Statistiche uso
        self.vehicle_usages: dict | None = None

        # Reverse geocoding
        self.geocoded_address: str | None = None
        self._last_geocoded_lat: float | None = None
        self._last_geocoded_lon: float | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self._normal_interval,
        )

    # ------------------------------------------------------------------
    # HTTP session
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _login(self) -> str:
        session = await self._get_session()
        headers = {**APP_HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
        async with session.post(LOGIN_URL, headers=headers, data={"username": self.username, "password": self.password}) as resp:
            if resp.status != 200:
                raise UpdateFailed(f"Login fallito: HTTP {resp.status}")
            result = await resp.json(content_type=None)
        token = result.get("JWT", {}).get("token")
        if not token:
            raise UpdateFailed("Token JWT non trovato")
        return token

    async def _ensure_token(self) -> None:
        if not self._token:
            self._token = await self._login()

    def _auth_headers(self) -> dict:
        return {**APP_HEADERS, "Authorization": f"Bearer {self._token}"}

    # ------------------------------------------------------------------
    # Posizione GPS
    # ------------------------------------------------------------------

    async def _fetch_position(self, force_update: bool = False) -> dict:
        session = await self._get_session()
        url = LAST_POSITION_URL.format(targa=self.targa)
        headers = self._auth_headers()
        params = {"update": "true" if force_update else "false"}

        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 401:
                self._token = await self._login()
                headers = self._auth_headers()
                async with session.get(url, headers=headers, params=params) as r2:
                    result = await r2.json(content_type=None)
            elif resp.status != 200:
                raise UpdateFailed(f"Errore posizione: HTTP {resp.status}")
            else:
                result = await resp.json(content_type=None)

        if result.get("operationResult", {}).get("type") != 0:
            raise UpdateFailed(f"Errore API posizione: {result}")
        return result["lastPosition"]

    # ------------------------------------------------------------------
    # Reverse geocoding (Nominatim/OpenStreetMap)
    # ------------------------------------------------------------------

    async def _reverse_geocode(self, lat: float, lon: float) -> str | None:
        """Converte lat/lon in indirizzo leggibile tramite Nominatim."""
        # Non ri-geocodifica se l'auto non si è spostata significativamente
        if (
            self._last_geocoded_lat is not None
            and abs(lat - self._last_geocoded_lat) < GEOCODE_CACHE_DISTANCE
            and abs(lon - self._last_geocoded_lon) < GEOCODE_CACHE_DISTANCE
        ):
            return self.geocoded_address

        session = await self._get_session()
        try:
            async with session.get(
                NOMINATIM_URL,
                params={"lat": lat, "lon": lon, "format": "json", "accept-language": "it"},
                headers={"User-Agent": f"HomeAssistant-UnipolSai/{self.targa}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)

            addr = data.get("address", {})
            # Componi un indirizzo leggibile: via + numero + città
            parts = []
            road = addr.get("road") or addr.get("pedestrian") or addr.get("path")
            if road:
                parts.append(road)
            house = addr.get("house_number")
            if house:
                parts.append(house)
            city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
            if city:
                parts.append(city)
            province = addr.get("county") or addr.get("state_district")
            if province and province != city:
                parts.append(f"({province})")

            address = ", ".join(parts) if parts else data.get("display_name", "")
            self._last_geocoded_lat = lat
            self._last_geocoded_lon = lon
            self.geocoded_address = address
            return address

        except Exception as err:
            _LOGGER.debug("UnipolSai: reverse geocoding fallito: %s", err)
            return None

    # ------------------------------------------------------------------
    # Notifiche
    # ------------------------------------------------------------------

    async def _fetch_notifications(self, vas_type: str) -> list[dict]:
        session = await self._get_session()
        url = LAST_NOTIFICATIONS_URL.format(targa=self.targa)
        async with session.get(url, headers=self._auth_headers(), params={"vehicleVAS": vas_type}) as resp:
            if resp.status == 401:
                self._token = await self._login()
                async with session.get(url, headers=self._auth_headers(), params={"vehicleVAS": vas_type}) as r2:
                    result = await r2.json(content_type=None)
            elif resp.status != 200:
                return []
            else:
                result = await resp.json(content_type=None)
        if result.get("operationResult", {}).get("type") != 0:
            return []
        return result.get("serviceNotifications", [])

    async def _check_car_moved_notifications(self) -> None:
        try:
            notifications = await self._fetch_notifications("carMovedEngineOff")
        except Exception as err:
            _LOGGER.error("UnipolSai: errore check carMoved: %s", err)
            return
        if not notifications:
            return
        latest = notifications[0]
        latest_id = latest.get("id")
        if self._last_seen_car_moved_id is None:
            self._last_seen_car_moved_id = latest_id
            self.last_car_moved_notification = latest
            return
        if latest_id != self._last_seen_car_moved_id:
            self._last_seen_car_moved_id = latest_id
            self.last_car_moved_notification = latest
            lat, lon = latest.get("latitude"), latest.get("longitude")
            event_dt = self._fmt_ts(latest.get("eventDate", 0))
            self.hass.bus.async_fire(EVENT_CAR_MOVED_ENGINE_OFF, {
                "targa": self.targa, "latitude": lat, "longitude": lon,
                "speed_kmh": latest.get("speed"), "event_date": event_dt,
                "notification_id": latest_id,
            })
            self.hass.components.persistent_notification.async_create(
                title=f"⚠️ Auto {self.targa} spostata a motore spento!",
                message=f"**Data:** {event_dt}\n**Velocità:** {latest.get('speed')} km/h\n**Posizione:** [Mappa](https://www.google.com/maps?q={lat},{lon})",
                notification_id=f"unipolsai_car_moved_{latest_id}",
            )

    async def _check_target_area_notifications(self) -> None:
        try:
            notifications = await self._fetch_notifications("targetArea")
        except Exception as err:
            _LOGGER.error("UnipolSai: errore check targetArea: %s", err)
            return
        if not notifications:
            return
        latest = notifications[0]
        latest_id = latest.get("id")
        if self._last_seen_target_area_notif_id is None:
            self._last_seen_target_area_notif_id = latest_id
            self.last_target_area_notification = latest
            return
        if latest_id != self._last_seen_target_area_notif_id:
            self._last_seen_target_area_notif_id = latest_id
            self.last_target_area_notification = latest
            lat, lon = latest.get("latitude"), latest.get("longitude")
            event_dt = self._fmt_ts(latest.get("eventDate", 0))
            self.hass.bus.async_fire(EVENT_TARGET_AREA_EXIT, {
                "targa": self.targa, "latitude": lat, "longitude": lon,
                "speed_kmh": latest.get("speed"), "event_date": event_dt,
                "notification_id": latest_id,
            })
            self.hass.components.persistent_notification.async_create(
                title=f"🚨 Auto {self.targa} uscita dalla zona!",
                message=f"**Data:** {event_dt}\n**Velocità:** {latest.get('speed')} km/h\n**Posizione:** [Mappa](https://www.google.com/maps?q={lat},{lon})",
                notification_id=f"unipolsai_target_area_{latest_id}",
            )

    async def _check_speed_limit_notifications(self) -> None:
        try:
            notifications = await self._fetch_notifications("speedLimit")
        except Exception as err:
            _LOGGER.error("UnipolSai: errore check speedLimit: %s", err)
            return
        if not notifications:
            return
        latest = notifications[0]
        latest_id = latest.get("id")
        if self._last_seen_speed_limit_notif_id is None:
            self._last_seen_speed_limit_notif_id = latest_id
            self.last_speed_limit_notification = latest
            return
        if latest_id != self._last_seen_speed_limit_notif_id:
            self._last_seen_speed_limit_notif_id = latest_id
            self.last_speed_limit_notification = latest
            lat, lon = latest.get("latitude"), latest.get("longitude")
            event_dt = self._fmt_ts(latest.get("eventDate", 0))
            self.hass.bus.async_fire(EVENT_SPEED_LIMIT_EXCEEDED, {
                "targa": self.targa, "latitude": lat, "longitude": lon,
                "speed_kmh": latest.get("speed"),
                "speed_limit_kmh": latest.get("speedLimitValue"),
                "event_date": event_dt, "notification_id": latest_id,
            })
            self.hass.components.persistent_notification.async_create(
                title=f"🚨 Auto {self.targa} ha superato il limite di velocità!",
                message=f"**Data:** {event_dt}\n**Velocità:** {latest.get('speed')} km/h\n**Limite:** {latest.get('speedLimitValue')} km/h\n**Posizione:** [Mappa](https://www.google.com/maps?q={lat},{lon})",
                notification_id=f"unipolsai_speed_limit_{latest_id}",
            )

    # ------------------------------------------------------------------
    # Target Area
    # ------------------------------------------------------------------

    async def _fetch_target_area(self) -> dict | None:
        session = await self._get_session()
        url = LAST_TARGET_AREA_URL.format(targa=self.targa)
        async with session.get(url, headers=self._auth_headers()) as resp:
            if resp.status == 401:
                self._token = await self._login()
                async with session.get(url, headers=self._auth_headers()) as r2:
                    result = await r2.json(content_type=None)
            elif resp.status != 200:
                return None
            else:
                result = await resp.json(content_type=None)
        if result.get("operationResult", {}).get("type") != 0:
            return None
        areas = result.get("targetArea", [])
        if isinstance(areas, list) and areas:
            return areas[0]
        if isinstance(areas, dict):
            return areas
        return None

    async def async_set_target_area(self, lat: float, lon: float, radius: int, active: bool = True) -> bool:
        await self._ensure_token()
        session = await self._get_session()
        enable_url = ENABLE_VAS_URL.format(targa=self.targa, vas="targetArea")
        try:
            async with session.post(enable_url, headers={**self._auth_headers(), "Content-Type": "application/json"}, json={"enable": "true"}) as resp:
                pass
        except Exception:
            pass
        modify_url = MODIFY_TARGET_AREA_URL.format(targa=self.targa)
        payload = {"status": "active" if active else "notActive", "lat": lat, "lon": lon, "radius": radius}
        try:
            async with session.post(modify_url, headers={**self._auth_headers(), "Content-Type": "application/json"}, json=payload) as resp:
                result = await resp.json(content_type=None)
                if result.get("operationResult", {}).get("type") == 0:
                    self.target_area = result.get("targetArea", payload)
                    self.async_update_listeners()
                    return True
        except Exception as err:
            _LOGGER.error("UnipolSai: errore set targetArea: %s", err)
        return False

    async def async_disable_target_area(self) -> bool:
        if not self.target_area:
            return False
        return await self.async_set_target_area(
            lat=self.target_area.get("lat", 0),
            lon=self.target_area.get("lon", 0),
            radius=int(self.target_area.get("radius", 250)),
            active=False,
        )

    # ------------------------------------------------------------------
    # Speed Limit
    # ------------------------------------------------------------------

    async def _fetch_speed_limit(self) -> dict | None:
        session = await self._get_session()
        url = SPEED_LIMIT_URL.format(targa=self.targa)
        try:
            async with session.get(url, headers=self._auth_headers()) as resp:
                if resp.status == 401:
                    self._token = await self._login()
                    async with session.get(url, headers=self._auth_headers()) as r2:
                        result = await r2.json(content_type=None)
                elif resp.status != 200:
                    return None
                else:
                    result = await resp.json(content_type=None)
            if result.get("operationResult", {}).get("type") != 0:
                return None
            return result.get("speedLimit") or result.get("lastSpeedLimit")
        except Exception as err:
            _LOGGER.debug("UnipolSai: errore fetch speedLimit: %s", err)
            return None

    async def async_set_speed_limit(self, speed_limit: int) -> bool:
        """Imposta il limite di velocità (50-150 km/h). 0 = disattiva."""
        await self._ensure_token()
        session = await self._get_session()

        # Abilita il servizio
        enable_url = ENABLE_VAS_URL.format(targa=self.targa, vas="speedLimit")
        try:
            async with session.post(enable_url, headers={**self._auth_headers(), "Content-Type": "application/json"}, json={"enable": "true"}) as resp:
                pass
        except Exception:
            pass

        # Imposta il limite
        modify_url = MODIFY_SPEED_LIMIT_URL.format(targa=self.targa)
        try:
            async with session.post(
                modify_url,
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                json={"speedLimit": speed_limit},
            ) as resp:
                result = await resp.json(content_type=None)
                if result.get("operationResult", {}).get("type") == 0:
                    _LOGGER.info("UnipolSai: speed limit impostato a %d km/h", speed_limit)
                    self.async_update_listeners()
                    return True
        except Exception as err:
            _LOGGER.error("UnipolSai: errore set speedLimit: %s", err)
        return False

    # ------------------------------------------------------------------
    # Contratto
    # ------------------------------------------------------------------

    async def _fetch_contract_data(self) -> dict | None:
        now = time.monotonic()
        if now - self._contract_last_fetch < CONTRACT_REFRESH_INTERVAL and self.contract_data:
            return self.contract_data

        session = await self._get_session()

        if not self._chiave_contratto:
            try:
                async with session.get(CONTRATTI_TELEMATICI_URL, headers=self._auth_headers()) as resp:
                    if resp.status != 200:
                        return None
                    result = await resp.json(content_type=None)
                contratti = result.get("auto", {}).get("contrattiAuto", [])
                if not contratti:
                    return None

                polizze_url = f"{BASE_URL}/hub/api/priv/contratti/v2/me/polizze"
                for params in [{"targa": self.targa}, {}]:
                    async with session.get(polizze_url, headers=self._auth_headers(), params=params) as resp2:
                        if resp2.status == 200:
                            pol = await resp2.json(content_type=None)
                            for p in pol.get("polizze", []) or []:
                                targa_p = (p.get("targaVeicolo") or "").replace(" ", "").upper()
                                if targa_p == self.targa or (not targa_p and str(p.get("comparto", "")) in ("1001", "1000")):
                                    chiave = p.get("chiaveContratto")
                                    if chiave:
                                        self._chiave_contratto = chiave
                                        break
                    if self._chiave_contratto:
                        break
            except Exception as err:
                _LOGGER.error("UnipolSai: errore recupero chiave contratto: %s", err)
                return None

        if not self._chiave_contratto:
            return None

        url = CONTRACT_URL.format(chiave_contratto=self._chiave_contratto)
        params = {
            "chiaveContratto": self._chiave_contratto,
            "sistemaContratto": "CRM",
            "ruoloContraente": "1001",
            "comparto": "1001",
            "targa": self.targa,
            "statoTitolo": "A",
            "btnProseguiOnline": "false",
        }
        try:
            async with session.get(url, headers=self._auth_headers(), params=params) as resp:
                if resp.status == 401:
                    self._token = await self._login()
                    async with session.get(url, headers=self._auth_headers(), params=params) as r2:
                        result = await r2.json(content_type=None)
                elif resp.status != 200:
                    return None
                else:
                    result = await resp.json(content_type=None)
            self._contract_last_fetch = time.monotonic()
            return self._parse_contract(result)
        except Exception as err:
            _LOGGER.error("UnipolSai: errore fetch contratto: %s", err)
            return None

    def _parse_contract(self, raw: dict) -> dict:
        import json as _json
        tpd = raw.get("rispostaTpdData", {}) or {}
        det_auto = tpd.get("dettagliAuto", {}) or {}
        pagamenti = tpd.get("dettagliPagamenti", {}) or {}
        garanzie = {g.get("nome", ""): g for g in det_auto.get("garanziaCvtArd", [])}
        rca_list = det_auto.get("garanziaRca", [{}])
        rca = rca_list[0] if rca_list else {}
        tempo_percorrenza = None
        try:
            unibox_raw = raw.get("unibox", {}).get("autoMoto", {}).get("valore", "")
            if unibox_raw:
                unibox_data = _json.loads(unibox_raw)
                val = unibox_data.get("tempoDiPercorrenza")
                if val is not None:
                    tempo_percorrenza = int(val)
        except Exception:
            pass
        return {
            "numero_contratto": f"{tpd.get('ramo', '')}/{tpd.get('polizza', '')}",
            "stato": (raw.get("stati") or ["N/D"])[0],
            "data_effetto": tpd.get("dataEffetto"),
            "data_scadenza": tpd.get("dataScadenza"),
            "premio_lordo_annuo": det_auto.get("premioLordo"),
            "prossima_rata": pagamenti.get("calendarioRate", [None])[0] if pagamenti.get("calendarioRate") else None,
            "premio_rca": rca.get("premioNetto"),
            "premio_furto": garanzie.get("Furto", {}).get("premioNetto"),
            "premio_incendio": garanzie.get("Incendio", {}).get("premioNetto"),
            "tempo_di_percorrenza": tempo_percorrenza,
            "agenzia": tpd.get("descrizioneAgenzia"),
            "frazionamento": tpd.get("descFrazionamento") or pagamenti.get("descFrazionamento"),
        }

    # ------------------------------------------------------------------
    # Vehicle Usages
    # ------------------------------------------------------------------

    async def _fetch_vehicle_usages(self) -> dict | None:
        session = await self._get_session()
        url = VEHICLE_USAGES_URL.format(targa=self.targa)
        try:
            async with session.get(url, headers=self._auth_headers(), params={"dateRange": "g"}) as resp:
                if resp.status == 401:
                    self._token = await self._login()
                    async with session.get(url, headers=self._auth_headers(), params={"dateRange": "g"}) as r2:
                        result = await r2.json(content_type=None)
                elif resp.status != 200:
                    return None
                else:
                    result = await resp.json(content_type=None)
            if result.get("operationResult", {}).get("type") != 0:
                return None
            usages = result.get("vehicleUsages", [])
            return usages[0] if usages else None
        except Exception as err:
            _LOGGER.error("UnipolSai: errore vehicleUsages: %s", err)
            return None

    # ------------------------------------------------------------------
    # GPS live update (button)
    # ------------------------------------------------------------------

    async def async_request_live_position(self) -> None:
        await self._ensure_token()
        position = await self._fetch_position(force_update=True)
        self.async_set_updated_data(position)
        if position.get("pendingRequest"):
            self._start_fast_polling()

    def _start_fast_polling(self) -> None:
        self._pending_since = time.monotonic()
        if self._fast_polling_task and not self._fast_polling_task.done():
            self._fast_polling_task.cancel()
        self._fast_polling_task = self.hass.async_create_task(self._fast_poll_loop())

    async def _fast_poll_loop(self) -> None:
        while True:
            await asyncio.sleep(FAST_POLL_INTERVAL.seconds)
            elapsed = time.monotonic() - (self._pending_since or 0)
            if elapsed > PENDING_TIMEOUT:
                self._pending_since = None
                break
            try:
                await self._ensure_token()
                position = await self._fetch_position(force_update=False)
                self.async_set_updated_data(position)
                if not position.get("pendingRequest", False):
                    self._pending_since = None
                    break
            except Exception as err:
                _LOGGER.error("UnipolSai: errore fast poll: %s", err)
                self._pending_since = None
                break

    # ------------------------------------------------------------------
    # Main update cycle
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        if self._fast_polling_task and not self._fast_polling_task.done():
            await self._ensure_token()
            await asyncio.gather(
                self._check_car_moved_notifications(),
                self._check_target_area_notifications(),
                self._check_speed_limit_notifications(),
            )
            return self.data or {}

        try:
            await self._ensure_token()
            position, target_area, speed_limit, contract, usages, _, _, _ = await asyncio.gather(
                self._fetch_position(force_update=False),
                self._fetch_target_area(),
                self._fetch_speed_limit(),
                self._fetch_contract_data(),
                self._fetch_vehicle_usages(),
                self._check_car_moved_notifications(),
                self._check_target_area_notifications(),
                self._check_speed_limit_notifications(),
                return_exceptions=False,
            )
            if target_area is not None:
                self.target_area = target_area
            if speed_limit is not None:
                self.speed_limit_data = speed_limit
            if contract is not None:
                self.contract_data = contract
            if usages is not None:
                self.vehicle_usages = usages

            # Reverse geocoding in background (non blocca l'update)
            lat = position.get("lat")
            lon = position.get("lon")
            if lat and lon:
                self.hass.async_create_task(self._reverse_geocode(lat, lon))

            return position
        except UpdateFailed:
            raise
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Errore di rete: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Errore imprevisto: {err}") from err

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_pending(self) -> bool:
        return (
            self._pending_since is not None
            or (self.data or {}).get("pendingRequest", False)
        )

    @property
    def available_credits(self) -> int | None:
        fruizioni = (self.data or {}).get("dailyFruitions", {})
        if fruizioni:
            return fruizioni.get("max", 5) - fruizioni.get("current", 0)
        return None

    @property
    def used_credits(self) -> int | None:
        return (self.data or {}).get("dailyFruitions", {}).get("current")

    @property
    def max_credits(self) -> int | None:
        return (self.data or {}).get("dailyFruitions", {}).get("max")

    @property
    def target_area_active(self) -> bool:
        return (self.target_area or {}).get("status") == "active"

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_ts(ts_ms: int) -> str:
        if not ts_ms:
            return "N/A"
        return datetime.fromtimestamp(ts_ms / 1000).strftime("%d/%m/%Y %H:%M:%S")

    async def async_close(self):
        if self._fast_polling_task and not self._fast_polling_task.done():
            self._fast_polling_task.cancel()
        if self._session and not self._session.closed:
            await self._session.close()
