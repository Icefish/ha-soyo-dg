"""按鈕平台 — 重啟逆變器。"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SoyoDGDeviceOfflineError
from .coordinator import SoyoDGCoordinator
from .entity import SoyoDGEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """建立按鈕。"""
    coordinator: SoyoDGCoordinator = hass.data["soyo_dg"][entry.entry_id]
    async_add_entities([SoyoDGRebootButton(coordinator, entry)])


class SoyoDGRebootButton(SoyoDGEntity, ButtonEntity):
    """重啟逆變器。

    重啟會讓設備短暫沒回應,即時資料會中斷一陣子。
    """

    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: SoyoDGCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "reboot")
        self._attr_translation_key = "reboot"

    @property
    def available(self) -> bool:
        """設備在線才能重啟。"""
        return super().available and self.coordinator.device.get("status") == 1

    async def async_press(self) -> None:
        """發送重啟指令。"""
        try:
            await self.coordinator.client.async_reboot(self.coordinator.device_sn)
        except SoyoDGDeviceOfflineError as err:
            raise HomeAssistantError(f"設備目前離線,無法重啟: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"重啟失敗: {err}") from err

        _LOGGER.info("已送出重啟指令給 %s", self.coordinator.device_sn)
        await self.coordinator.async_request_refresh()
