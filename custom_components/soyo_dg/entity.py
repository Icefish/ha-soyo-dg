"""共用 Entity 基底類別。"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SoyoDGCoordinator


class SoyoDGEntity(CoordinatorEntity[SoyoDGCoordinator]):
    """所有 soyo_dg entity 的基底。"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SoyoDGCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_sn}_{key}"
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """裝置資訊。"""
        device = self.coordinator.device
        realtime = self.coordinator.realtime
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device_sn)},
            name=self.coordinator.device_name,
            manufacturer="SOYO",
            model=device.get("model") or realtime.get("model") or "SOYO Inverter",
            serial_number=self.coordinator.device_sn,
            sw_version=device.get("fw_version") or device.get("version"),
        )

    @property
    def available(self) -> bool:
        """有拿到資料就視為可用,離線狀態另外用 binary_sensor 呈現。"""
        return super().available and bool(self.coordinator.realtime or self.coordinator.stats)

    def _get(self, *keys: str, default: Any = None) -> Any:
        """依序從 realtime → stats → device 找第一個有值的欄位。"""
        for source in (self.coordinator.realtime, self.coordinator.stats, self.coordinator.device):
            for key in keys:
                value = source.get(key)
                if value is not None:
                    return value
        return default
