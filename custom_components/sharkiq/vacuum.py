"""Shark IQ vacuum entity."""

from __future__ import annotations

import logging
from typing import Any

from sharkiq import OperatingModes, PowerModes, Properties, SharkIqVacuum

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

FAN_SPEEDS_MAP = {
    "Eco": PowerModes.ECO,
    "Normal": PowerModes.NORMAL,
    "Max": PowerModes.MAX,
}
FAN_SPEEDS_REVERSE = {v: k for k, v in FAN_SPEEDS_MAP.items()}

# Map Shark operating modes to HA vacuum states
STATE_MAP = {
    OperatingModes.STOP: "idle",
    OperatingModes.PAUSE: "paused",
    OperatingModes.START: "cleaning",
    OperatingModes.RETURN: "returning",
}

FEATURES = (
    VacuumEntityFeature.BATTERY
    | VacuumEntityFeature.FAN_SPEED
    | VacuumEntityFeature.LOCATE
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.START
    | VacuumEntityFeature.STATE
    | VacuumEntityFeature.STOP
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Shark IQ vacuum entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    devices = data["devices"]

    async_add_entities(
        SharkVacuumEntity(device, coordinator) for device in devices
    )


class SharkVacuumEntity(CoordinatorEntity, StateVacuumEntity):
    """Shark IQ vacuum entity."""

    _attr_has_entity_name = True
    _attr_fan_speed_list = list(FAN_SPEEDS_MAP)
    _attr_supported_features = FEATURES

    def __init__(self, device: SharkIqVacuum, coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._device = device
        self._attr_unique_id = device.serial_number
        self._attr_name = device.name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.serial_number)},
            manufacturer="Shark",
            model=self._device.vac_model_number or "Shark IQ",
            name=self._device.name,
            sw_version=self._device.get_property_value(Properties.FIRMWARE_VERSION),
        )

    @property
    def is_on(self) -> bool:
        """Return True if cleaning."""
        return self._device.get_property_value(Properties.OPERATING_MODE) == OperatingModes.START

    @property
    def state(self) -> str | None:
        """Return vacuum state."""
        mode = self._device.get_property_value(Properties.OPERATING_MODE)
        if mode is None:
            return None

        # Check if the vacuum is charging
        charging = self._device.get_property_value(Properties.CHARGING_STATUS)
        if charging and mode == OperatingModes.STOP:
            return "docked"

        return STATE_MAP.get(mode, "idle")

    @property
    def battery_level(self) -> int | None:
        """Return battery level."""
        return self._device.get_property_value(Properties.BATTERY_CAPACITY)

    @property
    def fan_speed(self) -> str | None:
        """Return current fan speed."""
        mode = self._device.get_property_value(Properties.POWER_MODE)
        return FAN_SPEEDS_REVERSE.get(mode)

    @property
    def error_code(self) -> int | None:
        """Return error code."""
        return self._device.error_code

    async def async_start(self) -> None:
        """Start cleaning."""
        await self._device.async_set_operating_mode(OperatingModes.START)
        await self.coordinator.async_request_refresh()

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop cleaning."""
        await self._device.async_set_operating_mode(OperatingModes.STOP)
        await self.coordinator.async_request_refresh()

    async def async_pause(self) -> None:
        """Pause cleaning."""
        await self._device.async_set_operating_mode(OperatingModes.PAUSE)
        await self.coordinator.async_request_refresh()

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Return to dock."""
        await self._device.async_set_operating_mode(OperatingModes.RETURN)
        await self.coordinator.async_request_refresh()

    async def async_locate(self, **kwargs: Any) -> None:
        """Locate vacuum."""
        await self._device.async_find_device()

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed."""
        mode = FAN_SPEEDS_MAP.get(fan_speed)
        if mode is None:
            _LOGGER.error("Invalid fan speed: %s", fan_speed)
            return
        await self._device.async_set_property_value(Properties.POWER_MODE, mode)
        await self.coordinator.async_request_refresh()
