"""Shark IQ vacuum entity."""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

from sharkiq import OperatingModes, PowerModes, Properties, SharkIqVacuum

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
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

STATE_MAP = {
    OperatingModes.STOP: VacuumActivity.IDLE,
    OperatingModes.PAUSE: VacuumActivity.PAUSED,
    OperatingModes.START: VacuumActivity.CLEANING,
    OperatingModes.RETURN: VacuumActivity.RETURNING,
}

ATTR_ERROR_CODE = "last_error_code"
ATTR_ERROR_MSG = "last_error_message"
ATTR_LOW_LIGHT = "low_light"
ATTR_RECHARGE_RESUME = "recharge_and_resume"
ATTR_ROOMS = "rooms"

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
    devices: Iterable[SharkIqVacuum] = data["devices"]

    async_add_entities(
        SharkVacuumEntity(device, coordinator) for device in devices
    )


class SharkVacuumEntity(CoordinatorEntity, StateVacuumEntity):
    """Shark IQ vacuum entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_fan_speed_list = list(FAN_SPEEDS_MAP)
    _attr_supported_features = FEATURES
    _unrecorded_attributes = frozenset({ATTR_ROOMS})

    def __init__(self, device: SharkIqVacuum, coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.sharkiq = device
        self._attr_unique_id = device.serial_number
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.serial_number)},
            manufacturer="Shark",
            model=device.vac_model_number or device.oem_model_number or "Shark IQ",
            name=device.name,
            sw_version=device.get_property_value(Properties.ROBOT_FIRMWARE_VERSION),
        )

    @property
    def activity(self) -> VacuumActivity | None:
        """Return vacuum activity state."""
        if self.sharkiq.get_property_value(Properties.CHARGING_STATUS):
            return VacuumActivity.DOCKED
        op_mode = self.sharkiq.get_property_value(Properties.OPERATING_MODE)
        return STATE_MAP.get(op_mode)

    @property
    def battery_level(self) -> int | None:
        """Return battery level."""
        return self.sharkiq.get_property_value(Properties.BATTERY_CAPACITY)

    @property
    def fan_speed(self) -> str | None:
        """Return current fan speed."""
        mode = self.sharkiq.get_property_value(Properties.POWER_MODE)
        return FAN_SPEEDS_REVERSE.get(mode)

    @property
    def error_code(self) -> int | None:
        """Return error code."""
        return self.sharkiq.error_code

    @property
    def available_rooms(self) -> list[str]:
        """Return list of rooms available to clean."""
        room_list = self.sharkiq.get_property_value(Properties.ROBOT_ROOM_LIST)
        if room_list:
            return room_list.split(":")[1:]
        return []

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            ATTR_ERROR_CODE: self.error_code,
            ATTR_ERROR_MSG: self.sharkiq.error_text,
            ATTR_LOW_LIGHT: self.sharkiq.get_property_value(Properties.LOW_LIGHT_MISSION),
            ATTR_RECHARGE_RESUME: self.sharkiq.get_property_value(Properties.RECHARGE_RESUME),
            ATTR_ROOMS: self.available_rooms,
        }

    async def async_start(self) -> None:
        """Start cleaning."""
        await self.sharkiq.async_set_operating_mode(OperatingModes.START)
        await self.coordinator.async_request_refresh()

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop cleaning."""
        await self.sharkiq.async_set_operating_mode(OperatingModes.STOP)
        await self.coordinator.async_request_refresh()

    async def async_pause(self) -> None:
        """Pause cleaning."""
        await self.sharkiq.async_set_operating_mode(OperatingModes.PAUSE)
        await self.coordinator.async_request_refresh()

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Return to dock."""
        await self.sharkiq.async_set_operating_mode(OperatingModes.RETURN)
        await self.coordinator.async_request_refresh()

    async def async_locate(self, **kwargs: Any) -> None:
        """Locate vacuum."""
        await self.sharkiq.async_find_device()

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed."""
        mode = FAN_SPEEDS_MAP.get(fan_speed)
        if mode is None:
            _LOGGER.error("Invalid fan speed: %s", fan_speed)
            return
        await self.sharkiq.async_set_property_value(Properties.POWER_MODE, mode)
        await self.coordinator.async_request_refresh()

    async def async_clean_rooms(self, rooms: list[str]) -> None:
        """Clean specific rooms."""
        valid_rooms = self.available_rooms
        rooms_normalized = [r.replace("_", " ").title() for r in rooms]
        rooms_to_clean = []
        for room in rooms_normalized:
            if room in valid_rooms:
                rooms_to_clean.append(room)
            else:
                _LOGGER.warning("Room '%s' not in available rooms: %s", room, valid_rooms)
        if rooms_to_clean:
            await self.sharkiq.async_clean_rooms(rooms_to_clean)
            await self.coordinator.async_request_refresh()
