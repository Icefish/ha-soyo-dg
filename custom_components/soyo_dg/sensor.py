"""感測器平台 — 逆變器的電氣量與狀態。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    POWER_STATUS_STANDBY,
    POWER_STATUS_WORKING,
    WORK_MODE_OPTIONS,
)
from .coordinator import SoyoDGCoordinator
from .entity import SoyoDGEntity


@dataclass(frozen=True, kw_only=True)
class SoyoDGSensorDescription(SensorEntityDescription):
    """感測器描述。

    ``source_keys`` 會依序在 realtime → stats → device 三個來源找第一個有值的欄位。
    """

    source_keys: tuple[str, ...]


SENSORS: tuple[SoyoDGSensorDescription, ...] = (
    SoyoDGSensorDescription(
        key="power",
        source_keys=("power",),
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SoyoDGSensorDescription(
        key="dc_voltage",
        source_keys=("dc_voltage",),
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
    ),
    SoyoDGSensorDescription(
        key="dc_current",
        source_keys=("dc_current",),
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
    ),
    SoyoDGSensorDescription(
        key="ac_voltage",
        source_keys=("ac_voltage",),
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
    ),
    SoyoDGSensorDescription(
        key="ac_frequency",
        source_keys=("ac_frequency",),
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        suggested_display_precision=2,
    ),
    SoyoDGSensorDescription(
        key="temperature",
        source_keys=("temperature",),
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SoyoDGSensorDescription(
        key="collector_power",
        source_keys=("collector_power",),
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SoyoDGSensorDescription(
        key="peak_power",
        source_keys=("peak_power",),
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SoyoDGSensorDescription(
        key="today_energy",
        source_keys=("today_energy",),
        device_class=SensorDeviceClass.ENERGY,
        # 每日重置,所以是 total(會下降),不是 total_increasing
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
    ),
    SoyoDGSensorDescription(
        key="total_energy",
        source_keys=("total_energy",),
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
    ),
    SoyoDGSensorDescription(
        key="month_energy",
        source_keys=("month_energy",),
        device_class=SensorDeviceClass.ENERGY,
        # 每月重置,同上
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """建立感測器。"""
    coordinator: SoyoDGCoordinator = hass.data["soyo_dg"][entry.entry_id]

    entities: list[SoyoDGEntity] = [
        SoyoDGSensor(coordinator, entry, description) for description in SENSORS
    ]
    entities.append(SoyoDGEnergyHistorySensor(coordinator, entry, "yesterday_energy"))
    entities.append(SoyoDGDataAgeSensor(coordinator, entry, "data_age"))
    entities.append(SoyoDGLastReportedSensor(coordinator, entry, "last_reported"))
    entities.append(SoyoDGTextSensor(coordinator, entry, "work_mode"))
    entities.append(SoyoDGTextSensor(coordinator, entry, "power_status"))
    entities.append(SoyoDGTextSensor(coordinator, entry, "error_message"))
    entities.append(SoyoDGTextSensor(coordinator, entry, "notice_message"))
    entities.append(SoyoDGTextSensor(coordinator, entry, "model"))

    async_add_entities(entities)


class SoyoDGSensor(SoyoDGEntity, SensorEntity):
    """一般數值感測器。"""

    entity_description: SoyoDGSensorDescription

    def __init__(
        self,
        coordinator: SoyoDGCoordinator,
        entry: ConfigEntry,
        description: SoyoDGSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description
        self._attr_translation_key = description.key

    @property
    def native_value(self) -> Any:
        """回傳感測器數值。"""
        value = self._get(*self.entity_description.source_keys)
        if isinstance(value, (int, float)):
            return value
        return None


class SoyoDGEnergyHistorySensor(SoyoDGEntity, SensorEntity):
    """昨日發電量(來自 stat-history 的 daily 陣列)。"""

    _attr_device_class = SensorDeviceClass.ENERGY
    # 昨日總量,是固定值(每天換一次),屬於 total
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(
        self, coordinator: SoyoDGCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key

    @property
    def native_value(self) -> float | None:
        """從每日紀錄裡找出昨天那筆。"""
        daily = (self.coordinator.data.get("history") or {}).get("daily") or []
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        for record in daily:
            if isinstance(record, dict) and record.get("date") == yesterday:
                energy = record.get("energy")
                if isinstance(energy, (int, float)):
                    return float(energy)
        return None


class SoyoDGDataAgeSensor(SoyoDGEntity, SensorEntity):
    """資料年齡(距離設備最後回報幾秒)。"""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self, coordinator: SoyoDGCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key

    @property
    def native_value(self) -> float | None:
        """回傳資料年齡(秒)。"""
        age = self.coordinator.data_age
        return None if age is None else round(age, 1)


class SoyoDGLastReportedSensor(SoyoDGEntity, SensorEntity):
    """設備最後回報資料的時間。"""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self, coordinator: SoyoDGCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key

    @property
    def native_value(self) -> datetime | None:
        """回傳最後回報時間。"""
        return self.coordinator.reported_at


class SoyoDGTextSensor(SoyoDGEntity, SensorEntity):
    """文字狀態感測器(模式、狀態、訊息)。"""

    _attr_icon = "mdi:information-outline"

    def __init__(
        self, coordinator: SoyoDGCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key
        self._key = key

    @property
    def native_value(self) -> str | None:
        """回傳文字內容。"""
        if self._key == "work_mode":
            mode = self._get("work_mode")
            if mode is None:
                return None
            return WORK_MODE_OPTIONS.get(int(mode), str(mode))

        if self._key == "power_status":
            status = self._get("power_status")
            if status is None:
                return None
            status = int(status)
            if status == POWER_STATUS_WORKING:
                return "working"
            if status == POWER_STATUS_STANDBY:
                return "standby"
            return "fault"

        if self._key == "error_message":
            return self._get("error_msg") or None

        if self._key == "notice_message":
            return self._get("notice_msg") or None

        if self._key == "model":
            return self._get("model") or None

        return None
