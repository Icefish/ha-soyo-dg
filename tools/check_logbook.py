#!/usr/bin/env python3
"""檢查哪些實體會被 HA 寫進 logbook(造成活動列表一直跳)。

HA 的 logbook 會跳過「連續型」sensor:有 unit_of_measurement、
state_class,或數字型 device_class 的。但 TIMESTAMP / DATE / ENUM
這三種 device_class 被列為 NON_NUMERIC,不享受這個待遇。

跑法:
    SSL_CERT_FILE=/etc/ssl/cert.pem <venv>/bin/python tools/check_logbook.py
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


async def main() -> None:
    """開 mock server、載入整合,然後用 HA 自己的邏輯判斷每個實體。"""
    from homeassistant import config_entries, loader
    from homeassistant.bootstrap import async_load_base_functionality
    from homeassistant.components.logbook.helpers import is_sensor_continuous
    from homeassistant.core import CoreState, HomeAssistant
    from homeassistant.helpers import entity_registry as er
    from homeassistant.setup import async_setup_component

    mock = Mock()
    mock.device_status = 1
    base = await mock.start()
    os.environ["SOYO_DG_API_BASE"] = f"{base}/api/v1"

    config_dir = Path(tempfile.mkdtemp(prefix="ha_soyo_lb_"))
    (config_dir / "configuration.yaml").write_text(
        "homeassistant:\n  name: Test\n  latitude: 0\n  longitude: 0\n"
        "  elevation: 0\n  unit_system: metric\n  time_zone: Asia/Taipei\n",
        encoding="utf-8",
    )
    (config_dir / "custom_components").mkdir()
    (config_dir / "custom_components" / "soyo_dg").symlink_to(COMPONENT_DIR)

    hass = HomeAssistant(str(config_dir))
    loader.async_setup(hass)
    hass.config.skip_pip = True
    hass.config.skip_pip_packages = []
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await async_load_base_functionality(hass)
    await async_setup_component(hass, "network", {})
    hass.set_state(CoreState.running)

    entry = config_entries.ConfigEntry(
        version=1,
        minor_version=1,
        domain="soyo_dg",
        title="Check",
        data={"refresh_token": "refresh-1", "device_sn": "SNY00000001", "scan_interval": 30},
        options={},
        source="user",
        unique_id="SNY00000001",
        entry_id="soyolbtest0001",
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    noisy: list[str] = []
    print(f"{'實體':<52} {'device_class':<22} {'結果'}")
    print("-" * 100)
    for reg in sorted(ent_reg.entities.values(), key=lambda r: r.entity_id):
        if not reg.unique_id or not reg.unique_id.startswith("SNY00000001_"):
            continue
        if reg.domain != "sensor":
            continue
        state = hass.states.get(reg.entity_id)
        dc = state.attributes.get("device_class") if state else reg.device_class
        continuous = is_sensor_continuous(hass, ent_reg, reg.entity_id)
        if continuous:
            verdict = "安靜(有 unit/state_class/數字 device_class)"
        else:
            verdict = "⚠ 會寫進 logbook"
            noisy.append(reg.entity_id)
        print(f"  {reg.entity_id:<50} {str(dc):<20} {verdict}")

    print(f"\n會跳活動列表的實體: {len(noisy)}")
    for n in noisy:
        print(f"  - {n}")

    await hass.async_stop()
    await mock.stop()
    shutil.rmtree(config_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
