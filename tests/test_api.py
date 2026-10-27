"""Deye Cloud OpenAPI client: sign-in, errors, rate limits and control orders."""
from __future__ import annotations

import hashlib
import itertools
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.deye_cloud import build_client
from custom_components.deye_cloud.api import (
    DeyeCloudApiError,
    DeyeCloudAuthError,
    DeyeCloudClient,
    DeyeCloudRateLimitError,
)
from custom_components.deye_cloud.const import REGIONS

from .test_init import ENTRY_DATA

BASE = REGIONS["eu"]["base_url"]
TOKEN_URL = f"{BASE}/account/token"
OK = {"code": "1000000", "msg": "success", "success": True, "requestId": "r1"}
TOKEN = {**OK, "accessToken": "Bearer tok-1", "expiresIn": 5184000}


@pytest.fixture
def client(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> DeyeCloudClient:
    return build_client(hass, ENTRY_DATA)


@pytest.fixture
def signed_in(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    return aioclient_mock


def _calls(aioclient_mock: AiohttpClientMocker, path: str) -> list:
    return [call for call in aioclient_mock.mock_calls if call[1].path.endswith(path)]


def _sequence(*bodies: dict):
    """Answer each request with the next body, repeating the last one."""
    replies = itertools.chain(bodies, itertools.repeat(bodies[-1]))

    async def side_effect(method, url, data):
        return AiohttpClientMockResponse(method, url, json=next(replies))

    return side_effect


# --- sign-in -----------------------------------------------------------------


async def test_sign_in_sends_the_app_id_and_a_hashed_password(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/station/listWithDevice", json={**OK, "stationList": [{"id": 1}]})

    assert await client.async_get_stations_with_devices() == [{"id": 1}]

    (token_call,) = _calls(signed_in, "/account/token")
    assert token_call[1].query["appId"] == "app-id"
    assert token_call[2] == {
        "appSecret": "app-secret",
        "email": "user@example.com",
        "password": hashlib.sha256(b"hunter2").hexdigest(),
    }
    (list_call,) = _calls(signed_in, "/station/listWithDevice")
    # The token comes back with its scheme; it must not be doubled in the header.
    assert list_call[3]["Authorization"] == "Bearer tok-1"


async def test_token_is_reused_until_it_nears_expiry(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/station/listWithDevice", json={**OK, "stationList": []})

    await client.async_get_stations_with_devices()
    await client.async_get_stations_with_devices()

    assert len(_calls(signed_in, "/account/token")) == 1


async def test_token_without_an_expiry_is_kept(
    client: DeyeCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json={**OK, "accessToken": "tok-1"})
    aioclient_mock.post(f"{BASE}/station/listWithDevice", json={**OK, "stationList": []})

    await client.async_get_stations_with_devices()
    await client.async_get_stations_with_devices()

    assert len(_calls(aioclient_mock, "/account/token")) == 1


async def test_token_within_a_day_of_expiry_is_renewed(
    client: DeyeCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json={**TOKEN, "expiresIn": 86400})
    aioclient_mock.post(f"{BASE}/station/listWithDevice", json={**OK, "stationList": []})

    await client.async_get_stations_with_devices()
    await client.async_get_stations_with_devices()

    assert len(_calls(aioclient_mock, "/account/token")) == 2


async def test_valid_credentials_pass_the_connection_test(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    assert await client.async_test_connection() is True


async def test_rejected_credentials_are_an_auth_error(
    client: DeyeCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json={"code": "2101019", "msg": "password error"})

    with pytest.raises(DeyeCloudAuthError, match="password error"):
        await client.async_obtain_token()
    assert await client.async_test_connection() is False


async def test_sign_in_without_a_token_is_an_auth_error(
    client: DeyeCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json=OK)

    with pytest.raises(DeyeCloudAuthError, match="No access token"):
        await client.async_obtain_token()


async def test_sign_in_over_quota_is_a_rate_limit(
    client: DeyeCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(TOKEN_URL, json={"code": "2101030", "msg": "Daily quota exceeded"})

    with pytest.raises(DeyeCloudRateLimitError):
        await client.async_obtain_token()


async def test_sign_in_http_429_carries_retry_after(
    client: DeyeCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        TOKEN_URL, status=HTTPStatus.TOO_MANY_REQUESTS, headers={"Retry-After": "60"}
    )

    with pytest.raises(DeyeCloudRateLimitError) as err:
        await client.async_obtain_token()
    assert err.value.retry_after == 60


@pytest.mark.parametrize(
    "failure,message",
    [
        ({"status": HTTPStatus.BAD_GATEWAY}, "Connection error"),
        ({"exc": aiohttp.ClientConnectionError("refused")}, "Connection error"),
        ({"exc": TimeoutError()}, "timed out"),
    ],
)
async def test_sign_in_transport_failures_are_api_errors(
    client: DeyeCloudClient, aioclient_mock: AiohttpClientMocker, failure, message
) -> None:
    aioclient_mock.post(TOKEN_URL, **failure)

    with pytest.raises(DeyeCloudApiError, match=message) as err:
        await client.async_obtain_token()
    assert type(err.value) is DeyeCloudApiError
    assert await client.async_test_connection() is False


# --- request errors ----------------------------------------------------------


async def test_http_429_is_a_rate_limit_with_retry_after(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(
        f"{BASE}/station/latest",
        status=HTTPStatus.TOO_MANY_REQUESTS,
        headers={"Retry-After": "120"},
    )

    with pytest.raises(DeyeCloudRateLimitError) as err:
        await client.async_get_station_latest("1")
    assert err.value.retry_after == 120


async def test_http_429_without_retry_after_still_rate_limits(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/station/latest", status=HTTPStatus.TOO_MANY_REQUESTS)

    with pytest.raises(DeyeCloudRateLimitError) as err:
        await client.async_get_station_latest("1")
    assert err.value.retry_after is None


@pytest.mark.parametrize(
    "failure,message",
    [
        ({"status": HTTPStatus.INTERNAL_SERVER_ERROR}, "Connection error"),
        ({"exc": aiohttp.ClientConnectionError("reset")}, "Connection error"),
        ({"exc": TimeoutError()}, "timed out"),
    ],
)
async def test_transport_failures_are_api_errors(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker, failure, message
) -> None:
    signed_in.post(f"{BASE}/station/latest", **failure)

    with pytest.raises(DeyeCloudApiError, match=message) as err:
        await client.async_get_station_latest("1")
    assert type(err.value) is DeyeCloudApiError


@pytest.mark.parametrize("code", [1001, "2101017"])
async def test_revoked_token_is_an_auth_error(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker, code
) -> None:
    signed_in.post(f"{BASE}/station/latest", json={"code": code, "msg": "token invalid"})

    with pytest.raises(DeyeCloudAuthError, match="token invalid"):
        await client.async_get_station_latest("1")


async def test_rate_limit_message_in_the_body_is_a_rate_limit(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(
        f"{BASE}/station/latest", json={"code": "2101040", "msg": "Request too frequent"}
    )

    with pytest.raises(DeyeCloudRateLimitError, match="code 2101040") as err:
        await client.async_get_station_latest("1")
    assert err.value.retry_after is None


async def test_other_error_codes_keep_the_cloud_message(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/station/latest", json={"code": "2104001", "msg": "device offline"})

    with pytest.raises(DeyeCloudApiError, match=r"device offline \(code 2104001\)") as err:
        await client.async_get_station_latest("1")
    assert type(err.value) is DeyeCloudApiError


# --- reads -------------------------------------------------------------------


async def test_station_latest_leaves_out_the_envelope(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/station/latest", json={**OK, "generationPower": 1200.0})

    assert await client.async_get_station_latest("1") == {"generationPower": 1200.0}
    assert _calls(signed_in, "/station/latest")[0][2] == {"stationId": "1"}


async def test_missing_station_list_reads_as_empty(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/station/listWithDevice", json=OK)

    assert await client.async_get_stations_with_devices() == []


async def test_measure_points_are_read_for_the_device_type(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/device/measurePoints", json={**OK, "measurePoints": ["SOC"]})

    assert await client.async_get_measure_points("SN1", "INVERTER") == ["SOC"]
    assert _calls(signed_in, "/device/measurePoints")[0][2] == {
        "deviceSn": "SN1",
        "deviceType": "INVERTER",
    }


async def test_null_measure_points_read_as_empty(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/device/measurePoints", json={**OK, "measurePoints": None})

    assert await client.async_get_measure_points("SN1", "INVERTER") == []


async def test_device_latest_is_split_into_values_and_units(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(
        f"{BASE}/device/latest",
        json={
            **OK,
            "deviceDataList": [
                {
                    "deviceSn": "SN1",
                    "dataList": [
                        {"key": "SOC", "value": "80", "unit": "%"},
                        {"key": "RunStatus", "value": "Normal", "unit": ""},
                        {"value": "orphan"},
                    ],
                },
                {"dataList": [{"key": "SOC", "value": "10"}]},
            ],
        },
    )

    assert await client.async_get_device_latest(["SN1"]) == {
        "SN1": {"data": {"SOC": "80", "RunStatus": "Normal"}, "units": {"SOC": "%"}}
    }
    assert _calls(signed_in, "/device/latest")[0][2] == {"deviceList": ["SN1"]}


async def test_device_latest_takes_at_most_ten_serials(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    with pytest.raises(ValueError):
        await client.async_get_device_latest([f"SN{n}" for n in range(11)])
    assert signed_in.call_count == 0


@pytest.mark.parametrize(
    "method,path",
    [
        ("async_get_system_config", "/config/system"),
        ("async_get_battery_config", "/config/battery"),
        ("async_get_tou", "/config/tou"),
    ],
)
async def test_config_reads_return_the_data_payload(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker, method, path
) -> None:
    signed_in.post(f"{BASE}{path}", json={**OK, "data": {"energyPattern": "LOAD_FIRST"}})

    assert await getattr(client, method)("SN1") == {"energyPattern": "LOAD_FIRST"}
    assert _calls(signed_in, path)[0][2] == {"deviceSn": "SN1"}


# --- dynamic-control read ----------------------------------------------------

READ_URL = f"{BASE}/strategy/dynamicControl/read"
RESULT_URL = f"{BASE}/strategy/dynamicControl/readResult"
SENDING = {"code": "2104013", "msg": "Order is sending", "success": False, "requestId": "r2"}


@pytest.fixture
def no_wait():
    with (
        patch("custom_components.deye_cloud.api.DYNAMIC_READ_DELAY", 0),
        patch("custom_components.deye_cloud.api.ORDER_POLL_INTERVAL", 0),
    ):
        yield


async def test_dynamic_read_waits_for_the_inverter_to_answer(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker, no_wait
) -> None:
    signed_in.post(READ_URL, json={**OK, "msg": "order sent successfully", "orderId": 7})
    signed_in.post(
        RESULT_URL,
        side_effect=_sequence(SENDING, SENDING, {**OK, "gridChargeAmpere": 30}),
    )

    assert await client.async_get_dynamic_config("SN1") == {"gridChargeAmpere": 30}
    assert _calls(signed_in, "/dynamicControl/read")[0][2] == {"deviceSn": "SN1"}
    assert [c[2] for c in _calls(signed_in, "/readResult")] == [{"orderId": 7}] * 3


async def test_dynamic_read_without_an_order_id_raises(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(READ_URL, json=OK)

    with pytest.raises(DeyeCloudApiError, match="not accepted"):
        await client.async_get_dynamic_config("SN1")
    assert not _calls(signed_in, "/readResult")


async def test_dynamic_read_unanswered_after_the_timeout_raises(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker, no_wait
) -> None:
    signed_in.post(READ_URL, json={**OK, "orderId": 7})
    signed_in.post(RESULT_URL, json=SENDING)
    clock = MagicMock()
    clock.time.side_effect = itertools.count(1_000_000, 5)

    with (
        patch("custom_components.deye_cloud.api.time", clock),
        pytest.raises(DeyeCloudApiError, match="timed out"),
    ):
        await client.async_get_dynamic_config("SN1")


# --- control orders ----------------------------------------------------------


@pytest.mark.parametrize(
    "method,args,path,body",
    [
        (
            "async_set_work_mode",
            ("SN1", "ZERO_EXPORT_TO_LOAD"),
            "/order/sys/workMode/update",
            {"deviceSn": "SN1", "workMode": "ZERO_EXPORT_TO_LOAD"},
        ),
        (
            "async_set_energy_pattern",
            ("SN1", "BATTERY_FIRST"),
            "/order/sys/energyPattern/update",
            {"deviceSn": "SN1", "energyPattern": "BATTERY_FIRST"},
        ),
        (
            "async_set_solar_sell",
            ("SN1", True),
            "/order/sys/solarSell/control",
            {"deviceSn": "SN1", "action": "on"},
        ),
        (
            "async_set_solar_sell",
            ("SN1", False),
            "/order/sys/solarSell/control",
            {"deviceSn": "SN1", "action": "off"},
        ),
        (
            "async_set_battery_param",
            ("SN1", "MAX_CHARGE_CURRENT", 40),
            "/order/battery/parameter/update",
            {"deviceSn": "SN1", "paramterType": "MAX_CHARGE_CURRENT", "value": 40},
        ),
        (
            "async_set_battery_param",
            ("SN1", "GRID_CHARGE_AMPERE", 30),
            "/order/battery/parameter/update",
            {"deviceSn": "SN1", "paramterType": "GRID_CHARGE_AMPERE", "value": 30},
        ),
        (
            "async_set_peak_shaving",
            ("SN1", True, 3000),
            "/order/gridPeakShaving/control",
            {"deviceSn": "SN1", "action": "on", "power": 3000},
        ),
        (
            "async_set_peak_shaving",
            ("SN1", False),
            "/order/gridPeakShaving/control",
            {"deviceSn": "SN1", "action": "off"},
        ),
        (
            "async_set_power_param",
            ("SN1", "MAX_SELL_POWER", 5000),
            "/order/sys/power/update",
            {"deviceSn": "SN1", "powerType": "MAX_SELL_POWER", "value": 5000},
        ),
        (
            "async_set_tou",
            ("SN1", [{"time": "0100", "soc": 90}, {"time": "5:00", "soc": 30}]),
            "/order/sys/tou/update",
            {
                "deviceSn": "SN1",
                "timeUseSettingItems": [
                    {"time": "01:00", "soc": 90},
                    {"time": "05:00", "soc": 30},
                ],
            },
        ),
        (
            "async_set_tou_switch",
            ("SN1", True),
            "/order/sys/tou/switch",
            {"deviceSn": "SN1", "action": "on"},
        ),
        (
            "async_set_tou_switch",
            ("SN1", False, ["MONDAY", "FRIDAY"]),
            "/order/sys/tou/switch",
            {"deviceSn": "SN1", "action": "off", "days": ["MONDAY", "FRIDAY"]},
        ),
    ],
)
async def test_control_is_sent_and_confirmed(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker, method, args, path, body
) -> None:
    signed_in.post(f"{BASE}{path}", json={**OK, "orderId": 42})
    signed_in.get(f"{BASE}/order/42", json={**OK, "status": 666})

    result = await getattr(client, method)(*args)

    assert result["status"] == 666
    assert _calls(signed_in, path)[0][2] == body
    assert len(_calls(signed_in, "/order/42")) == 1


async def test_control_without_an_order_id_is_not_polled(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/order/sys/solarSell/control", json=OK)

    await client.async_set_solar_sell("SN1", True)

    assert [call[0].upper() for call in signed_in.mock_calls] == ["POST", "POST"]


async def test_pending_order_is_polled_until_it_succeeds(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/order/sys/solarSell/control", json={**OK, "orderId": 42})
    signed_in.get(
        f"{BASE}/order/42",
        side_effect=_sequence({**OK, "status": 0}, {**OK, "status": 100}, {**OK, "status": "666"}),
    )

    with patch("custom_components.deye_cloud.api.ORDER_POLL_INTERVAL", 0):
        await client.async_set_solar_sell("SN1", True)

    assert len(_calls(signed_in, "/order/42")) == 3


@pytest.mark.parametrize("status", [2, None])
async def test_failed_order_raises(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker, status
) -> None:
    signed_in.post(f"{BASE}/order/sys/solarSell/control", json={**OK, "orderId": 42})
    signed_in.get(f"{BASE}/order/42", json={**OK, "status": status})

    with pytest.raises(DeyeCloudApiError, match=f"failed with status {status}"):
        await client.async_set_solar_sell("SN1", True)


async def test_order_still_pending_after_the_timeout_raises(
    client: DeyeCloudClient, signed_in: AiohttpClientMocker
) -> None:
    signed_in.post(f"{BASE}/order/sys/solarSell/control", json={**OK, "orderId": 42})
    signed_in.get(f"{BASE}/order/42", json={**OK, "status": 100})
    clock = MagicMock()
    clock.time.side_effect = itertools.count(1_000_000, 5)

    with (
        patch("custom_components.deye_cloud.api.time", clock),
        patch("custom_components.deye_cloud.api.ORDER_POLL_INTERVAL", 0),
        pytest.raises(DeyeCloudApiError, match="timed out"),
    ):
        await client.async_set_solar_sell("SN1", True)

    assert _calls(signed_in, "/order/42")


# --- sessions ----------------------------------------------------------------


async def test_client_without_a_session_closes_the_one_it_opened() -> None:
    client = DeyeCloudClient(BASE, "app-id", "app-secret", "user@example.com", "hunter2")
    session = await client._get_session()

    await client.async_close()

    assert session.closed


async def test_shared_session_is_left_open(hass: HomeAssistant, client: DeyeCloudClient) -> None:
    await client.async_close()

    assert not async_get_clientsession(hass).closed
