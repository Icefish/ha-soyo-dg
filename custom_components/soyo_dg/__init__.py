"""The SOYO-DG inverter integration.

把 web.soyo-dg.com(並網逆變器遠端管理平台)的資料帶進 Home Assistant。

認證方式有兩種:

1. **refresh token**(推薦)— 從網頁版 localStorage 取出 refresh token 貼進來,
   Home Assistant 完全不需要保存你的帳號密碼。平台在 token 過期時會自動輪替,
   整合會把新的 token 存回設定項。
2. **帳號 + 密碼** — 整合自己呼叫 ``POST /auth/login`` 登入並自行續期。
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SoyoDGAuthError, SoyoDGClient, SoyoDGError
from .const import (
    CONF_DEVICE_SN,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import SoyoDGCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORM_SETUP: list[Platform] = [Platform(p) for p in PLATFORMS]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SOYO-DG from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = SoyoDGClient(async_get_clientsession(hass))

    try:
        refresh_token = entry.data.get(CONF_REFRESH_TOKEN)
        if refresh_token:
            await client.async_set_tokens(refresh_token)
        else:
            await client.async_login(
                entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
            )
    except SoyoDGAuthError as err:
        raise ConfigEntryAuthFailed(f"認證失敗: {err}") from err
    except SoyoDGError as err:
        raise ConfigEntryNotReady(f"無法連線到 soyo-dg 平台: {err}") from err

    scan_interval = int(
        entry.options.get(CONF_SCAN_INTERVAL)
        or entry.data.get(CONF_SCAN_INTERVAL)
        or DEFAULT_SCAN_INTERVAL
    )

    device_sn = entry.data[CONF_DEVICE_SN]
    coordinator = SoyoDGCoordinator(
        hass=hass,
        client=client,
        device_sn=device_sn,
        device_name=entry.title or device_sn,
        entry=entry,
        scan_interval=scan_interval,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except Exception as err:
        raise ConfigEntryNotReady(f"無法取得設備資料: {err}") from err

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # 平台會輪替 refresh token,每次更新後把最新的存回設定項
    def _save_tokens() -> None:
        _persist_tokens(hass, entry, client)

    entry.async_on_unload(coordinator.async_add_listener(_save_tokens))
    _save_tokens()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORM_SETUP)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORM_SETUP)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


def _persist_tokens(
    hass: HomeAssistant, entry: ConfigEntry, client: SoyoDGClient
) -> None:
    """把最新的 token 寫回 config entry(有變化才寫)。"""
    new_data: dict[str, Any] = dict(entry.data)

    access = client.access_token
    if access and new_data.get("access_token") != access:
        new_data["access_token"] = access

    refresh = client.refresh_token
    if refresh and new_data.get(CONF_REFRESH_TOKEN) != refresh:
        new_data[CONF_REFRESH_TOKEN] = refresh

    if new_data != dict(entry.data):
        hass.config_entries.async_update_entry(entry, data=new_data)
