"""數值平台 — 逆變器可寫入的設備參數。

對應 ``PUT /devices/{sn}/params`` 的四個數值欄位:
  * delay_start_sec   延時啟動(秒)
  * battery_out_w     電池輸出功率(W)
  * battery_start_v   啟動電壓(V)
  * battery_protect_v 欠壓保護值(V)

注意:這個 API 是**整組覆蓋**,所以每次寫入都會連同其他參數一起送出,
避免把沒帶到的欄位清成 0。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SoyoDGDeviceOfflineError
from .const import (
    BATTERY_OUT_W_MAX,
    BATTERY_OUT_W_MIN,
    BATTERY_OUT_W_STEP,
    DELAY_START_MAX,
    DELAY_START_MIN,
    PARAM_BATTERY_OUT_W,
    PARAM_BATTERY_PROTECT_V,
    PARAM_BATTERY_START_V,
    PARAM_DELAY_START_SEC,
    VOLTAGE_GAP_MIN,
)
from .coordinator import SoyoDGCoordinator
from .entity import SoyoDGEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SoyoDGNumberDescription(NumberEntityDescription):
    """數值實體描述。"""

    param: str
    #: True 表示合法區間要依電池標稱電壓動態決定
    voltage_range: bool = False


NUMBERS: tuple[SoyoDGNumberDescription, ...] = (
    SoyoDGNumberDescription(
        key="delay_start_sec",
        param=PARAM_DELAY_START_SEC,
        native_min_value=DELAY_START_MIN,
        native_max_value=DELAY_START_MAX,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:timer-play-outline",
    ),
    SoyoDGNumberDescription(
        key="battery_out_w",
        param=PARAM_BATTERY_OUT_W,
        native_min_value=BATTERY_OUT_W_MIN,
        native_max_value=BATTERY_OUT_W_MAX,
        native_step=BATTERY_OUT_W_STEP,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:battery-arrow-up-outline",
    ),
    SoyoDGNumberDescription(
        key="battery_start_v",
        param=PARAM_BATTERY_START_V,
        native_step=0.5,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:battery-charging-outline",
        voltage_range=True,
    ),
    SoyoDGNumberDescription(
        key="battery_protect_v",
        param=PARAM_BATTERY_PROTECT_V,
        native_step=0.5,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:battery-alert-outline",
        voltage_range=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """建立數值實體。"""
    coordinator: SoyoDGCoordinator = hass.data["soyo_dg"][entry.entry_id]
    async_add_entities(
        [SoyoDGNumber(coordinator, entry, description) for description in NUMBERS]
    )


class SoyoDGNumber(SoyoDGEntity, NumberEntity):
    """可寫入的設備參數。"""

    entity_description: SoyoDGNumberDescription
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: SoyoDGCoordinator,
        entry: ConfigEntry,
        description: SoyoDGNumberDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_native_step = description.native_step
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        if description.icon:
            self._attr_icon = description.icon

    @property
    def native_min_value(self) -> float:
        """最小值(電壓參數依電池標稱電壓動態決定)。"""
        if self.entity_description.voltage_range:
            return float(self.coordinator.voltage_range[0])
        return float(self.entity_description.native_min_value or 0)

    @property
    def native_max_value(self) -> float:
        """最大值(電壓參數依電池標稱電壓動態決定)。"""
        if self.entity_description.voltage_range:
            return float(self.coordinator.voltage_range[1])
        return float(self.entity_description.native_max_value or 0)

    @property
    def available(self) -> bool:
        """讀得到設備參數才有辦法操作。"""
        return super().available and self.coordinator.params_available

    @property
    def native_value(self) -> float | None:
        """目前參數值。"""
        value = self.coordinator.params.get(self.entity_description.param)
        if value is None:
            return None
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        """寫入參數。"""
        if self.entity_description.param == PARAM_BATTERY_START_V:
            self._validate_voltage_gap(float(value))

        try:
            await self.coordinator.async_write_param(
                self.entity_description.param, value
            )
        except SoyoDGDeviceOfflineError as err:
            raise HomeAssistantError(
                f"設備目前離線,無法寫入參數: {err}"
            ) from err
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"寫入參數失敗: {err}") from err

    def _validate_voltage_gap(self, start_v: float) -> None:
        """啟動電壓至少要比欠壓保護值高 2V,否則設備會拒絕。"""
        protect = self.coordinator.params.get(PARAM_BATTERY_PROTECT_V)
        if protect is None:
            return
        if start_v < float(protect) + VOLTAGE_GAP_MIN:
            raise HomeAssistantError(
                f"啟動電壓必須至少高於欠壓保護值 {VOLTAGE_GAP_MIN} V"
                f"(目前保護值 {protect} V)"
            )
