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
        self._contract_extra_params: dict = {}
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

            # Parte 1: via/strada (urban) oppure strada/località (rurale)
            road = (
                addr.get("road")
                or addr.get("pedestrian")
                or addr.get("path")
                or addr.get("highway")
                or addr.get("motorway")
                or addr.get("trunk")
            )
            house = addr.get("house_number")

            # Parte 2: frazione/quartiere (utile in aree rurali)
            locality = (
                addr.get("suburb")
                or addr.get("quarter")
                or addr.get("neighbourhood")
                or addr.get("hamlet")
                or addr.get("isolated_dwelling")
                or addr.get("locality")
            )

            # Parte 3: comune
            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("municipality")
            )

            # Parte 4: provincia abbreviata
            province = addr.get("county") or addr.get("state_district") or addr.get("state")

            # Costruisci l'indirizzo dal più al meno specifico
            parts = []
            if road:
                parts.append(f"{road} {house}".strip() if house else road)
            if locality and locality != city:
                parts.append(locality)
            if city:
                parts.append(city)
            if province and province not in parts:
                # Abbrevia la provincia se termina con "Provincia di ..."
                prov_short = province.replace("Provincia di ", "").replace("Città Metropolitana di ", "")
                parts.append(f"({prov_short})")

            if parts:
                address = ", ".join(parts)
            else:
                # Fallback: usa i primi 3 segmenti del display_name di Nominatim
                # che sono tipicamente: nome_luogo, comune, provincia
                display = data.get("display_name", "")
                segments = [s.strip() for s in display.split(",")]
                address = ", ".join(segments[:3]) if segments else display

            self._last_geocoded_lat = lat
            self._last_geocoded_lon = lon
            self.geocoded_address = address
            _LOGGER.debug("UnipolSai: geocoding %s,%s → %s", lat, lon, address)
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

        # ------------------------------------------------------------------
        # Step 1: GET /contesto-utente/v2/me/polizze
        # Chiamato dall'app all'avvio — restituisce le polizze con
        # chiaveContratto e i campi per costruire il body del passo 2.
        # ------------------------------------------------------------------
        if not self._chiave_contratto:
            polizze_url = f"{BASE_URL}/hub/api/priv/contesto-utente/v2/me/polizze"
            try:
                async with session.get(polizze_url, headers=self._auth_headers()) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("UnipolSai contratto: /me/polizze HTTP %d", resp.status)
                        return None
                    data = await resp.json(content_type=None)

                polizze = data.get("polizze", []) if isinstance(data, dict) else data
                polizza_raw = None
                for p in polizze:
                    targa_p = (p.get("targaVeicolo") or "").replace(" ", "").upper()
                    if targa_p == self.targa and p.get("chiaveContratto"):
                        polizza_raw = p
                        self._chiave_contratto = str(p["chiaveContratto"])
                        break

                if not polizza_raw:
                    _LOGGER.warning("UnipolSai contratto: targa %s non trovata in /me/polizze", self.targa)
                    return None

                # ----------------------------------------------------------
                # Step 2: POST /contratti/v2/polizze/titolo/recuperoTitoli
                # Restituisce timbroEffettivoPagamento e altri campi necessari
                # per la chiamata di dettaglio.
                # ----------------------------------------------------------
                from datetime import datetime as _dt
                scadenza_ts = polizza_raw.get("dataScadenza")
                scadenza_str = _dt.fromtimestamp(scadenza_ts / 1000).strftime("%Y-%m-%d") if scadenza_ts else ""

                recupero_url = f"{BASE_URL}/hub/api/priv/contratti/v2/polizze/titolo/recuperoTitoli"
                recupero_body = {
                    "ListaPolizza": [{
                        "IdPolizza": polizza_raw.get("polizza", ""),
                        "Compagnia": polizza_raw.get("exdivisione", "1"),
                        "AgenziaMadre": polizza_raw.get("agenzia", ""),
                        "AgenziaFiglia": polizza_raw.get("agenzia", ""),
                        "RamoPolizza": polizza_raw.get("ramo", "030"),
                        "DataScadenzaPolizza": scadenza_str,
                        "Targa": self.targa,
                    }],
                    "ListaFolder": [],
                }

                timbro = ""
                try:
                    async with session.post(
                        recupero_url,
                        headers={**self._auth_headers(), "Content-Type": "application/json"},
                        json=recupero_body,
                    ) as resp2:
                        if resp2.status == 200:
                            r2data = await resp2.json(content_type=None)
                            titoli = r2data.get("listaPolizza", [])
                            if titoli:
                                timbro = titoli[0].get("timbroEffettivoPagamento", "") or ""
                        else:
                            _LOGGER.debug("UnipolSai contratto: recuperoTitoli HTTP %d", resp2.status)
                except Exception as err:
                    _LOGGER.debug("UnipolSai contratto: recuperoTitoli errore: %s", err)

                self._contract_extra_params = {
                    "polizzaNum": polizza_raw.get("polizza", ""),
                    "dataScadenzaPolizza": scadenza_str,
                    "timbroEffettivoPagamento": timbro,
                    "ruoloContraente": str(polizza_raw.get("ruoloContraente", "1001")),
                    "comparto": str(polizza_raw.get("comparto", "1001")),
                }
                _LOGGER.info(
                    "UnipolSai contratto: chiave=%s polizza=%s scadenza=%s",
                    self._chiave_contratto,
                    polizza_raw.get("polizza"),
                    scadenza_str,
                )

            except Exception as err:
                _LOGGER.warning("UnipolSai contratto: errore discovery: %s", err)
                return None

        if not self._chiave_contratto:
            _LOGGER.warning("UnipolSai contratto: chiaveContratto non trovata per targa %s", self.targa)
            return None

        # ------------------------------------------------------------------
        # Step 3: GET /contratti/v4/polizze/{chiave} — dettaglio contratto
        # ------------------------------------------------------------------
        url = CONTRACT_URL.format(chiave_contratto=self._chiave_contratto)
        extra = self._contract_extra_params
        params = {
            "chiaveContratto": self._chiave_contratto,
            "sistemaContratto": "CRM",
            "ruoloContraente": extra.get("ruoloContraente", "1001"),
            "comparto": extra.get("comparto", "1001"),
            "dataScadenzaPolizza": extra.get("dataScadenzaPolizza", ""),
            "timbroEffettivoPagamento": extra.get("timbroEffettivoPagamento", ""),
            "polizzaNum": extra.get("polizzaNum", ""),
            "statoTitolo": "A",
            "btnProseguiOnline": "false",
            "targa": self.targa,
        }
        try:
            async with session.get(url, headers=self._auth_headers(), params=params) as resp:
                if resp.status == 401:
                    self._token = await self._login()
                    async with session.get(url, headers=self._auth_headers(), params=params) as r2:
                        result = await r2.json(content_type=None)
                elif resp.status != 200:
                    _LOGGER.warning(
                        "UnipolSai contratto: dettaglio HTTP %d chiave=%s",
                        resp.status, self._chiave_contratto,
                    )
                    return None
                else:
                    result = await resp.json(content_type=None)
            self._contract_last_fetch = time.monotonic()
            return self._parse_contract(result)
        except Exception as err:
            _LOGGER.error("UnipolSai contratto: errore fetch dettaglio: %s", err)
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
    # Vehicle Usages con periodo selezionabile
    # ------------------------------------------------------------------

    async def _fetch_vehicle_usages(
        self,
        start_date: int | None = None,
        end_date: int | None = None,
    ) -> dict | None:
        """Recupera le statistiche di utilizzo.
        
        Se start_date/end_date sono None usa dateRange=g (inizio contratto → oggi).
        Altrimenti usa dateRange=t con le date specificate (timestamp Unix ms).
        """
        session = await self._get_session()
        url = VEHICLE_USAGES_URL.format(targa=self.targa)
        if start_date and end_date:
            params = {"dateRange": "t", "startDate": start_date, "endDate": end_date}
        else:
            params = {"dateRange": "g"}
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
            if result.get("operationResult", {}).get("type") != 0:
                return None
            usages = result.get("vehicleUsages", [])
            return usages[0] if usages else None
        except Exception as err:
            _LOGGER.error("UnipolSai: errore vehicleUsages: %s", err)
            return None

    async def async_set_usages_period(
        self, start_date: str, end_date: str
    ) -> bool:
        """Imposta il periodo delle statistiche (formato YYYY-MM-DD).
        
        Aggiorna i sensori vehicleUsages per il periodo specificato.
        """
        await self._ensure_token()
        try:
            from datetime import datetime as _dt
            start_ts = int(_dt.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
            end_ts = int(_dt.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)
        except ValueError as err:
            _LOGGER.error("UnipolSai: formato data non valido: %s", err)
            return False

        usages = await self._fetch_vehicle_usages(start_date=start_ts, end_date=end_ts)
        if usages is not None:
            self.vehicle_usages = usages
            self.async_update_listeners()
            _LOGGER.info(
                "UnipolSai: statistiche aggiornate per il periodo %s → %s",
                start_date, end_date,
            )
            return True
        return False

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
                self._fetch_vehicle_usages(),  # default: inizio contratto → oggi
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
