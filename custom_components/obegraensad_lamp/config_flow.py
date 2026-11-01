"""Config flow for the IKEA OBEGRÄNSAD Lamp."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
import voluptuous as vol

from .api import (
    LampClient,
    LampConnectionError,
    LampNotSupportedError,
    LampResponseError,
    LampState,
    normalise_host,
)
from .const import (
    CONF_DDP_PORT,
    CONF_MAX_LAMP_MESSAGES,
    CONF_MESSAGE_DELAY,
    CONF_MESSAGE_REPEAT,
    CONF_NIGHT_SUPPRESS_LOW,
    CONF_POLL_INTERVAL,
    CONF_RESTORE,
    DEFAULT_DDP_PORT,
    DEFAULT_MAX_LAMP_MESSAGES,
    DEFAULT_MESSAGE_DELAY,
    DEFAULT_MESSAGE_REPEAT,
    DEFAULT_NIGHT_SUPPRESS_LOW,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_RESTORE,
    DOMAIN,
    NAME,
)
from .coordinator import ObegraensadConfigEntry

_LOGGER = logging.getLogger(__name__)

HOST_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class ObegraensadConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a lamp by host or IP address."""

    VERSION = 1

    async def _validate(self, host: str) -> tuple[LampState | None, dict[str, str]]:
        """Fetch /api/info; return the state or form errors."""
        client = LampClient(async_get_clientsession(self.hass), host, retries=1)
        try:
            state = await client.get_info()
        except LampNotSupportedError:
            return None, {"base": "firmware_unsupported"}
        except LampConnectionError:
            return None, {"base": "cannot_connect"}
        except LampResponseError:
            return None, {"base": "invalid_response"}
        except Exception:
            _LOGGER.exception("Unexpected error while adding the lamp")
            return None, {"base": "unknown"}
        if not state.mac_address:
            return None, {"base": "invalid_response"}
        return state, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the host."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = normalise_host(user_input[CONF_HOST])
            state, errors = await self._validate(host)
            if state is not None:
                await self.async_set_unique_id(format_mac(state.mac_address or ""))
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(title=NAME, data={CONF_HOST: host})
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(HOST_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the host of an existing lamp."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = normalise_host(user_input[CONF_HOST])
            state, errors = await self._validate(host)
            if state is not None:
                await self.async_set_unique_id(format_mac(state.mac_address or ""))
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data_updates={CONF_HOST: host})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                HOST_SCHEMA, user_input or {CONF_HOST: entry.data[CONF_HOST]}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ObegraensadConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ObegraensadOptionsFlow()


def _number(minimum: int, maximum: int, unit: str | None = None) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=1, mode=selector.NumberSelectorMode.BOX
    )
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): _number(10, 600, "s"),
        vol.Required(CONF_MESSAGE_DELAY, default=DEFAULT_MESSAGE_DELAY): _number(10, 500, "ms"),
        vol.Required(CONF_MESSAGE_REPEAT, default=DEFAULT_MESSAGE_REPEAT): _number(-1, 100),
        vol.Required(CONF_MAX_LAMP_MESSAGES, default=DEFAULT_MAX_LAMP_MESSAGES): _number(1, 8),
        vol.Required(CONF_RESTORE, default=DEFAULT_RESTORE): selector.BooleanSelector(),
        vol.Required(
            CONF_NIGHT_SUPPRESS_LOW, default=DEFAULT_NIGHT_SUPPRESS_LOW
        ): selector.BooleanSelector(),
        vol.Required(CONF_DDP_PORT, default=DEFAULT_DDP_PORT): _number(1, 65535),
    }
)


class ObegraensadOptionsFlow(OptionsFlow):
    """Tune polling, message defaults and the display engine."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and save the options."""
        if user_input is not None:
            # number selectors return floats
            data = {k: int(v) if isinstance(v, float) else v for k, v in user_input.items()}
            return self.async_create_entry(data=data)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
