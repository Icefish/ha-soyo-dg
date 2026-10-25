"""soyo-dg 平台的 mock server。

回應內容是 2026-10-25 從 web.soyo-dg.com 實測抓到的真實 payload,
用來離線測試整合(不需要真的帳號密碼)。

給 test_api.py(單元測試)與 test_e2e.py(載入 Home Assistant 的端對端測試)共用。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from aiohttp import web


def now_iso() -> str:
    """現在時間(帶時區),當作設備最後回報時間。"""
    return datetime.now().astimezone().isoformat()

DEVICE_ITEM: dict[str, Any] = {
    "sn": "SNY00000001",
    "name": "SNY00000001",
    "host": "tcp://mqtt.soyo-dg.com:1883",
    "model": "2.0KW/PV:55-90V(BAT:48V)/AC:220V",
    "wifi": "Soyo_00000001",
    "jqm": "00000000",
    "timezone": "",
    "timezone_configured": False,
    "status": 0,
    "last_online_at": "2026-10-25T08:39:25+08:00",
    "bound_at": "2026-10-24T16:08:30+08:00",
    "power": 285,
    "collector_power": 0,
    "dc_voltage": 46.7,
    "dc_current": 6.9,
    "ac_voltage": 233,
    "ac_frequency": 60,
    "temperature": 39,
    "total_energy": 3.7,
    "today_energy": 1.1,
    "month_energy": 3.29,
    "work_mode": 4,
    "power_status": 1,
    "error_msg": "",
    "notice_msg": "",
    "collector_status": 1,
    "reported_at": "2026-10-25T08:38:15.379858469+08:00",
}

DEVICES_BODY: dict[str, Any] = {
    "code": 0,
    "message": "success",
    "data": {"items": [DEVICE_ITEM], "total": 1, "page": 1, "page_size": 200},
}

REALTIME_BODY: dict[str, Any] = {
    "code": 0,
    "message": "success",
    "data": {
        "sn": "SNY00000001",
        "dc_voltage": 46.7,
        "dc_current": 6.9,
        "ac_voltage": 233,
        "ac_frequency": 60,
        "power": 285,
        "collector_power": 0,
        "peak_power": 397,
        "temperature": 39,
        "total_energy": 3.7,
        "today_energy": 1.1,
        "work_mode": 4,
        "power_status": 1,
        "error_msg": "",
        "notice_msg": "",
        "collector_status": 1,
        "reported_at": "2026-10-25T08:38:15.379858469+08:00",
        "model": "2.0KW/PV:55-90V(BAT:48V)/AC:220V",
    },
}

STATS_BODY: dict[str, Any] = {
    "code": 0,
    "message": "success",
    "data": {
        "sn": "SNY00000001",
        "total_energy": 3.7,
        "today_energy": 1.1,
        "month_energy": 3.29,
        "peak_power": 397,
    },
}

HISTORY_BODY: dict[str, Any] = {
    "code": 0,
    "message": "success",
    "data": {
        "sn": "SNY00000001",
        "total_energy": 3.7,
        "today_energy": 1.1,
        "month_energy": 3.29,
        "daily": [
            {"date": "2026-10-24", "energy": 2.19},
            {"date": "2026-10-25", "energy": 1.1},
        ],
        "monthly": [{"date": "2026-10", "energy": 3.29}],
    },
}

PARAMS_BODY: dict[str, Any] = {
    "code": 0,
    "message": "success",
    "data": {
        "work_mode": 4,
        "delay_start_sec": 30,
        "battery_out_w": 2000,
        "battery_start_v": 48,
        "battery_protect_v": 42,
    },
}

# 設備離線時的真實回應(HTTP 502 + code 50000)
OFFLINE_BODY: dict[str, Any] = {
    "code": 50000,
    "message": "设备当前离线，无法读取参数",
    "detail": None,
}


class Mock:
    """記錄請求並回放回應的 mock server。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.tokens: dict[str, str] = {"access": "token-1", "refresh": "refresh-1"}
        self._seq = 1
        self.fail_next_auth = False
        self.device_status = 0
        self.params_written: dict[str, Any] | None = None
        self.rebooted = False
        self.offline_params = False
        self.runner: web.AppRunner | None = None
        self.port: int = 0

    def _rotate(self) -> None:
        """模擬平台輪替 token(每次 refresh / login 都換新的)。"""
        self._seq += 1
        self.tokens = {
            "access": f"token-{self._seq}",
            "refresh": f"refresh-{self._seq}",
        }

    async def _record(self, request: web.Request) -> dict[str, Any]:
        body = await request.text()
        entry = {
            "method": request.method,
            "path": request.path,
            "query": dict(request.query),
            "auth": request.headers.get("Authorization"),
            "body": body,
        }
        self.calls.append(entry)
        return entry

    async def handle_refresh(self, request: web.Request) -> web.Response:
        await self._record(request)
        payload = await request.json()
        if not payload.get("refresh_token"):
            return web.json_response(
                {"code": 40100, "message": "缺少认证信息", "detail": None}, status=401
            )
        self._rotate()
        return web.json_response(
            {
                "code": 0,
                "message": "success",
                "data": {
                    "access_token": self.tokens["access"],
                    "refresh_token": self.tokens["refresh"],
                },
            }
        )

    async def handle_login(self, request: web.Request) -> web.Response:
        await self._record(request)
        payload = await request.json()
        if payload.get("password") != "correct-password":
            return web.json_response(
                {"code": 40100, "message": "账号或密码错误", "detail": None}, status=401
            )
        self._rotate()
        return web.json_response(
            {
                "code": 0,
                "message": "success",
                "data": {
                    "access_token": self.tokens["access"],
                    "refresh_token": self.tokens["refresh"],
                },
            }
        )

    async def handle_devices(self, request: web.Request) -> web.Response:
        entry = await self._record(request)
        if self.fail_next_auth:
            self.fail_next_auth = False
            return web.json_response(
                {"code": 40100, "message": "认证已过期", "detail": None}, status=401
            )
        if entry["auth"] != f"Bearer {self.tokens['access']}":
            return web.json_response(
                {"code": 40100, "message": "缺少认证信息", "detail": None}, status=401
            )
        item = {**DEVICE_ITEM, "status": self.device_status, "reported_at": now_iso()}
        body = {
            "code": 0,
            "message": "success",
            "data": {
                "items": [item],
                "total": 1,
                "page": 1,
                "page_size": 200,
            },
        }
        return web.json_response(body)

    async def handle_realtime(self, request: web.Request) -> web.Response:
        await self._record(request)
        body = {
            "code": 0,
            "message": "success",
            "data": {**REALTIME_BODY["data"], "reported_at": now_iso()},
        }
        return web.json_response(body)

    async def handle_stats(self, request: web.Request) -> web.Response:
        await self._record(request)
        return web.json_response(STATS_BODY)

    async def handle_history(self, request: web.Request) -> web.Response:
        await self._record(request)
        return web.json_response(HISTORY_BODY)

    async def handle_params(self, request: web.Request) -> web.Response:
        await self._record(request)
        if request.method == "PUT":
            self.params_written = await request.json()
            return web.json_response({"code": 0, "message": "success", "data": {}})
        if self.offline_params:
            return web.json_response(OFFLINE_BODY, status=502)
        return web.json_response(PARAMS_BODY)

    async def handle_reboot(self, request: web.Request) -> web.Response:
        await self._record(request)
        self.rebooted = True
        return web.json_response({"code": 0, "message": "success", "data": {}})

    async def start(self) -> str:
        """啟動 server,回傳 base URL。"""
        app = web.Application()
        app.router.add_post("/api/v1/auth/refresh", self.handle_refresh)
        app.router.add_post("/api/v1/auth/login", self.handle_login)
        app.router.add_get("/api/v1/devices", self.handle_devices)
        app.router.add_get("/api/v1/devices/{sn}/realtime", self.handle_realtime)
        app.router.add_get("/api/v1/devices/{sn}/stats", self.handle_stats)
        app.router.add_get("/api/v1/devices/{sn}/stat-history", self.handle_history)
        app.router.add_get("/api/v1/devices/{sn}/params", self.handle_params)
        app.router.add_put("/api/v1/devices/{sn}/params", self.handle_params)
        app.router.add_post("/api/v1/devices/{sn}/reboot", self.handle_reboot)

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
        return f"http://127.0.0.1:{self.port}"

    async def stop(self) -> None:
        """關掉 server。"""
        if self.runner:
            await self.runner.cleanup()
