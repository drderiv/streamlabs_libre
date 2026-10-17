"""Config flow for StreamLabs Libre integration."""

from __future__ import annotations

from typing import Any, Dict, List
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .client import (
    StreamLabsAuthError,
    StreamLabsClient,
    StreamLabsConnectionError,
    StreamLabsError,
)
from .const import (
    CONF_LOCATIONS,
    CONF_SCAN_INTERVAL,
    CONF_WATER_OFF_INTERVAL,
    CONF_WATER_ON_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WATER_OFF_INTERVAL,
    DEFAULT_WATER_ON_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)


class StreamlabsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for StreamLabs Libre."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> StreamlabsOptionsFlowHandler:
        """Get the options flow for this handler."""
        return StreamlabsOptionsFlowHandler()

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._auth_data: Dict[str, str] = {}
        self._discovered_locations: Dict[str, str] = {}

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

            def _validate() -> list[dict[str, Any]]:
                client = StreamLabsClient(username, password)
                resp = client.get_locations()
                return resp.get("locations", [])

            try:
                locations = await self.hass.async_add_executor_job(_validate)
            except StreamLabsAuthError:
                errors["base"] = "invalid_auth"
            except StreamLabsConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected error during authentication")
                errors["base"] = "unknown"
            else:
                if not locations:
                    # Account has no locations configured yet
                    return self.async_create_entry(
                        title=username,
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_LOCATIONS: [],
                        },
                    )

                self._auth_data = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                }
                self._discovered_locations = {
                    str(loc["locationId"]): loc.get("locationName") or f"Location {loc['locationId']}"
                    for loc in locations
                    if "locationId" in loc
                }

                if len(self._discovered_locations) == 1:
                    loc_id = next(iter(self._discovered_locations))
                    loc_name = self._discovered_locations[loc_id]
                    return self.async_create_entry(
                        title=loc_name,
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_LOCATIONS: [loc_id],
                        },
                    )

                return await self.async_step_location()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle selection of multiple locations."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_locs: List[str] = user_input.get(CONF_LOCATIONS, [])
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
                    title=title,
                    data={
                        CONF_USERNAME: self._auth_data[CONF_USERNAME],
                        CONF_PASSWORD: self._auth_data[CONF_PASSWORD],
                        CONF_LOCATIONS: selected_locs,
                    },
                )

        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCATIONS,
                        default=list(self._discovered_locations.keys()),
                    ): cv.multi_select(self._discovered_locations)
                }
            ),
            errors=errors,
        )


class StreamlabsOptionsFlowHandler(OptionsFlow):
    """Handle options flow for StreamLabs Libre."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        options = self.config_entry.options or {}
        data = self.config_entry.data or {}

        # Discover all available locations on the account if coordinator is available
        raw_current = options.get(CONF_LOCATIONS, data.get(CONF_LOCATIONS, []))
        current_locations: List[str] = (
            [str(x) for x in raw_current] if isinstance(raw_current, (list, set)) else []
        )
        location_options: Dict[str, str] = {}
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator and hasattr(coordinator, "client"):
            try:
                resp = await self.hass.async_add_executor_job(coordinator.client.get_locations)
                if isinstance(resp, dict):
                    for loc in resp.get("locations", []):
                        raw_id = loc.get("locationId") or loc.get("location_id") or loc.get("id")
                        if raw_id is not None:
                            str_id = str(raw_id)
                            location_options[str_id] = (
                                loc.get("locationName") or loc.get("name") or f"Location {str_id}"
                            )
            except Exception as err:
                LOGGER.debug("Could not fetch locations in options flow: %s", err)

        # Fallback to current_locations if get_locations was unavailable
        if not location_options and current_locations:
            location_options = {loc_id: f"Location {loc_id}" for loc_id in current_locations}

        errors: dict[str, str] = {}
        if user_input is not None:
            selected_locs = [str(x) for x in user_input.get(CONF_LOCATIONS, [])]
            if location_options and len(location_options) > 1 and not selected_locs:
                errors[CONF_LOCATIONS] = "no_location_selected"
            else:
                if selected_locs:
                    user_input[CONF_LOCATIONS] = selected_locs
                return self.async_create_entry(title="", data=user_input)

        legacy_interval = options.get(
            CONF_SCAN_INTERVAL,
            data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        current_off = options.get(
            CONF_WATER_OFF_INTERVAL,
            data.get(CONF_WATER_OFF_INTERVAL, legacy_interval),
        )
        current_on = options.get(
            CONF_WATER_ON_INTERVAL,
            data.get(CONF_WATER_ON_INTERVAL, DEFAULT_WATER_ON_INTERVAL),
        )

        schema_dict: dict[Any, Any] = {}
        if len(location_options) > 1:
            valid_defaults = [loc for loc in current_locations if loc in location_options]
            schema_dict[
                vol.Required(
                    CONF_LOCATIONS,
                    default=valid_defaults or list(location_options.keys()),
                )
            ] = cv.multi_select(location_options)

        schema_dict[
            vol.Required(
                CONF_WATER_OFF_INTERVAL,
                default=current_off,
            )
        ] = vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
        )
        schema_dict[
            vol.Required(
                CONF_WATER_ON_INTERVAL,
                default=current_on,
            )
        ] = vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )
