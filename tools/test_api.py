#!/usr/bin/env python3
"""soyo_dg API 客戶端測試(單元測試)。

用本機 mock server 重播「2026-10-25 從 web.soyo-dg.com 實測抓到的真實回應」,
檢查 api.py 的行為:認證 header、401 自動換證重試、信封解析、
錯誤分類(認證失敗 / 設備離線)、參數整組寫入、reboot。

跑法(必須在 tools/ 以外的目錄執行,避免 stdlib select 被遮蔽):

    cd /tmp && python3 /Users/icefish/Work/soyo-dg/tools/test_api.py
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

COMPONENT_DIR = TOOLS_DIR.parent / "custom_components" / "soyo_dg"

# 真的 __init__.py 會 import homeassistant,測試時只需要 api.py / const.py,
# 所以手動塞一個空的 package,避免執行到真實的 __init__.py。
_pkg = types.ModuleType("soyo_dg")
_pkg.__path__ = [str(COMPONENT_DIR)]
sys.modules["soyo_dg"] = _pkg

from mock_soyo import Mock  # noqa: E402

from soyo_dg.api import (  # noqa: E402
    SoyoDGAuthError,
    SoyoDGClient,
    SoyoDGDeviceOfflineError,
    SoyoDGError,
    build_params_payload,
    parse_reported_at,
)
from soyo_dg.const import PARAM_KEYS  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """記錄一項測試結果。"""
    if condition:
        PASSED.append(name)
        print(f"  ✓ {name}")
    else:
        FAILED.append(f"{name} — {detail}")
        print(f"  ✗ {name}  {detail}")


async def run_tests() -> int:
    """執行所有測試。"""
    mock = Mock()
    base = await mock.start()
    print(f"mock server: {base}\n")

    import aiohttp

    session = aiohttp.ClientSession()

    try:
        # --- 1. refresh token 登入 ---
        print("[1] refresh token 換 access token")
        client = SoyoDGClient(session, base_url=f"{base}/api/v1")
        await client.async_set_tokens("refresh-1")
        check(
            "access token 已取得",
            client.access_token == "token-2",
            f"got {client.access_token}",
        )
        check(
            "refresh token 已輪替",
            client.refresh_token == "refresh-2",
            f"got {client.refresh_token}",
        )

        # --- 2. 認證 header ---
        print("\n[2] 請求帶 Authorization header")
        mock.calls.clear()
        devices = await client.async_get_devices()
        auth_header = mock.calls[0]["auth"]
        check("帶 Bearer token", auth_header == "Bearer token-2", f"got {auth_header}")
        check("回傳 1 台裝置", len(devices) == 1)
        check("裝置序號正確", devices[0]["sn"] == "SNY00000001")

        # --- 3. 401 自動換證並重試 ---
        print("\n[3] 401 → 自動 refresh → 重試")
        mock.calls.clear()
        mock.fail_next_auth = True
        devices = await client.async_get_devices()
        paths = [c["path"] for c in mock.calls]
        check("有呼叫 refresh", "/api/v1/auth/refresh" in paths, str(paths))
        check(
            "refresh 後 access token 已更新",
            client.access_token == "token-3",
            f"got {client.access_token}",
        )
        check("重試成功拿到資料", len(devices) == 1)
        retry_call = [c for c in mock.calls if c["path"] == "/api/v1/devices"][-1]
        check(
            "重試時用新 token",
            retry_call["auth"] == "Bearer token-3",
            f"got {retry_call['auth']}",
        )

        # --- 4. 即時遙測 ---
        print("\n[4] 即時遙測 / 統計 / 歷史")
        realtime = await client.async_get_realtime("SNY00000001")
        check("power = 285", realtime.get("power") == 285)
        check("dc_voltage = 46.7", realtime.get("dc_voltage") == 46.7)
        check("ac_voltage = 233", realtime.get("ac_voltage") == 233)
        check("temperature = 39", realtime.get("temperature") == 39)
        check("work_mode = 4", realtime.get("work_mode") == 4)

        stats = await client.async_get_stats("SNY00000001")
        check("month_energy = 3.29", stats.get("month_energy") == 3.29)
        check("peak_power = 397", stats.get("peak_power") == 397)

        history = await client.async_get_stat_history("SNY00000001")
        check("daily 有 2 筆", len(history.get("daily") or []) == 2)
        check("monthly 有 1 筆", len(history.get("monthly") or []) == 1)

        # --- 5. 設備離線 ---
        print("\n[5] 設備離線的錯誤分類")
        mock.offline_params = True
        try:
            await client.async_get_params("SNY00000001")
            check("離線時丟出 SoyoDGDeviceOfflineError", False, "沒有丟例外")
        except SoyoDGDeviceOfflineError as err:
            check("離線時丟出 SoyoDGDeviceOfflineError", True)
            check("錯誤訊息保留平台原文", "离线" in str(err), str(err))
        except Exception as err:  # noqa: BLE001
            check(
                "離線時丟出 SoyoDGDeviceOfflineError",
                False,
                f"丟了 {type(err).__name__}",
            )
        mock.offline_params = False

        # --- 6. 參數讀寫 ---
        print("\n[6] 參數讀取 / 整組寫入")
        params = await client.async_get_params("SNY00000001")
        check("讀到 work_mode = 4", params.get("work_mode") == 4)
        check("讀到 battery_out_w = 2000", params.get("battery_out_w") == 2000)

        await client.async_set_params(
            "SNY00000001",
            build_params_payload(params, "battery_out_w", 1500),
        )
        written = mock.params_written or {}
        check(
            "PUT 送出完整參數集合",
            set(written.keys()) == set(PARAM_KEYS),
            f"got {sorted(written.keys())}",
        )
        check("新值有帶上", written.get("battery_out_w") == 1500)
        check(
            "其他參數沒被清掉",
            written.get("battery_start_v") == 48
            and written.get("battery_protect_v") == 42
            and written.get("delay_start_sec") == 30,
            str(written),
        )

        # --- 7. reboot ---
        print("\n[7] 重啟")
        result = await client.async_reboot("SNY00000001")
        check("reboot 已送出", mock.rebooted is True)
        check("reboot 回傳 True", result is True)

        # --- 8. 帳號密碼登入 ---
        print("\n[8] 帳號密碼登入")
        client2 = SoyoDGClient(session, base_url=f"{base}/api/v1")
        await client2.async_login("0000000000", "correct-password")
        check(
            "登入成功拿到 token",
            (client2.access_token or "").startswith("token-"),
            f"got {client2.access_token}",
        )
        check("記住帳號", client2.username == "0000000000")

        client3 = SoyoDGClient(session, base_url=f"{base}/api/v1")
        try:
            await client3.async_login("0000000000", "wrong-password")
            check("密碼錯誤會丟 SoyoDGAuthError", False, "沒有丟例外")
        except SoyoDGAuthError:
            check("密碼錯誤會丟 SoyoDGAuthError", True)

        # --- 9. 純函式 ---
        print("\n[9] 輔助函式")
        parsed = parse_reported_at("2026-10-25T08:38:15.379858469+08:00")
        check("reported_at 可解析", parsed is not None)
        check(
            "時區保留",
            parsed is not None and parsed.utcoffset().total_seconds() == 8 * 3600,
        )
        check("壞值回 None", parse_reported_at("not-a-date") is None)
        check("None 回 None", parse_reported_at(None) is None)

        payload = build_params_payload(
            {"work_mode": 1, "delay_start_sec": 10, "battery_out_w": 1000},
            "battery_start_v",
            48,
        )
        check(
            "build_params_payload 只帶已知欄位",
            set(payload)
            == {"work_mode", "delay_start_sec", "battery_out_w", "battery_start_v"},
            str(sorted(payload)),
        )

        # --- 10. 連線失敗 ---
        print("\n[10] 連線錯誤")
        bad = SoyoDGClient(session, base_url="http://127.0.0.1:1/api/v1")
        try:
            await bad.async_get_devices()
            check("連線失敗丟 SoyoDGError", False, "沒有丟例外")
        except SoyoDGAuthError:
            check("連線失敗丟 SoyoDGError", False, "丟了 AuthError")
        except SoyoDGError:
            check("連線失敗丟 SoyoDGError", True)

    finally:
        await session.close()
        await mock.stop()

    print(f"\n{'=' * 60}")
    print(f"通過 {len(PASSED)} 項,失敗 {len(FAILED)} 項")
    for failure in FAILED:
        print(f"  FAILED: {failure}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_tests()))
