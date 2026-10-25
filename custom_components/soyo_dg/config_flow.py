"""Config flow for the SOYO-DG inverter integration.

流程:

  step user      → 選認證方式(refresh token / 帳號密碼)
  step token     → 貼上 refresh token
  step account   → 帳號 + 密碼
  step device    → 從帳號底下的裝置清單選一台(或直接用 SN)
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SoyoDGAuthError, SoyoDGClient, SoyoDGError
from .const import (
    CONF_DEVICE_SN,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MODE_ACCOUNT,
    MODE_TOKEN,
    SCAN_INTERVAL_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

CONF_AUTH_MODE = "auth_mode"

TOKEN_HELP = (
    "在已登入 web.soyo-dg.com 的瀏覽器按 F12 → Console → 貼上這行並按 Enter,"
    "然後把複製到的值貼到下面:\n"
    "copy(localStorage.getItem('nbq_refresh_token'))"
)


class SoyoDGConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SOYO-DG."""

    VERSION = 1

    def __init__(self) -> None:
        self._auth_mode: str = MODE_TOKEN
        self._data: dict[str, Any] = {}
        self._devices: list[dict[str, Any]] = []

    # -----------------------------------------------------------------
    # Step 1:選認證方式
    # -----------------------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """選擇認證方式。"""
        if user_input is not None:
            self._auth_mode = user_input[CONF_AUTH_MODE]
            if self._auth_mode == MODE_TOKEN:
                return await self.async_step_token()
            return await self.async_step_account()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_MODE, default=MODE_TOKEN): vol.In(
                        {
                            MODE_TOKEN: "Refresh token(推薦,不用交出帳號密碼)",
                            MODE_ACCOUNT: "帳號 + 密碼",
                        }
                    )
                }
            ),
        )

    # -----------------------------------------------------------------
    # Step 2a:refresh token
    # -----------------------------------------------------------------
    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """貼上 refresh token。"""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_REFRESH_TOKEN].strip()
            client = SoyoDGClient(async_get_clientsession(self.hass))
            try:
                await client.async_set_tokens(token)
                devices = await client.async_get_devices()
            except SoyoDGAuthError as err:
                _LOGGER.warning("refresh token 驗證失敗: %s", err)
                errors["base"] = "invalid_auth"
            except SoyoDGError as err:
                _LOGGER.warning("連線失敗: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("未預期的錯誤")
                errors["base"] = "unknown"
            else:
                self._auth_mode = MODE_TOKEN
                self._data = {CONF_REFRESH_TOKEN: token}
                self._devices = devices
                return await self.async_step_device()

        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema({vol.Required(CONF_REFRESH_TOKEN): str}),
            errors=errors,
            description_placeholders={"help": TOKEN_HELP},
        )

    # -----------------------------------------------------------------
    # Step 2b:帳號密碼
    # -----------------------------------------------------------------
    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """帳號 + 密碼登入。"""
        errors: dict[str, str] = {}

        if user_input is not None:
            client = SoyoDGClient(async_get_clientsession(self.hass))
            try:
                await client.async_login(
                    user_input[CONF_USERNAME].strip(),
                    user_input[CONF_PASSWORD],
                )
                devices = await client.async_get_devices()
            except SoyoDGAuthError as err:
                _LOGGER.warning("帳號登入失敗: %s", err)
                errors["base"] = "invalid_auth"
            except SoyoDGError as err:
                _LOGGER.warning("連線失敗: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("未預期的錯誤")
                errors["base"] = "unknown"
            else:
                self._auth_mode = MODE_ACCOUNT
                self._data = {
                    CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                self._devices = devices
                return await self.async_step_device()

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    # -----------------------------------------------------------------
    # Step 3:選裝置
    # -----------------------------------------------------------------
    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """從裝置清單挑一台。"""
        errors: dict[str, str] = {}

        if user_input is not None:
            sn = user_input[CONF_DEVICE_SN]
            await self.async_set_unique_id(sn)
            self._abort_if_unique_id_configured()

            name = sn
            for device in self._devices:
                if device.get("sn") == sn:
                    name = device.get("name") or sn
                    break

            return self.async_create_entry(
                title=name,
                data={
                    **self._data,
                    CONF_DEVICE_SN: sn,
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                },
            )

        options: dict[str, str] = {}
        for device in self._devices:
            sn = device.get("sn")
            if not sn:
                continue
            label = device.get("name") or sn
            model = device.get("model")
            if model:
                label = f"{label} ({model})"
            options[str(sn)] = label

        if not options:
            return self.async_show_form(
                step_id="device",
                data_schema=vol.Schema(
                    {vol.Required(CONF_DEVICE_SN): str}
                ),
                errors={"base": "no_device_found"},
            )

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE_SN): vol.In(options)}
            ),
            errors=errors,
        )

    # -----------------------------------------------------------------
    # 重新設定
    # -----------------------------------------------------------------
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """重新設定認證資訊。"""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input.get(CONF_REFRESH_TOKEN, "").strip()
            username = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "")

            client = SoyoDGClient(async_get_clientsession(self.hass))
            try:
                if token:
                    await client.async_set_tokens(token)
                    updates = {CONF_REFRESH_TOKEN: token}
                else:
                    await client.async_login(username, password)
                    updates = {
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    }
            except SoyoDGAuthError as err:
                _LOGGER.warning("重新認證失敗: %s", err)
                errors["base"] = "invalid_auth"
            except SoyoDGError as err:
                _LOGGER.warning("連線失敗: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=updates)

        current_token = entry.data.get(CONF_REFRESH_TOKEN, "")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_REFRESH_TOKEN, default=current_token
                    ): str,
                    vol.Optional(CONF_USERNAME, default=""): str,
                    vol.Optional(CONF_PASSWORD, default=""): str,
                }
            ),
            errors=errors,
            description_placeholders={"help": TOKEN_HELP},
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlow:
        """取得選項流程。"""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """設定輪詢間隔。"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """顯示 / 儲存選項。"""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=current
                    ): vol.In(SCAN_INTERVAL_OPTIONS)
                }
            ),
        )
