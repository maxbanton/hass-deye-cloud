"""Client for the Deye Cloud OpenAPI."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_TIMEOUT = 30

# Response codes the API uses to signal success.
_SUCCESS_CODES = {0, 1000000, 1106000, "0", "1000000", "1106000"}
_AUTH_ERROR_CODES = {1001, 1002, 1003, 2101017, "1001", "1002", "1003", "2101017"}

# Deye has announced usage quotas and rate limits but not yet published the
# error codes they will be reported with, so body-level detection is by message
# text; HTTP 429 is handled directly.
_RATE_LIMIT_HINTS = (
    "rate limit",
    "ratelimit",
    "too many request",
    "too frequent",
    "request too fast",
    "quota",
    "call limit",
    "request limit",
    "api limit",
)


def _retry_after(headers: Any) -> float | None:
    """Seconds from a Retry-After header, if it carries a usable value."""
    try:
        value = headers.get("Retry-After")
    except AttributeError:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_rate_limit(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in _RATE_LIMIT_HINTS)

# Control ("order") endpoints are asynchronous: they return an orderId and the
# real outcome must be read from GET /order/{orderId}.
ORDER_STATUS_SUCCESS = 666
ORDER_STATUS_PENDING = (0, 100)
ORDER_POLL_INTERVAL = 2
ORDER_POLL_TIMEOUT = 30


def _normalize_tou_time(value: Any) -> str:
    """Return a TOU slot time as 'HH:mm' (the update endpoint's required format).

    /config/tou returns 'HHMM' (e.g. '0100'); accept that and 'H:MM'/'HH:mm'.
    """
    s = str(value or "").strip()
    if ":" in s:
        hh, _, mm = s.partition(":")
        return f"{int(hh):02d}:{int(mm or 0):02d}"
    digits = s.zfill(4)
    return f"{digits[:2]}:{digits[2:4]}"


class DeyeCloudApiError(Exception):
    """Base exception for Deye Cloud API errors."""


class DeyeCloudAuthError(DeyeCloudApiError):
    """Authentication error."""


class DeyeCloudRateLimitError(DeyeCloudApiError):
    """The API rejected the call for exceeding a quota or rate limit."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class DeyeCloudClient:
    """Thin async client around the Deye Cloud OpenAPI."""

    def __init__(
        self,
        base_url: str,
        app_id: str,
        app_secret: str,
        email: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._app_id = app_id
        self._app_secret = app_secret
        self._email = email
        self._password_hash = hashlib.sha256(password.encode()).hexdigest().lower()
        self._session = session
        self._own_session = session is None
        self._token: str | None = None
        self._token_expiry = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        require_auth: bool = True,
    ) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        payload = data or {}
        headers = {"Content-Type": "application/json"}

        if require_auth:
            if not self._token or time.time() >= self._token_expiry:
                await self.async_obtain_token()
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            async with asyncio.timeout(API_TIMEOUT):
                if method.upper() == "GET":
                    ctx = session.get(url, params=payload, headers=headers)
                else:
                    ctx = session.post(url, json=payload, headers=headers)
                async with ctx as response:
                    response.raise_for_status()
                    result = await response.json()
        except aiohttp.ClientResponseError as err:
            if err.status == 429:
                raise DeyeCloudRateLimitError(
                    f"HTTP 429 for {endpoint}", _retry_after(err.headers)
                ) from err
            raise DeyeCloudApiError(f"Connection error: {err}") from err
        except aiohttp.ClientError as err:
            raise DeyeCloudApiError(f"Connection error: {err}") from err
        except TimeoutError as err:
            raise DeyeCloudApiError("Request timed out") from err

        code = result.get("code")
        if code is not None and code not in _SUCCESS_CODES:
            msg = result.get("msg", "Unknown error")
            if code in _AUTH_ERROR_CODES:
                raise DeyeCloudAuthError(msg)
            if _is_rate_limit(str(msg)):
                raise DeyeCloudRateLimitError(f"{msg} (code {code})")
            raise DeyeCloudApiError(f"{msg} (code {code})")

        inner = result.get("data")
        return inner if inner is not None else result

    async def async_obtain_token(self) -> str:
        """Obtain (or refresh) the bearer token.

        appId is a query parameter; credentials go in the body and the password
        must be SHA-256 hex encoded.
        """
        session = await self._get_session()
        url = f"{self.base_url}/account/token?appId={self._app_id}"
        body = {
            "appSecret": self._app_secret,
            "email": self._email,
            "password": self._password_hash,
        }
        try:
            async with asyncio.timeout(API_TIMEOUT):
                async with session.post(
                    url, json=body, headers={"Content-Type": "application/json"}
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
        except aiohttp.ClientResponseError as err:
            if err.status == 429:
                raise DeyeCloudRateLimitError(
                    "HTTP 429 while obtaining a token", _retry_after(err.headers)
                ) from err
            raise DeyeCloudApiError(f"Connection error: {err}") from err
        except aiohttp.ClientError as err:
            raise DeyeCloudApiError(f"Connection error: {err}") from err
        except TimeoutError as err:
            raise DeyeCloudApiError("Request timed out") from err

        if result.get("code") not in _SUCCESS_CODES:
            msg = str(result.get("msg", "Authentication failed"))
            if _is_rate_limit(msg):
                raise DeyeCloudRateLimitError(msg)
            raise DeyeCloudAuthError(msg)

        token = result.get("accessToken")
        if not token:
            raise DeyeCloudAuthError("No access token in response")
        # Strip any leading scheme so the header is built consistently.
        self._token = token.split(" ", 1)[-1]

        expires_in = result.get("expiresIn") or 60 * 24 * 60 * 60
        self._token_expiry = time.time() + float(expires_in) - 86400
        return self._token

    async def async_test_connection(self) -> bool:
        """Return True if credentials authenticate."""
        try:
            await self.async_obtain_token()
            return True
        except DeyeCloudApiError:
            return False

    async def async_get_stations_with_devices(self) -> list[dict[str, Any]]:
        result = await self._request("POST", "/station/listWithDevice")
        return result.get("stationList", [])

    async def async_get_station_latest(self, station_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/station/latest", data={"stationId": station_id}
        )

    async def async_get_device_latest(
        self, device_sns: list[str]
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Return {sn: {"data": {key: value}, "units": {key: unit}}} (<=10 SNs)."""
        if len(device_sns) > 10:
            raise ValueError("Maximum 10 devices per request")
        result = await self._request(
            "POST", "/device/latest", data={"deviceList": device_sns}
        )
        parsed: dict[str, dict[str, dict[str, Any]]] = {}
        for device in result.get("deviceDataList", []):
            sn = device.get("deviceSn")
            if not sn:
                continue
            values: dict[str, Any] = {}
            units: dict[str, str] = {}
            for item in device.get("dataList", []):
                key = item.get("key")
                if not key:
                    continue
                values[key] = item.get("value")
                if item.get("unit"):
                    units[key] = item["unit"]
            parsed[sn] = {"data": values, "units": units}
        return parsed

    async def async_get_system_config(self, device_sn: str) -> dict[str, Any]:
        return await self._request("POST", "/config/system", data={"deviceSn": device_sn})

    async def async_get_battery_config(self, device_sn: str) -> dict[str, Any]:
        return await self._request("POST", "/config/battery", data={"deviceSn": device_sn})

    async def async_get_tou(self, device_sn: str) -> dict[str, Any]:
        return await self._request("POST", "/config/tou", data={"deviceSn": device_sn})

    # --- control (asynchronous order) endpoints ------------------------------

    async def _confirm_order(self, result: Any) -> Any:
        """Poll a control order until success (666), else raise."""
        order_id = result.get("orderId") if isinstance(result, dict) else None
        if not order_id:
            return result
        deadline = time.time() + ORDER_POLL_TIMEOUT
        while time.time() < deadline:
            status_result = await self._request("GET", f"/order/{order_id}")
            status = status_result.get("status") if isinstance(status_result, dict) else None
            with contextlib.suppress(TypeError, ValueError):
                status = int(status)
            if status == ORDER_STATUS_SUCCESS:
                return status_result
            if status not in ORDER_STATUS_PENDING:
                raise DeyeCloudApiError(
                    f"Control order {order_id} failed with status {status}"
                )
            await asyncio.sleep(ORDER_POLL_INTERVAL)
        raise DeyeCloudApiError(f"Control order {order_id} timed out")

    async def async_set_work_mode(self, device_sn: str, work_mode: str) -> Any:
        result = await self._request(
            "POST", "/order/sys/workMode/update",
            data={"deviceSn": device_sn, "workMode": work_mode},
        )
        return await self._confirm_order(result)

    async def async_set_energy_pattern(self, device_sn: str, energy_pattern: str) -> Any:
        result = await self._request(
            "POST", "/order/sys/energyPattern/update",
            data={"deviceSn": device_sn, "energyPattern": energy_pattern},
        )
        return await self._confirm_order(result)

    async def async_set_solar_sell(self, device_sn: str, enabled: bool) -> Any:
        result = await self._request(
            "POST", "/order/sys/solarSell/control",
            data={"deviceSn": device_sn, "action": "on" if enabled else "off"},
        )
        return await self._confirm_order(result)

    async def async_set_battery_param(
        self, device_sn: str, param_type: str, value: int
    ) -> Any:
        """Set a battery set-point. Note the API field is 'paramterType' (sic)."""
        result = await self._request(
            "POST", "/order/battery/parameter/update",
            data={"deviceSn": device_sn, "paramterType": param_type, "value": value},
        )
        return await self._confirm_order(result)

    async def async_set_power_param(
        self, device_sn: str, power_type: str, value: int
    ) -> Any:
        """Set a system power set-point (e.g. MAX_SELL_POWER)."""
        result = await self._request(
            "POST", "/order/sys/power/update",
            data={"deviceSn": device_sn, "powerType": power_type, "value": value},
        )
        return await self._confirm_order(result)

    async def async_set_tou(self, device_sn: str, items: list[dict[str, Any]]) -> Any:
        """Set the time-of-use schedule (all 6 slots, in order).

        The update endpoint requires ``time`` as ``HH:mm``, but /config/tou
        returns it as ``HHMM`` (e.g. ``0100``); normalize so round-tripped items
        are accepted.
        """
        normalized = [dict(item) for item in items]
        for item in normalized:
            item["time"] = _normalize_tou_time(item.get("time"))
        result = await self._request(
            "POST", "/order/sys/tou/update",
            data={"deviceSn": device_sn, "timeUseSettingItems": normalized},
        )
        return await self._confirm_order(result)

    async def async_set_tou_switch(
        self, device_sn: str, enabled: bool, days: list[str] | None = None
    ) -> Any:
        """Enable or disable the time-of-use schedule, optionally per weekday."""
        data: dict[str, Any] = {
            "deviceSn": device_sn,
            "action": "on" if enabled else "off",
        }
        if days:
            data["days"] = days
        result = await self._request("POST", "/order/sys/tou/switch", data=data)
        return await self._confirm_order(result)

    async def async_close(self) -> None:
        if self._own_session and self._session:
            await self._session.close()
            self._session = None
