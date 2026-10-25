"""二元感測器 — 在線狀態、採集器連線、資料新鮮度、故障。"""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import STATUS_ONLINE
from .coordinator import SoyoDGCoordinator
from .entity import SoyoDGEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """建立二元感測器。"""
    coordinator: SoyoDGCoordinator = hass.data["soyo_dg"][entry.entry_id]

    async_add_entities(
        [
            SoyoDGConnectivitySensor(coordinator, entry, "connectivity"),
            SoyoDGCollectorSensor(coordinator, entry, "collector_connected"),
            SoyoDGDataFreshSensor(coordinator, entry, "data_fresh"),
            SoyoDGFaultSensor(coordinator, entry, "fault"),
        ]
    )


class SoyoDGConnectivitySensor(SoyoDGEntity, BinarySensorEntity):
    """設備在線狀態(雲端 status 欄位:1=在線,2=故障,其他=離線)。"""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self, coordinator: SoyoDGCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key

    @property
    def is_on(self) -> bool:
        """在線為 True。"""
        return self._get("status") == STATUS_ONLINE


class SoyoDGCollectorSensor(SoyoDGEntity, BinarySensorEntity):
    """採集器是否連線。"""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self, coordinator: SoyoDGCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key

    @property
    def is_on(self) -> bool:
        """採集器連線為 True。"""
        return self._get("collector_status") == 1


class SoyoDGDataFreshSensor(SoyoDGEntity, BinarySensorEntity):
    """資料是否還新鮮(reported_at 距今未超過過期門檻)。"""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:database-clock"

    def __init__(
        self, coordinator: SoyoDGCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key

    @property
    def is_on(self) -> bool:
        """資料新鮮為 True。"""
        return not self.coordinator.is_stale


class SoyoDGFaultSensor(SoyoDGEntity, BinarySensorEntity):
    """設備是否有故障。"""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: SoyoDGCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key

    @property
    def is_on(self) -> bool:
        """有故障訊息或 power_status 異常為 True。"""
        error = self._get("error_msg")
        if error:
            return True
        status = self._get("power_status")
        return status is not None and int(status) not in (0, 1)
