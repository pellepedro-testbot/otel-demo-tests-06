import json

import pytest

QUOTE_PARAMS = {
    "itemList": json.dumps([{"productId": "LS4PSXUNUM", "quantity": 1}]),
    "currencyCode": "USD",
    "address": json.dumps({"streetAddress": "1600 Amphitheatre Parkway", "zipCode": "94043", "city": "Mountain View", "state": "CA", "country": "United States"}),
}


@pytest.mark.parametrize("params", [QUOTE_PARAMS, None], ids=["with_quote_params", "without_params"])
def test_post_shipping_answers_405_with_allow_get_and_empty_body(api, params):
    resp = api.request("POST", "/api/shipping", params=params, timeout=5)
    assert resp.status_code == 405
    assert resp.headers["Allow"] == "GET"
    assert resp.content == b""
    assert resp.elapsed.total_seconds() < 5


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_other_unhandled_methods_on_shipping_answer_like_post(api, method):
    post = api.request("POST", "/api/shipping", params=QUOTE_PARAMS, timeout=5)
    resp = api.request(method, "/api/shipping", params=QUOTE_PARAMS, timeout=5)
    assert resp.status_code == 405
    assert resp.headers["Allow"] == "GET"
    assert resp.content == b""
    assert resp.elapsed.total_seconds() < 5
    assert (resp.status_code, resp.headers.get("Allow")) == (post.status_code, post.headers.get("Allow"))
