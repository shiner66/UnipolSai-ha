"""Config flow e Options flow per UnipolSai."""
import voluptuous as vol
import aiohttp

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, LOGIN_URL, APP_HEADERS

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required("username"): str,
    vol.Required("password"): str,
    vol.Required("targa"): str,
    vol.Optional("scan_interval", default=5): vol.All(int, vol.Range(min=1, max=60)),
})


async def _validate_credentials(username: str, password: str) -> None:
    """Verifica le credenziali eseguendo un login di prova."""
    headers = {**APP_HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            LOGIN_URL,
            headers=headers,
            data={"username": username, "password": password},
        ) as resp:
            if resp.status != 200:
                raise ValueError("invalid_auth")
            result = await resp.json(content_type=None)
    if not result.get("JWT", {}).get("token"):
        raise ValueError("invalid_auth")


class UnipolSaiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow per l'integrazione UnipolSai."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return UnipolSaiOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            try:
                await _validate_credentials(user_input["username"], user_input["password"])
            except ValueError:
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                targa = user_input["targa"].upper().replace(" ", "")
                # Ogni coppia (username, targa) è un'entità unica —
                # consente più auto anche con utenti diversi
                await self.async_set_unique_id(f"unipolsai_{user_input['username']}_{targa}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"UnipolSai - {targa}",
                    data={
                        "username": user_input["username"],
                        "password": user_input["password"],
                        "targa": targa,
                        "scan_interval": user_input.get("scan_interval", 5),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class UnipolSaiOptionsFlow(config_entries.OptionsFlow):
    """Options flow: modifica le impostazioni senza reinstallare."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options or self.config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    "scan_interval",
                    default=int(current.get("scan_interval", 5)),
                ): vol.All(int, vol.Range(min=1, max=60)),
            }),
        )
