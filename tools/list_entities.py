#!/usr/bin/env python3
"""列出整合實際註冊的所有實體(用於核對社群文裡的數字)。

跑法:
    SSL_CERT_FILE=/etc/ssl/cert.pem <venv>/bin/python tools/list_entities.py
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
    """開 mock server、把整合載進 HA,然後印出所有實體。"""
    from homeassistant import config_entries, loader
    from homeassistant.bootstrap import async_load_base_functionality
    from homeassistant.core import CoreState, HomeAssistant
    from homeassistant.helpers import entity_registry as er
    from homeassistant.setup import async_setup_component

    mock = Mock()
    mock.device_status = 1
    base = await mock.start()
    os.environ["SOYO_DG_API_BASE"] = f"{base}/api/v1"

    config_dir = Path(tempfile.mkdtemp(prefix="ha_soyo_list_"))
    (config_dir / "configuration.yaml").write_text(
        "homeassistant:\n  name: Test\n  latitude: 0\n  longitude: 0\n"
        "  elevation: 0\n  unit_system: metric\n  time_zone: Asia/Taipei\n",
        encoding="utf-8",
    )
    shutil.copytree(COMPONENT_DIR, config_dir / "custom_components" / "soyo_dg")

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
        title="List",
        data={"refresh_token": "refresh-1", "device_sn": "SNY00000001", "scan_interval": 30},
        options={},
        source="user",
        unique_id="SNY00000001",
        entry_id="soylisttest001",
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()

    by_domain: dict[str, list[str]] = {}
    registry = er.async_get(hass)
    for reg in registry.entities.values():
        if not reg.unique_id or not reg.unique_id.startswith("SNY00000001_"):
            continue
        state = hass.states.get(reg.entity_id)
        by_domain.setdefault(reg.domain, []).append(
            (
                reg.entity_id,
                state.attributes.get("friendly_name") if state else reg.original_name,
                state.state if state else "n/a",
            )
        )

    total = 0
    for domain in sorted(by_domain):
        rows = sorted(by_domain[domain])
        print(f"\n=== {domain} ({len(rows)}) ===")
        for eid, name, value in rows:
            print(f"  {eid:58} {str(name):24} = {value}")
        total += len(rows)
    print(f"\n總計: {total} 個實體")

    await hass.async_stop()
    await mock.stop()
    shutil.rmtree(config_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
