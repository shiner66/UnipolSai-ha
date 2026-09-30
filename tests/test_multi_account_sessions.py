"""Regression tests for UnipolSai multi-account session isolation."""

from __future__ import annotations

import asyncio
from types import MethodType

from homeassistant.core import HomeAssistant

from custom_components.unipolsai import coordinator as coordinator_module
from custom_components.unipolsai.coordinator import UnipolSaiCoordinator


class _MockResponse:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self, *, content_type=None):
        return self._payload


class _AccountSession:
    """Model an API that binds each JWT to the login session cookie."""

    def __init__(self) -> None:
        self.cookie_jar: dict[str, str] = {}
        self.tokens: dict[str, str] = {}

    def post(self, url, *, headers=None, data=None, **kwargs):
        username = data["username"]
        token = f"jwt:{username}"
        self.tokens[token] = username
        self.cookie_jar["account"] = username
        return _MockResponse(200, {"JWT": {"token": token}})

    def get(self, url, *, headers=None, params=None, **kwargs):
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        token_account = self.tokens.get(token)
        if token_account != self.cookie_jar.get("account"):
            return _MockResponse(403, {"error": "session/JWT account mismatch"})

        plate = url.split("IT-")[-1].split("/")[0]
        return _MockResponse(
            200,
            {
                "operationResult": {"type": 0},
                "lastPosition": {
                    "plate": plate,
                    "lat": 40.0,
                    "lon": 14.0,
                    "pendingRequest": False,
                },
            },
        )


async def _return_none(*args, **kwargs):
    return None


def _new_hass() -> HomeAssistant:
    hass = HomeAssistant("/tmp/unipolsai-multi-account-test")
    try:
        from homeassistant.helpers import frame

        frame.async_setup(hass)
    except (ImportError, AttributeError):
        pass
    return hass


def _build_coordinator(
    hass: HomeAssistant, username: str, plate: str
) -> UnipolSaiCoordinator:
    coordinator = UnipolSaiCoordinator(
        hass,
        username=username,
        password="test-password",
        targa=plate,
    )

    # Keep the test focused on the mandatory authenticated position request.
    for method_name in (
        "_fetch_target_area",
        "_fetch_speed_limit",
        "_fetch_contract_data",
        "_fetch_vehicle_usages",
        "_check_car_moved_notifications",
        "_check_target_area_notifications",
        "_check_speed_limit_notifications",
    ):
        setattr(coordinator, method_name, MethodType(_return_none, coordinator))
    coordinator._schedule_reverse_geocode = lambda position: None
    return coordinator


def test_coordinators_receive_distinct_sessions(monkeypatch) -> None:
    sessions: list[_AccountSession] = []

    def create_session(hass):
        session = _AccountSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(
        coordinator_module, "async_create_clientsession", create_session
    )

    async def run_test() -> None:
        hass = _new_hass()
        account_a = _build_coordinator(hass, "account-a@example.test", "AA111AA")
        account_b = _build_coordinator(hass, "account-b@example.test", "BB222BB")

        assert account_a._session is sessions[0]
        assert account_b._session is sessions[1]
        assert account_a._session is not account_b._session
        assert account_a._session.cookie_jar is not account_b._session.cookie_jar

    asyncio.run(run_test())


def test_two_accounts_keep_cookie_auth_isolated(monkeypatch) -> None:
    sessions: list[_AccountSession] = []

    def create_session(hass):
        session = _AccountSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(
        coordinator_module, "async_create_clientsession", create_session
    )

    async def run_test() -> None:
        hass = _new_hass()
        account_a = _build_coordinator(hass, "account-a@example.test", "AA111AA")
        account_b = _build_coordinator(hass, "account-b@example.test", "BB222BB")

        results = await asyncio.gather(
            account_a._async_update_data(), account_b._async_update_data()
        )

        assert [result["plate"] for result in results] == ["AA111AA", "BB222BB"]
        assert sessions[0].cookie_jar["account"] == "account-a@example.test"
        assert sessions[1].cookie_jar["account"] == "account-b@example.test"

    asyncio.run(run_test())
