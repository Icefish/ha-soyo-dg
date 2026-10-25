"""DataUpdateCoordinator for the SOYO-DG inverter.

每個輪詢週期會抓:
  * GET /devices              → 裝置清單(在線狀態、最後上線時間)
  * GET /devices/{sn}/realtime → 即時遙測
  * GET /devices/{sn}/stats    → 發電量統計
  * GET /devices/{sn}/stat-history → 每日 / 每月發電量
  * GET /devices/{sn}/params   → 設備參數(讀不到時保留上一次的值)
"""
from __future__ import annotations

import inspect
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SoyoDGApiError,
    SoyoDGAuthError,
    SoyoDGClient,
    SoyoDGDeviceOfflineError,
    SoyoDGError,
    build_params_payload,
    parse_reported_at,
)
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_SECONDS,
    DOMAIN,
    PARAM_KEYS,
    voltage_range as get_voltage_range,
)

_LOGGER = logging.getLogger(__name__)

#: HA 2025.x 之後 DataUpdateCoordinator 多了一個 config_entry 參數,
#: 不傳的話新版會跳 usage warning;舊版根本沒有這個參數,所以要先偵測。
_COORDINATOR_TAKES_CONFIG_ENTRY = (
    "config_entry" in inspect.signature(DataUpdateCoordinator.__init__).parameters
)


class SoyoDGCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """輪詢 soyo-dg 雲端並把資料整理成 dict。"""

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        client: SoyoDGClient,
        device_sn: str,
        device_name: str,
        entry: ConfigEntry | None = None,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        stale_seconds: int = DEFAULT_STALE_SECONDS,
    ) -> None:
        extra: dict[str, Any] = {}
        if entry is not None and _COORDINATOR_TAKES_CONFIG_ENTRY:
            extra["config_entry"] = entry

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}:{device_sn}",
            update_interval=timedelta(seconds=scan_interval),
            **extra,
        )
        self.client = client
        self.device_sn = device_sn
        self.device_name = device_name
        self.stale_seconds = stale_seconds

        self.data: dict[str, Any] = {
            "device": {},
            "realtime": {},
            "stats": {},
            "history": {},
            "params": {},
            "params_available": False,
        }

    # -----------------------------------------------------------------
    # 資料存取
    # -----------------------------------------------------------------
    @property
    def realtime(self) -> dict[str, Any]:
        """最新即時遙測。"""
        return self.data.get("realtime") or {}

    @property
    def stats(self) -> dict[str, Any]:
        """最新發電量統計。"""
        return self.data.get("stats") or {}

    @property
    def device(self) -> dict[str, Any]:
        """裝置清單中的那一筆。"""
        return self.data.get("device") or {}

    @property
    def params(self) -> dict[str, Any]:
        """設備參數(讀不到時為空 dict)。"""
        return self.data.get("params") or {}

    @property
    def params_available(self) -> bool:
        """目前是否讀得到設備參數。"""
        return bool(self.data.get("params_available"))

    @property
    def reported_at(self) -> datetime | None:
        """設備最後回報資料的時間。"""
        return parse_reported_at(self.realtime.get("reported_at"))

    @property
    def data_age(self) -> float | None:
        """資料年齡(秒)。"""
        reported = self.reported_at
        if reported is None:
            return None
        return (datetime.now(timezone.utc) - reported).total_seconds()

    @property
    def is_stale(self) -> bool:
        """資料是否已過期。"""
        age = self.data_age
        if age is None:
            return True
        return age > self.stale_seconds

    @property
    def model(self) -> str | None:
        """設備型號(電壓區間要從這裡面的 BAT:xxV 推)。"""
        return self.realtime.get("model") or self.device.get("model")

    @property
    def voltage_range(self) -> tuple[int, int]:
        """電壓參數的合法區間,依電池標稱電壓決定。"""
        return get_voltage_range(self.model)

    # -----------------------------------------------------------------
    # 輪詢
    # -----------------------------------------------------------------
    async def _async_update_data(self) -> dict[str, Any]:
        """抓取一輪資料。"""
        try:
            devices = await self.client.async_get_devices()
        except SoyoDGAuthError as err:
            raise UpdateFailed(f"認證失敗: {err}") from err
        except SoyoDGError as err:
            raise UpdateFailed(f"無法取得裝置清單: {err}") from err

        device = next(
            (d for d in devices if d.get("sn") == self.device_sn),
            {},
        )

        try:
            realtime = await self.client.async_get_realtime(self.device_sn)
        except SoyoDGAuthError as err:
            raise UpdateFailed(f"認證失敗: {err}") from err
        except SoyoDGError as err:
            raise UpdateFailed(f"無法取得即時資料: {err}") from err

        # stats / history 失敗不影響主要遙測
        try:
            stats = await self.client.async_get_stats(self.device_sn)
        except SoyoDGError as err:
            _LOGGER.debug("取得統計資料失敗: %s", err)
            stats = self.stats

        try:
            history = await self.client.async_get_stat_history(self.device_sn)
        except SoyoDGError as err:
            _LOGGER.debug("取得歷史資料失敗: %s", err)
            history = self.data.get("history") or {}

        # 參數:設備離線時讀不到,保留上一次成功讀到的值
        params_available = False
        params = self.params
        try:
            fetched = await self.client.async_get_params(self.device_sn)
            if fetched:
                params = {key: fetched.get(key) for key in PARAM_KEYS if key in fetched}
                params_available = True
        except SoyoDGDeviceOfflineError as err:
            _LOGGER.debug("設備離線,無法讀取參數: %s", err)
        except SoyoDGApiError as err:
            _LOGGER.debug("讀取參數失敗: %s", err)
        except SoyoDGError as err:
            _LOGGER.debug("讀取參數失敗: %s", err)

        return {
            "device": device,
            "realtime": realtime,
            "stats": stats,
            "history": history,
            "params": params,
            "params_available": params_available,
        }

    # -----------------------------------------------------------------
    # 參數寫入
    # -----------------------------------------------------------------
    async def async_write_param(self, key: str, value: Any) -> dict[str, Any]:
        """改單一參數並送出完整參數集合。

        ``PUT /devices/{sn}/params`` 是整組覆蓋,少一個欄位就會被清掉,
        所以這裡一定會把目前讀到的所有參數一起帶上去。
        """
        current = dict(self.params)
        if not current:
            # 還沒讀到過參數,先讀一次再寫
            fetched = await self.client.async_get_params(self.device_sn)
            current = {
                param: fetched[param] for param in PARAM_KEYS if param in fetched
            }

        payload = build_params_payload(current, key, value)

        result = await self.client.async_set_params(self.device_sn, payload)

        self.data = {
            **self.data,
            "params": payload,
            "params_available": True,
        }
        await self.async_request_refresh()
        return result
