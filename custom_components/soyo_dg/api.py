"""API client for the SOYO-DG (並網逆變器遠端管理平台) cloud.

平台回應格式:

    {"code": 0, "message": "success", "data": {...}}

``code == 0`` 代表成功。**HTTP status 不一定是 4xx/5xx** — 例如設備離線時
``GET /devices/{sn}/params`` 會回 HTTP 502 但 code=50000,所以必須先看信封。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from .const import (
    API_BASE,
    AUTH_ERROR_CODES,
    DEVICE_OFFLINE_CODES,
    PARAM_KEYS,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20


def parse_reported_at(value: Any) -> datetime | None:
    """把 ``reported_at``(ISO 8601,含時區)轉成 datetime。

    平台回的格式像 ``2026-10-25T08:38:15.379858469+08:00``,
    Python 3.11+ 的 ``datetime.fromisoformat`` 可以直接解析。
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def build_params_payload(
    current: dict[str, Any], key: str, value: Any
) -> dict[str, Any]:
    """把單一參數合併進完整參數集合。

    ``PUT /devices/{sn}/params`` 是**整組覆蓋**,少帶一個欄位就會被清成 0,
    所以每次寫入都要把目前已知的參數全部一起送出去。
    """
    merged = dict(current)
    merged[key] = value
    return {param: merged[param] for param in PARAM_KEYS if param in merged}



class SoyoDGError(Exception):
    """Base error for the SOYO-DG API."""


class SoyoDGAuthError(SoyoDGError):
    """認證失敗或 session 過期。"""


class SoyoDGApiError(SoyoDGError):
    """平台回傳錯誤信封。"""

    def __init__(
        self,
        message: str,
        code: int | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class SoyoDGDeviceOfflineError(SoyoDGApiError):
    """雲端連不到設備本身(讀寫參數 / 重啟會失敗)。"""


class SoyoDGClient:
    """SOYO-DG 雲端 API 客戶端。

    認證流程:
      1. ``async_login(username, password)`` → access_token + refresh_token
      2. 或 ``async_set_tokens(refresh_token=...)`` → 直接用 refresh token 換 access token
      3. 每個請求帶 ``Authorization: Bearer <access_token>``
      4. 收到 401 → 自動 ``async_refresh()`` 換新的 access token 後重試一次
    """

    def __init__(
        self,
        session: Any,
        base_url: str = API_BASE,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._username: str | None = None
        self._password: str | None = None

    # -----------------------------------------------------------------
    # 屬性
    # -----------------------------------------------------------------
    @property
    def access_token(self) -> str | None:
        """目前的 access token(刷新後會變動)。"""
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        """目前的 refresh token(平台可能每次刷新都輪替)。"""
        return self._refresh_token

    @property
    def username(self) -> str | None:
        """帳號(若是用 refresh token 模式則為 None)。"""
        return self._username

    # -----------------------------------------------------------------
    # 認證
    # -----------------------------------------------------------------
    async def async_set_tokens(self, refresh_token: str) -> None:
        """用 refresh token 直接換取 access token(不需帳號密碼)。"""
        self._refresh_token = refresh_token.strip()
        self._username = None
        self._password = None
        await self.async_refresh()

    async def async_login(self, username: str, password: str) -> dict[str, Any]:
        """帳號密碼登入。"""
        self._username = username.strip()
        self._password = password

        payload = await self._async_post(
            "/auth/login",
            {"user": self._username, "password": password},
            authenticated=False,
        )
        self._store_tokens(payload)
        return payload

    async def async_refresh(self) -> bool:
        """用 refresh token 換新的 access token。"""
        if not self._refresh_token:
            raise SoyoDGAuthError("沒有 refresh token,無法重新驗證")

        payload = await self._async_post(
            "/auth/refresh",
            {"refresh_token": self._refresh_token},
            authenticated=False,
        )
        self._store_tokens(payload)
        return True

    def _store_tokens(self, payload: dict[str, Any]) -> None:
        """把登入 / 刷新回應裡的 token 存起來。"""
        if not isinstance(payload, dict):
            raise SoyoDGAuthError("認證回應格式不正確")

        access = payload.get("access_token")
        if not access:
            raise SoyoDGAuthError("認證回應缺少 access_token")

        self._access_token = access
        refresh = payload.get("refresh_token")
        if refresh:
            self._refresh_token = refresh

    # -----------------------------------------------------------------
    # 請求
    # -----------------------------------------------------------------
    def _headers(self, authenticated: bool = True) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if authenticated and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def _async_post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        authenticated: bool = True,
    ) -> Any:
        """送出 POST 並解析回應信封。"""
        return await self.async_request(
            "POST", path, json_body=body, authenticated=authenticated
        )

    async def async_request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
        _retry: bool = True,
    ) -> Any:
        """送出請求並解析回應信封,回傳 ``data`` 欄位。

        401 會自動用 refresh token 換證後重試一次。
        """
        url = f"{self._base_url}{path}"
        headers = self._headers(authenticated)

        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=self._timeout,
            ) as response:
                status = response.status
                text = await response.text()
        except Exception as err:  # aiohttp.ClientError / asyncio.TimeoutError
            raise SoyoDGError(f"無法連線到 soyo-dg 平台: {err}") from err

        try:
            payload = json.loads(text) if text else None
        except ValueError:
            payload = None

        if status == 401:
            if authenticated and _retry and self._refresh_token:
                _LOGGER.debug("access token 過期,嘗試用 refresh token 更新")
                try:
                    await self.async_refresh()
                except SoyoDGError as err:
                    raise SoyoDGAuthError(f"重新驗證失敗: {err}") from err
                return await self.async_request(
                    method,
                    path,
                    json_body,
                    authenticated=authenticated,
                    _retry=False,
                )
            raise SoyoDGAuthError("認證失敗或 session 已過期")

        if payload is None:
            raise SoyoDGApiError(
                f"平台回應無法解析 (HTTP {status})", status=status
            )

        code = payload.get("code")
        message = payload.get("message") or ""

        if code != 0:
            if code in AUTH_ERROR_CODES:
                raise SoyoDGAuthError(message or f"認證錯誤 (code {code})")
            if code in DEVICE_OFFLINE_CODES or "離線" in message or "离线" in message:
                raise SoyoDGDeviceOfflineError(
                    message or "設備目前離線,無法讀寫", code=code, status=status
                )
            raise SoyoDGApiError(message or f"平台錯誤 (code {code})", code=code, status=status)

        return payload.get("data")

    # -----------------------------------------------------------------
    # 裝置 API
    # -----------------------------------------------------------------
    async def async_get_devices(self) -> list[dict[str, Any]]:
        """取得帳號下綁定的所有裝置。"""
        data = await self.async_request(
            "GET", "/devices?page=1&page_size=200"
        )
        if not isinstance(data, dict):
            return []
        items = data.get("items") or []
        return [item for item in items if isinstance(item, dict)]

    async def async_get_realtime(self, sn: str) -> dict[str, Any]:
        """即時遙測。"""
        data = await self.async_request("GET", f"/devices/{sn}/realtime")
        return data if isinstance(data, dict) else {}

    async def async_get_stats(self, sn: str) -> dict[str, Any]:
        """發電量統計(累計 / 今日 / 本月 / 峰值)。"""
        data = await self.async_request("GET", f"/devices/{sn}/stats")
        return data if isinstance(data, dict) else {}

    async def async_get_stat_history(self, sn: str) -> dict[str, Any]:
        """歷史發電量(daily / monthly 陣列)。"""
        data = await self.async_request("GET", f"/devices/{sn}/stat-history")
        return data if isinstance(data, dict) else {}

    async def async_get_params(self, sn: str) -> dict[str, Any]:
        """讀取設備參數(設備離線時會失敗)。"""
        data = await self.async_request("GET", f"/devices/{sn}/params")
        return data if isinstance(data, dict) else {}

    async def async_set_params(self, sn: str, params: dict[str, Any]) -> dict[str, Any]:
        """寫入設備參數(必須一次送出完整參數集合)。"""
        data = await self.async_request(
            "PUT", f"/devices/{sn}/params", json_body=params
        )
        return data if isinstance(data, dict) else {}

    async def async_reboot(self, sn: str) -> bool:
        """要求設備重啟。"""
        await self.async_request("POST", f"/devices/{sn}/reboot")
        return True
