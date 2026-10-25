"""Config flow for StreamLabs Libre integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .client import StreamLabsAuthError, StreamLabsClient, StreamLabsConnectionError
from .const import (
    CONF_LOCATIONS,
    CONF_SCAN_INTERVAL,
    CONF_WATER_OFF_INTERVAL,
    CONF_WATER_ON_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WATER_ON_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

_INTERVAL_VALIDATOR = vol.All(
    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
)


def _fetch_locations(username: str, password: str) -> list[dict[str, Any]]:
    """Authenticate (blocking) and return the account's locations."""
    client = StreamLabsClient(username, password)
    try:
        return client.get_locations().get("locations", [])
    finally:
        client.close()


class StreamlabsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for StreamLabs Libre."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._auth_data: dict[str, str] = {}
        self._discovered_locations: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> StreamlabsOptionsFlow:
        """Get the options flow for this handler."""
        return StreamlabsOptionsFlow()

    async def _async_check_credentials(
        self, username: str, password: str, errors: dict[str, str]
    ) -> list[dict[str, Any]] | None:
        """Validate credentials, recording a form error on failure."""
        try:
            return await self.hass.async_add_executor_job(_fetch_locations, username, password)
        except StreamLabsAuthError:
            errors["base"] = "invalid_auth"
        except StreamLabsConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during authentication")
            errors["base"] = "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial step where credentials are provided."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            if (locations := await self._async_check_credentials(username, password, errors)) is not None:
                self._auth_data = {CONF_USERNAME: username, CONF_PASSWORD: password}
                self._discovered_locations = {
                    str(loc["locationId"]): loc.get("locationName") or f"Location {loc['locationId']}"
                    for loc in locations
                    if "locationId" in loc
                }

                if not locations:
                    # Account has no locations configured yet
                    return self.async_create_entry(
                        title=username, data={**self._auth_data, CONF_LOCATIONS: []}
                    )
                if len(self._discovered_locations) == 1:
                    loc_id, loc_name = next(iter(self._discovered_locations.items()))
                    return self.async_create_entry(
                        title=loc_name, data={**self._auth_data, CONF_LOCATIONS: [loc_id]}
                    )
                return await self.async_step_location()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
        )

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle selection of multiple locations."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_locs: list[str] = user_input.get(CONF_LOCATIONS, [])
            if not selected_locs:
                errors[CONF_LOCATIONS] = "no_location_selected"
            else:
                if len(selected_locs) == 1:
                    title = self._discovered_locations.get(
                        selected_locs[0], self._auth_data[CONF_USERNAME]
                    )
                else:
                    title = f"StreamLabs ({len(selected_locs)} locations)"
                return self.async_create_entry(
                    title=title, data={**self._auth_data, CONF_LOCATIONS: selected_locs}
                )

        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCATIONS, default=list(self._discovered_locations)
                    ): cv.multi_select(self._discovered_locations)
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after the stored credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            if (
                await self._async_check_credentials(
                    entry.data[CONF_USERNAME], user_input[CONF_PASSWORD], errors
                )
                is not None
            ):
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_USERNAME: entry.data[CONF_USERNAME]},
            errors=errors,
        )


class StreamlabsOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for StreamLabs Libre (reloads the entry when options change)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        entry = self.config_entry
        options, data = entry.options, entry.data

        raw_current = options.get(CONF_LOCATIONS, data.get(CONF_LOCATIONS, []))
        current_locations = [str(x) for x in raw_current]

        # Locations come from the coordinator's last poll; fall back to the saved selection
        location_options: dict[str, str] = {}
        if entry.state is ConfigEntryState.LOADED:
            location_options = dict(entry.runtime_data.known_locations)
        if not location_options:
            location_options = {loc_id: f"Location {loc_id}" for loc_id in current_locations}

        errors: dict[str, str] = {}
        if user_input is not None:
            selected = [str(x) for x in user_input.get(CONF_LOCATIONS, [])]
            if len(location_options) > 1 and CONF_LOCATIONS in user_input and not selected:
                errors[CONF_LOCATIONS] = "no_location_selected"
            else:
                new_options = {**options, **user_input}
                if selected:
                    new_options[CONF_LOCATIONS] = selected
                return self.async_create_entry(data=new_options)

        legacy_interval = options.get(
            CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        current_off = options.get(CONF_WATER_OFF_INTERVAL, data.get(CONF_WATER_OFF_INTERVAL, legacy_interval))
        current_on = options.get(
            CONF_WATER_ON_INTERVAL, data.get(CONF_WATER_ON_INTERVAL, DEFAULT_WATER_ON_INTERVAL)
        )

        schema: dict[Any, Any] = {}
        if len(location_options) > 1:
            defaults = [loc for loc in current_locations if loc in location_options]
            schema[vol.Required(CONF_LOCATIONS, default=defaults or list(location_options))] = (
                cv.multi_select(location_options)
            )
        schema[vol.Required(CONF_WATER_OFF_INTERVAL, default=current_off)] = _INTERVAL_VALIDATOR
        schema[vol.Required(CONF_WATER_ON_INTERVAL, default=current_on)] = _INTERVAL_VALIDATOR

        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema), errors=errors
        )
