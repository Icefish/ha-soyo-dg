"""Constants for the SOYO-DG inverter integration.

資料來源(2026-10-25 由 web.soyo-dg.com 前端 bundle 實測):
  * API 根路徑  https://web.soyo-dg.com/api/v1
  * 認證       Authorization: Bearer <access_token>
  * 回應封裝   {"code": 0, "message": "success", "data": {...}}
                code != 0 代表失敗,HTTP status 不一定是 4xx/5xx
"""
from __future__ import annotations

import os
import re
from typing import Final

DOMAIN: Final = "soyo_dg"

# ---------------------------------------------------------------------
# API 端點
# ---------------------------------------------------------------------
#: 預設的平台 API 根路徑。
#: 測試時可以用環境變數 SOYO_DG_API_BASE 指到本機 mock server。
API_BASE: Final = os.environ.get(
    "SOYO_DG_API_BASE", "https://web.soyo-dg.com/api/v1"
)

#: 官方 Open API(另一套獨立系統,需另外申請 soyo_live_xxx key)
OPENAPI_BASE: Final = "https://api.soyo-dg.com/v1"

# ---------------------------------------------------------------------
# config_flow / 設定項目
# ---------------------------------------------------------------------
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_DEVICE_SN: Final = "device_sn"
CONF_SCAN_INTERVAL: Final = "scan_interval"

#: 認證模式
MODE_TOKEN: Final = "token"        # 只貼 refresh token,HA 不碰帳號密碼(推薦)
MODE_ACCOUNT: Final = "account"    # 帳號 + 密碼

# ---------------------------------------------------------------------
# 輪詢
# ---------------------------------------------------------------------
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 300

#: 資料過期判定(reported_at 距今超過這個秒數就算資料過期)
DEFAULT_STALE_SECONDS: Final = 180

# ---------------------------------------------------------------------
# 錯誤碼
# ---------------------------------------------------------------------
#: 認證相關(缺少 / 過期 / 無效)
AUTH_ERROR_CODES: Final[frozenset[int]] = frozenset({40100, 401, 40300})

#: 裝置本身離線(雲端連不到設備,讀寫參數會失敗)
DEVICE_OFFLINE_CODES: Final[frozenset[int]] = frozenset({50000})

# ---------------------------------------------------------------------
# 設備狀態(GET /devices 回傳的 status 欄位)
# ---------------------------------------------------------------------
STATUS_ONLINE: Final = 1
STATUS_FAULT: Final = 2
STATUS_OFFLINE: Final = 0

# ---------------------------------------------------------------------
# 運行狀態(realtime 的 power_status)
# ---------------------------------------------------------------------
POWER_STATUS_STANDBY: Final = 0
POWER_STATUS_WORKING: Final = 1

# ---------------------------------------------------------------------
# 工作模式(GET/PUT /devices/{sn}/params 的 work_mode)
# ---------------------------------------------------------------------
WORK_MODE_PV: Final = 1               # 光伏模式 — 常规并网发电
WORK_MODE_PV_LIMIT: Final = 2         # 光伏防逆流 — 限制反送电
WORK_MODE_BATTERY_CONSTANT: Final = 3  # 电池恒功率 — 固定电池输出
WORK_MODE_BATTERY_LIMIT: Final = 4     # 电池防反流 — 电池侧防反流

WORK_MODE_OPTIONS: Final[dict[int, str]] = {
    WORK_MODE_PV: "pv",
    WORK_MODE_PV_LIMIT: "pv_limit",
    WORK_MODE_BATTERY_CONSTANT: "battery_constant",
    WORK_MODE_BATTERY_LIMIT: "battery_limit",
}

# ---------------------------------------------------------------------
# 參數鍵名(GET/PUT /devices/{sn}/params)
# ---------------------------------------------------------------------
PARAM_WORK_MODE: Final = "work_mode"
PARAM_DELAY_START_SEC: Final = "delay_start_sec"
PARAM_BATTERY_OUT_W: Final = "battery_out_w"
PARAM_BATTERY_START_V: Final = "battery_start_v"
PARAM_BATTERY_PROTECT_V: Final = "battery_protect_v"

#: PUT /params 必須一次送出完整參數集合,順序無關但欄位不可缺
PARAM_KEYS: Final[tuple[str, ...]] = (
    PARAM_WORK_MODE,
    PARAM_DELAY_START_SEC,
    PARAM_BATTERY_OUT_W,
    PARAM_BATTERY_START_V,
    PARAM_BATTERY_PROTECT_V,
)

#: 讀不到 params 時的預設值(對應網頁版的初始值)
DEFAULT_PARAMS: Final[dict[str, int]] = {
    PARAM_WORK_MODE: WORK_MODE_PV,
    PARAM_DELAY_START_SEC: 30,
    PARAM_BATTERY_OUT_W: 2000,
    PARAM_BATTERY_START_V: 48,
    PARAM_BATTERY_PROTECT_V: 42,
}

# ---------------------------------------------------------------------
# 參數範圍限制
#
# 來源:網頁版「參數設定」頁的實際輸入框限制(2026-10-25 實測)
#   * delay_start_sec → <input type="range" min="1" max="180">
#   * battery_out_w   → <input type="number" min="0" max="10000" step="10">
#   * battery_start_v / battery_protect_v → 文字欄位,3 位數,
#     合法區間依「電池標稱電壓」動態決定(見 voltage_range)
# ---------------------------------------------------------------------
DELAY_START_MIN: Final = 1
DELAY_START_MAX: Final = 180
BATTERY_OUT_W_MIN: Final = 0
BATTERY_OUT_W_MAX: Final = 10000
BATTERY_OUT_W_STEP: Final = 10

#: 電壓輸入框最多 3 位數
BATTERY_VOLTAGE_MAX: Final = 999

#: 啟動電壓至少要比欠壓保護值高 2V
VOLTAGE_GAP_MIN: Final = 2

#: 電池標稱電壓 → 電壓參數的合法區間
#: (網頁版依標稱電壓挑選區間:12V→8~16、24V→18~32、36V→30~49、
#:  48V→40~65、72V→66~98、96V→80~130)
BATTERY_VOLTAGE_BANDS: Final[dict[int, tuple[int, int]]] = {
    12: (8, 16),
    24: (18, 32),
    36: (30, 49),
    48: (40, 65),
    72: (66, 98),
    96: (80, 130),
}

#: 型號字串裡的電池電壓,例如 "2.0KW/PV:55-90V(BAT:48V)/AC:220V"
BATTERY_VOLTAGE_PATTERN: Final = re.compile(r"BAT:(\d+)V", re.IGNORECASE)


def nominal_battery_voltage(model: str | None) -> int | None:
    """從型號字串抓出電池標稱電壓。

    範例:``2.0KW/PV:55-90V(BAT:48V)/AC:220V`` → ``48``
    """
    if not model:
        return None
    match = BATTERY_VOLTAGE_PATTERN.search(model)
    if match is None:
        return None
    return int(match.group(1))


def voltage_range(model: str | None, fallback: int = 48) -> tuple[int, int]:
    """回傳這台機器電壓參數的合法區間。"""
    nominal = nominal_battery_voltage(model) or fallback
    for upper in (12, 24, 36, 48, 72, 96):
        if nominal <= upper:
            return BATTERY_VOLTAGE_BANDS[upper]
    return BATTERY_VOLTAGE_BANDS[96]

# ---------------------------------------------------------------------
# 平台
# ---------------------------------------------------------------------
PLATFORMS: Final[list[str]] = [
    "sensor",
    "binary_sensor",
    "select",
    "number",
    "button",
]

#: 設定項(供 UI 產生 config entry options 用)
SCAN_INTERVAL_OPTIONS: Final[list[int]] = [10, 15, 30, 60, 120, 300]
