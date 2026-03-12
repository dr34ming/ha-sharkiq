"""Shark IQ Robot Vacuums (HACS) — with PKCE auth and token persistence."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from sharkiq import AylaApi, get_ayla_api

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ID_TOKEN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.VACUUM]

type SharkIqConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: SharkIqConfigEntry) -> bool:
    """Set up Shark IQ from a config entry with persisted tokens."""
    ayla_api = get_ayla_api(
        username=entry.data.get(CONF_USERNAME, ""),
        password="",  # not used — we inject tokens directly
    )

    # Inject persisted tokens directly into the API object
    ayla_api._access_token = entry.data[CONF_ACCESS_TOKEN]
    ayla_api._auth0_id_token = entry.data.get(CONF_ID_TOKEN)
    ayla_api._refresh_token = entry.data[CONF_REFRESH_TOKEN]
    ayla_api._is_authed = True

    # Try to refresh tokens on startup to ensure they're current
    try:
        await ayla_api.async_refresh_auth()
    except Exception:
        _LOGGER.warning("Token refresh failed, trying with stored tokens")
        # If refresh fails, the stored tokens may still work
        # If they don't, the coordinator will catch it

    # Persist any refreshed tokens back to config entry
    await _persist_tokens(hass, entry, ayla_api)

    # Fetch devices
    try:
        devices = await ayla_api.async_list_devices()
    except Exception as err:
        _LOGGER.error("Failed to list devices: %s", err)
        raise ConfigEntryAuthFailed(
            "Authentication failed. Please reconfigure the integration."
        ) from err

    device_names = ", ".join(d.name for d in devices)
    _LOGGER.info("Found %d Shark devices: %s", len(devices), device_names)

    coordinator = SharkIqUpdateCoordinator(hass, entry, ayla_api, devices)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "ayla_api": ayla_api,
        "coordinator": coordinator,
        "devices": devices,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SharkIqConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _persist_tokens(
    hass: HomeAssistant, entry: SharkIqConfigEntry, ayla_api: AylaApi
) -> None:
    """Persist current API tokens back to the config entry."""
    new_data: dict[str, Any] = {**entry.data}
    changed = False

    token_map = {
        CONF_ACCESS_TOKEN: getattr(ayla_api, "_access_token", None),
        CONF_ID_TOKEN: getattr(ayla_api, "_auth0_id_token", None),
        CONF_REFRESH_TOKEN: getattr(ayla_api, "_refresh_token", None),
    }

    for key, value in token_map.items():
        if value and value != new_data.get(key):
            new_data[key] = value
            changed = True

    if changed:
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.debug("Persisted refreshed tokens to config entry")


class SharkIqUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to poll Shark IQ devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SharkIqConfigEntry,
        ayla_api: AylaApi,
        devices: list,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._entry = entry
        self._ayla_api = ayla_api
        self._devices = devices

    async def _async_update_data(self) -> bool:
        """Fetch latest device data."""
        try:
            for device in self._devices:
                await device.async_update()
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                # Try to refresh auth
                try:
                    await self._ayla_api.async_refresh_auth()
                    await _persist_tokens(self.hass, self._entry, self._ayla_api)
                    # Retry update after refresh
                    for device in self._devices:
                        await device.async_update()
                except Exception as refresh_err:
                    raise ConfigEntryAuthFailed(
                        "Authentication expired. Please reconfigure."
                    ) from refresh_err
            else:
                raise UpdateFailed(f"Error updating Shark devices: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error updating Shark devices: {err}") from err
        return True
