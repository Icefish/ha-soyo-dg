#!/usr/bin/env python3
"""soyo_dg 端對端測試 — 真的把 Home Assistant 開起來載入整合。

流程:
  1. 開一個本機 mock server 假冒 soyo-dg 平台
  2. 用環境變數把整合的 API 根路徑指過去
  3. 在暫存目錄起一個 Home Assistant,把 custom_components/soyo_dg 放進去
  4. 建立 config entry、載入整合
  5. 檢查實體有沒有正確建立、數值對不對、寫入有沒有送出正確的參數

跑法:

    cd /tmp && /Users/icefish/Work/soyo-dg/.venv/bin/python \
        /Users/icefish/Work/soyo-dg/tools/test_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import MappingProxyType

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

COMPONENT_DIR = TOOLS_DIR.parent / "custom_components" / "soyo_dg"

from mock_soyo import Mock  # noqa: E402

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
    """執行端對端測試。"""
    mock = Mock()
    mock.device_status = 1  # 正常運作中的設備
    base = await mock.start()
    os.environ["SOYO_DG_API_BASE"] = f"{base}/api/v1"
    print(f"mock server: {base}")
    print(f"SOYO_DG_API_BASE={os.environ['SOYO_DG_API_BASE']}\n")

    config_dir = Path(tempfile.mkdtemp(prefix="ha_soyo_test_"))
    (config_dir / "configuration.yaml").write_text(
        "homeassistant:\n  name: Test\n  latitude: 0\n  longitude: 0\n  elevation: 0\n  unit_system: metric\n  time_zone: Asia/Taipei\n",
        encoding="utf-8",
    )
    custom_components = config_dir / "custom_components"
    custom_components.mkdir()
    (custom_components / "soyo_dg").symlink_to(COMPONENT_DIR)
    print(f"HA config dir: {config_dir}")

    from homeassistant import config_entries, loader
    from homeassistant.bootstrap import async_load_base_functionality
    from homeassistant.core import CoreState, HomeAssistant
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from homeassistant.setup import async_setup_component

    hass = HomeAssistant(str(config_dir))
    loader.async_setup(hass)
    hass.config.skip_pip = True
    hass.config.skip_pip_packages = []
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await async_load_base_functionality(hass)
    # aiohttp client 需要 network component 提供網路介面資訊
    await async_setup_component(hass, "network", {})
    hass.set_state(CoreState.running)

    try:
        # ---------- 載入整合 ----------
        print("\n[1] 載入 config entry")
        entry = config_entries.ConfigEntry(
            version=1,
            minor_version=1,
            domain="soyo_dg",
            title="SNY00000001",
            data={
                "refresh_token": "refresh-1",
                "device_sn": "SNY00000001",
                "scan_interval": 30,
            },
            options={},
            source="user",
            unique_id="SNY00000001",
            entry_id="soyodgtest0001",
            discovery_keys=MappingProxyType({}),
            subentries_data=None,
        )
        await hass.config_entries.async_add(entry)
        await hass.async_block_till_done()

        check(
            "config entry 載入成功",
            entry.state is config_entries.ConfigEntryState.LOADED,
            f"state={entry.state}",
        )
        if entry.state is not config_entries.ConfigEntryState.LOADED:
            print("\n錯誤紀錄:")
            for component, errors in hass.config.components.items():
                if errors:
                    print(f"  {component}: {errors}")
            return 1

        # ---------- 實體 ----------
        print("\n[2] 實體建立")
        ent_reg = er.async_get(hass)
        entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        # 同一個 key 可能同時出現在不同 domain(sensor / select),要用 (domain, key) 當索引
        by_key = {
            (e.domain, e.unique_id.split("_", 1)[1]): e
            for e in entities
            if "_" in e.unique_id
        }

        expected = [
            ("sensor", "power"), ("sensor", "dc_voltage"), ("sensor", "dc_current"),
            ("sensor", "ac_voltage"), ("sensor", "ac_frequency"),
            ("sensor", "temperature"), ("sensor", "collector_power"),
            ("sensor", "peak_power"), ("sensor", "today_energy"),
            ("sensor", "total_energy"), ("sensor", "month_energy"),
            ("sensor", "yesterday_energy"), ("sensor", "data_age"),
            ("sensor", "last_reported"), ("sensor", "work_mode"),
            ("sensor", "power_status"), ("sensor", "error_message"),
            ("sensor", "notice_message"), ("sensor", "model"),
            ("binary_sensor", "connectivity"),
            ("binary_sensor", "collector_connected"),
            ("binary_sensor", "data_fresh"), ("binary_sensor", "fault"),
            ("select", "work_mode"), ("number", "delay_start_sec"),
            ("number", "battery_out_w"), ("number", "battery_start_v"),
            ("number", "battery_protect_v"), ("button", "reboot"),
        ]
        for domain, key in expected:
            check(f"實體 {domain}.{key} 有建立", (domain, key) in by_key)

        # ---------- 數值 ----------
        print("\n[3] 感測器數值")

        def state_of(domain: str, key: str):
            e = by_key.get((domain, key))
            if e is None:
                return None
            return hass.states.get(e.entity_id)

        s = state_of("sensor", "power")
        check("power = 285", s is not None and s.state == "285", s.state if s else "None")
        check("power 單位是 W", s is not None and s.attributes.get("unit_of_measurement") == "W")

        s = state_of("sensor", "dc_voltage")
        check("dc_voltage = 46.7", s is not None and s.state == "46.7", s.state if s else "None")

        s = state_of("sensor", "ac_voltage")
        check("ac_voltage = 233", s is not None and s.state == "233", s.state if s else "None")

        s = state_of("sensor", "temperature")
        check("temperature = 39", s is not None and s.state == "39", s.state if s else "None")
        check("temperature 單位是 °C", s is not None and s.attributes.get("unit_of_measurement") == "°C")

        s = state_of("sensor", "today_energy")
        check("today_energy = 1.1", s is not None and s.state == "1.1", s.state if s else "None")
        check("today_energy 單位是 kWh", s is not None and s.attributes.get("unit_of_measurement") == "kWh")

        s = state_of("sensor", "total_energy")
        check("total_energy = 3.7", s is not None and s.state == "3.7", s.state if s else "None")
        check(
            "total_energy 是 total_increasing",
            s is not None and s.attributes.get("state_class") == "total_increasing",
        )

        s = state_of("sensor", "month_energy")
        check("month_energy = 3.29", s is not None and s.state == "3.29", s.state if s else "None")

        s = state_of("sensor", "power_status")
        check("power_status = working", s is not None and s.state == "working", s.state if s else "None")

        s = state_of("sensor", "work_mode")
        check("work_mode = battery_limit", s is not None and s.state == "battery_limit", s.state if s else "None")

        s = state_of("sensor", "model")
        check(
            "model 有值",
            s is not None and "2.0KW" in (s.state or ""),
            s.state if s else "None",
        )

        s = state_of("binary_sensor", "data_fresh")
        check("data_fresh = on", s is not None and s.state == "on", s.state if s else "None")

        s = state_of("binary_sensor", "connectivity")
        check(
            "connectivity = on(設備 status=1)",
            s is not None and s.state == "on",
            s.state if s else "None",
        )

        s = state_of("binary_sensor", "collector_connected")
        check("collector_connected = on", s is not None and s.state == "on", s.state if s else "None")

        # ---------- 裝置註冊 ----------
        print("\n[4] 裝置註冊")
        dev_reg = dr.async_get(hass)
        devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        check("註冊了 1 個裝置", len(devices) == 1, f"got {len(devices)}")
        if devices:
            check("裝置序號正確", devices[0].serial_number == "SNY00000001")
            check("廠牌是 SOYO", devices[0].manufacturer == "SOYO")
            check(
                "型號有帶上",
                "2.0KW" in (devices[0].model or ""),
                str(devices[0].model),
            )

        # ---------- 寫入參數 ----------
        print("\n[5] 寫入設備參數")
        num_entity = by_key.get(("number", "battery_out_w"))
        check("battery_out_w 實體存在", num_entity is not None)
        if num_entity is not None:
            mock.params_written = None
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": num_entity.entity_id, "value": 1500},
                blocking=True,
            )
            await hass.async_block_till_done()
            written = mock.params_written or {}
            check("PUT 有送出", bool(written), str(written))
            check("新值 1500 有帶上", written.get("battery_out_w") == 1500, str(written))
            check(
                "其他參數沒被清掉",
                written.get("work_mode") == 4
                and written.get("battery_start_v") == 48
                and written.get("battery_protect_v") == 42
                and written.get("delay_start_sec") == 30,
                str(written),
            )

        sel_entity = by_key.get(("select", "work_mode"))
        if sel_entity is not None:
            mock.params_written = None
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": sel_entity.entity_id, "option": "pv"},
                blocking=True,
            )
            await hass.async_block_till_done()
            written = mock.params_written or {}
            check("select 寫入 work_mode = 1", written.get("work_mode") == 1, str(written))
            check(
                "select 也帶完整參數",
                set(written.keys())
                == {"work_mode", "delay_start_sec", "battery_out_w", "battery_start_v", "battery_protect_v"},
                str(sorted(written.keys())),
            )

        # ---------- 重啟 ----------
        print("\n[6] 重啟按鈕")
        btn = by_key.get(("button", "reboot"))
        check("reboot 實體存在", btn is not None)
        if btn is not None:
            mock.rebooted = False
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": btn.entity_id},
                blocking=True,
            )
            await hass.async_block_till_done()
            check("reboot 指令有送出", mock.rebooted is True)

        # ---------- 卸載 ----------
        print("\n[7] 卸載")
        unload_ok = await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        check("可以卸載", unload_ok is True)
        check(
            "卸載後狀態是 NOT_LOADED",
            entry.state is config_entries.ConfigEntryState.NOT_LOADED,
            f"state={entry.state}",
        )

    finally:
        try:
            await hass.async_stop()
        except Exception:  # noqa: BLE001
            pass
        await mock.stop()
        shutil.rmtree(config_dir, ignore_errors=True)

    print(f"\n{'=' * 60}")
    print(f"通過 {len(PASSED)} 項,失敗 {len(FAILED)} 項")
    for failure in FAILED:
        print(f"  FAILED: {failure}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_tests()))
