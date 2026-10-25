"""選擇器平台 — 逆變器工作模式。"""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SoyoDGDeviceOfflineError
from .const import PARAM_WORK_MODE, WORK_MODE_OPTIONS
from .coordinator import SoyoDGCoordinator
from .entity import SoyoDGEntity

_LOGGER = logging.getLogger(__name__)

#: option key → 實際寫給設備的數值
OPTION_TO_VALUE: dict[str, int] = {
    option: value for value, option in WORK_MODE_OPTIONS.items()
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """建立選擇器。"""
    coordinator: SoyoDGCoordinator = hass.data["soyo_dg"][entry.entry_id]
    async_add_entities([SoyoDGWorkModeSelect(coordinator, entry)])


class SoyoDGWorkModeSelect(SoyoDGEntity, SelectEntity):
    """工作模式(光伏 / 光伏防逆流 / 電池恆功率 / 電池防反流)。"""

    _attr_options = list(OPTION_TO_VALUE)
    _attr_icon = "mdi:sine-wave"

    def __init__(self, coordinator: SoyoDGCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "work_mode")
        self._attr_translation_key = "work_mode"

    @property
    def available(self) -> bool:
        """讀得到設備參數才有辦法操作。"""
        return super().available and self.coordinator.params_available

    @property
    def current_option(self) -> str | None:
        """目前的工作模式。"""
        value = self.coordinator.params.get(PARAM_WORK_MODE)
        if value is None:
            return None
        return WORK_MODE_OPTIONS.get(int(value))

    async def async_select_option(self, option: str) -> None:
        """寫入工作模式。"""
        value = OPTION_TO_VALUE.get(option)
        if value is None:
            raise HomeAssistantError(f"不支援的工作模式: {option}")

        try:
            await self.coordinator.async_write_param(PARAM_WORK_MODE, value)
        except SoyoDGDeviceOfflineError as err:
            raise HomeAssistantError(
                f"設備目前離線,無法寫入參數: {err}"
            ) from err
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"寫入工作模式失敗: {err}") from err
