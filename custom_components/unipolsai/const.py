"""Costanti per l'integrazione UnipolSai."""

DOMAIN = "unipolsai"
DEFAULT_SCAN_INTERVAL = 5  # minuti

# ------------------------------------------------------------------
# Endpoint API
# ------------------------------------------------------------------
BASE_URL = "https://apphub.unipolsai.it"
LOGIN_URL = f"{BASE_URL}/hub/login"
CONTRATTI_TELEMATICI_URL = f"{BASE_URL}/hub/api/priv/contesto-utente/v2/me/contrattiTelematici"
LAST_POSITION_URL = f"{BASE_URL}/hub/api/priv/telematici/auto/v1/vehicles/IT-{{targa}}/lastPosition"
LAST_NOTIFICATIONS_URL = f"{BASE_URL}/hub/api/priv/telematici/auto/v1/vehicles/IT-{{targa}}/lastNotifications"
LAST_TARGET_AREA_URL = f"{BASE_URL}/hub/api/priv/telematici/auto/v1/vehicles/IT-{{targa}}/lastTargetArea"
MODIFY_TARGET_AREA_URL = f"{BASE_URL}/hub/api/priv/telematici/auto/v1/vehicles/IT-{{targa}}/lastTargetArea/modify"
ENABLE_VAS_URL = f"{BASE_URL}/hub/api/priv/telematici/auto/v1/vehicles/IT-{{targa}}/vehicleVAS/{{vas}}"
CONTRACT_URL = f"{BASE_URL}/hub/api/priv/contratti/v4/polizze/{{chiave_contratto}}"
VEHICLE_USAGES_URL = f"{BASE_URL}/hub/api/priv/telematici/auto/v1/vehicles/IT-{{targa}}/vehicleUsages"
SPEED_LIMIT_URL = f"{BASE_URL}/hub/api/priv/telematici/auto/v1/vehicles/IT-{{targa}}/lastSpeedLimit"
MODIFY_SPEED_LIMIT_URL = f"{BASE_URL}/hub/api/priv/telematici/auto/v1/vehicles/IT-{{targa}}/lastSpeedLimit/modify"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

# ------------------------------------------------------------------
# Credenziali app UnipolSai (client-side, non personali)
#
# Questi valori sono le credenziali dell'applicazione mobile ufficiale
# UnipolSai, necessarie per autenticarsi al gateway API. Non sono
# credenziali personali dell'utente — sono pubblicamente ottenibili
# tramite analisi del traffico dell'app ufficiale (liberamente
# scaricabile dall'App Store). Senza questi header, il gateway API
# rifiuta le richieste con HTTP 401.
# ------------------------------------------------------------------
APP_HEADERS = {
    "x-ibm-client-id": "246a3dc4-9b99-47a1-859c-1840a0adf49a",
    "x-ibm-client-secret": "L6kT5mS5bW0pQ4qD1eT2fV8sL5qI0sD8eI5tK8sF0uI4kK1wM5",
    "api_key": "zje898HMI2P8aQy413mbz7euA0X93GiD",
    "x-unipol-tenant": "e63a8acccacc90d4d4814149523bfe67f09746bf3c9221f3a6ea551e3c804283",
    "source": "mobile",
    "x-canale": "APP",
    "x-media": "APP",
    "x-user-family": "CLIENTE",
    "x-unipol-canale": "APP",
    "company_id": "unipolsai",
    "service_type": "Vehicle",
    "User-Agent": "UnipolSaiApp/6.2.12 (it.unipolsai.clientitpd; build:42379; iOS 18.0) Alamofire/5.10.2",
    "Accept": "application/json",
    "Accept-Language": "it-IT;q=1.0, en-IT;q=0.9",
}

# ------------------------------------------------------------------
# Eventi Home Assistant
# ------------------------------------------------------------------
EVENT_CAR_MOVED_ENGINE_OFF = "unipolsai_car_moved_engine_off"
EVENT_TARGET_AREA_EXIT = "unipolsai_target_area_exit"
EVENT_SPEED_LIMIT_EXCEEDED = "unipolsai_speed_limit_exceeded"
