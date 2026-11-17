import json
import secrets
import time

import pytest

ADDRESS = json.dumps({
    "streetAddress": "1600 Amphitheatre Parkway",
    "city": "Mountain View",
    "state": "CA",
    "country": "United States",
    "zipCode": "94043",
})
THREE_ITEMS = '[{"productId":"OLJCESPC7Z","quantity":3}]'
VALID_PARAMS = {"itemList": THREE_ITEMS, "currencyCode": "USD", "address": ADDRESS}
PROMPT_SECONDS = 10


def amount(cost):
    return cost["units"] + cost["nanos"] / 1e9


def assert_refused(resp, elapsed, param):
    assert resp.status_code == 400, resp.text
    assert resp.headers["Content-Type"].startswith("application/json")
    body = resp.json()
    assert isinstance(body, dict)
    assert isinstance(body.get("error"), str) and body["error"]
    assert param in body["error"]
    assert elapsed < PROMPT_SECONDS


def get_shipping(api, params, **kwargs):
    start = time.monotonic()
    resp = api.get("/api/shipping", params=params, **kwargs)
    return resp, time.monotonic() - start


def test_missing_itemlist_is_refused(api):
    resp, elapsed = get_shipping(api, {"currencyCode": "USD", "address": ADDRESS})
    assert_refused(resp, elapsed, "itemList")


def test_missing_address_is_refused(api):
    resp, elapsed = get_shipping(api, {"currencyCode": "USD", "itemList": THREE_ITEMS})
    assert_refused(resp, elapsed, "address")


def test_empty_itemlist_array_is_refused(api):
    resp, elapsed = get_shipping(api, {"itemList": "[]", "currencyCode": "USD", "address": ADDRESS})
    assert_refused(resp, elapsed, "itemList")


def test_itemlist_not_json_is_refused(api):
    resp, elapsed = get_shipping(api, {"itemList": "not-json", "currencyCode": "USD", "address": ADDRESS})
    assert_refused(resp, elapsed, "itemList")


def test_itemlist_not_json_answers_json_error_object(api):
    resp = api.get("/api/shipping", params={"itemList": "not-json", "currencyCode": "USD", "address": ADDRESS})
    assert resp.status_code == 400
    assert resp.headers["Content-Type"].startswith("application/json")
    body = resp.json()
    assert list(body.keys()) == ["error"]
    assert isinstance(body["error"], str) and body["error"]
    assert "itemList" in body["error"]


def test_address_array_is_refused(api):
    resp, elapsed = get_shipping(api, {"itemList": THREE_ITEMS, "currencyCode": "USD", "address": "[]"})
    assert_refused(resp, elapsed, "address")


@pytest.mark.parametrize("item_list", ['{"productId":"OLJCESPC7Z","quantity":1}', '"x"', "3", "null"])
def test_itemlist_json_not_array_is_refused(api, item_list):
    resp, elapsed = get_shipping(api, {"itemList": item_list, "currencyCode": "USD", "address": ADDRESS})
    assert_refused(resp, elapsed, "itemList")


@pytest.mark.parametrize("address", ["not-json", "null", '"Mountain View"', "42"])
def test_address_not_json_object_is_refused(api, address):
    resp, elapsed = get_shipping(api, {"itemList": THREE_ITEMS, "currencyCode": "USD", "address": address})
    assert_refused(resp, elapsed, "address")


def test_empty_itemlist_value_is_refused(api):
    resp, elapsed = get_shipping(api, {"itemList": "", "currencyCode": "USD", "address": ADDRESS})
    assert_refused(resp, elapsed, "itemList")


def test_itemlist_given_twice_is_refused(api):
    params = [
        ("itemList", THREE_ITEMS),
        ("itemList", THREE_ITEMS),
        ("currencyCode", "USD"),
        ("address", ADDRESS),
    ]
    resp, elapsed = get_shipping(api, params)
    assert_refused(resp, elapsed, "itemList")


def test_both_itemlist_and_address_missing_is_refused(api):
    resp = api.get("/api/shipping", params={"currencyCode": "USD"})
    assert resp.status_code == 400, resp.text
    error = resp.json()["error"]
    assert isinstance(error, str)
    assert "itemList" in error or "address" in error


def _trace_services(api, trace_id):
    resp = api.get(f"/jaeger/ui/api/traces/{trace_id}", timeout=10)
    if resp.status_code != 200:
        return None
    data = resp.json().get("data") or []
    if not data:
        return None
    return {p["serviceName"] for p in data[0]["processes"].values()}


def _traceparent():
    trace_id = secrets.token_hex(16)
    return trace_id, {"traceparent": f"00-{trace_id}-{secrets.token_hex(8)}-01"}


def test_refused_request_calls_neither_shipping_nor_currency(api):
    refused_trace, refused_headers = _traceparent()
    resp = api.get(
        "/api/shipping",
        params={"itemList": "not-json", "currencyCode": "USD", "address": ADDRESS},
        headers=refused_headers,
    )
    assert resp.status_code == 400

    control_trace, control_headers = _traceparent()
    control = api.get("/api/shipping", params=VALID_PARAMS, headers=control_headers)
    assert control.status_code == 200

    deadline = time.monotonic() + 60
    control_services = None
    while time.monotonic() < deadline:
        control_services = _trace_services(api, control_trace)
        if control_services and {"shipping", "currency"} <= control_services:
            break
        time.sleep(3)
    else:
        pytest.skip(f"Jaeger did not show the control trace within 60s (saw {control_services})")

    refused_services = None
    while time.monotonic() < deadline + 15:
        refused_services = _trace_services(api, refused_trace)
        if refused_services and "frontend" in refused_services:
            break
        time.sleep(3)
    assert refused_services and "frontend" in refused_services, refused_services
    assert not refused_services & {"shipping", "quote", "currency"}, refused_services


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("with_params", [True, False], ids=["with-query", "no-query"])
def test_other_method_is_refused_with_405(api, method, with_params):
    params = VALID_PARAMS if with_params else None
    resp = api.request(method, "/api/shipping", params=params, timeout=10)
    assert resp.status_code == 405
    assert resp.headers["Allow"] == "GET"
    assert resp.content == b""


def test_post_without_query_or_body_answers_405_at_once(api):
    start = time.monotonic()
    resp = api.request("POST", "/api/shipping", timeout=5)
    elapsed = time.monotonic() - start
    assert resp.status_code == 405
    assert elapsed < 5
    assert resp.headers["Allow"] == "GET"
    assert resp.content == b""


def test_three_items_in_usd_cost_26_97(api):
    resp = api.get("/api/shipping", params=VALID_PARAMS)
    assert resp.status_code == 200, resp.text
    cost = resp.json()
    assert cost["currencyCode"] == "USD"
    assert abs(amount(cost) - 26.97) < 1e-6


def test_three_items_of_quantity_one_in_usd_cost_26_97(api):
    item_list = json.dumps([
        {"productId": "OLJCESPC7Z", "quantity": 1},
        {"productId": "66VCHSJNUP", "quantity": 1},
        {"productId": "9SIQT8TOJO", "quantity": 1},
    ])
    resp = api.get("/api/shipping", params={"itemList": item_list, "currencyCode": "USD", "address": ADDRESS})
    assert resp.status_code == 200, resp.text
    cost = resp.json()
    assert cost["currencyCode"] == "USD"
    assert abs(amount(cost) - 26.97) < 1e-6


def test_quote_in_eur_is_converted(api):
    resp = api.get("/api/shipping", params={**VALID_PARAMS, "currencyCode": "EUR"})
    assert resp.status_code == 200, resp.text
    cost = resp.json()
    assert cost["currencyCode"] == "EUR"
    assert isinstance(cost["units"], int) and isinstance(cost["nanos"], int)
    assert amount(cost) > 0
    assert abs(amount(cost) - 26.97) > 0.01


def test_one_item_in_usd_costs_8_99(api):
    resp = api.get("/api/shipping", params={**VALID_PARAMS, "itemList": '[{"productId":"OLJCESPC7Z","quantity":1}]'})
    assert resp.status_code == 200, resp.text
    cost = resp.json()
    assert cost["currencyCode"] == "USD"
    assert abs(amount(cost) - 8.99) < 1e-6


def test_quote_without_currency_code_is_in_usd(api):
    resp = api.get("/api/shipping", params={"itemList": THREE_ITEMS, "address": ADDRESS})
    assert resp.status_code == 200, resp.text
    cost = resp.json()
    assert cost["currencyCode"] == "USD"
    assert abs(amount(cost) - 26.97) < 1e-6


CART_PAGE_ITEMS = json.dumps([{"productId": "OLJCESPC7Z", "quantity": 2}, {"productId": "66VCHSJNUP", "quantity": 1}])


def test_cart_page_request_gets_a_usd_quote(api):
    resp = api.get("/api/shipping", params={"itemList": CART_PAGE_ITEMS, "currencyCode": "USD", "address": ADDRESS})
    assert resp.status_code == 200, resp.text
    cost = resp.json()
    assert cost["currencyCode"] == "USD"
    assert abs(amount(cost) - 26.97) < 1e-6


def test_cart_page_request_gets_a_cad_quote(api):
    resp = api.get("/api/shipping", params={"itemList": CART_PAGE_ITEMS, "currencyCode": "CAD", "address": ADDRESS})
    assert resp.status_code == 200, resp.text
    cost = resp.json()
    assert cost["currencyCode"] == "CAD"
    assert amount(cost) > 0
