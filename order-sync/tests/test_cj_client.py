"""CJ client tests with a fake HTTP session (no network)."""
import pytest

from bublu.cj import CJClient, CJError


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.text = body, status, str(body)

    def json(self):
        return self.body


def ok(data):
    return Resp({"code": 200, "result": True, "message": "Success", "data": data})


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json, headers))
        if url.endswith("/authentication/getAccessToken"):
            return ok({"accessToken": "TOK", "refreshToken": "REF",
                       "accessTokenExpiryDate": "2027-04-01T00:00:00+08:00",
                       "refreshTokenExpiryDate": "2027-04-01T00:00:00+08:00"})
        if url.endswith("/logistic/freightCalculate"):
            return ok([{"logisticName": "Slow", "logisticPrice": 9.0}, {"logisticName": "USPS US to US", "logisticPrice": 0}])
        return Resp({"code": 1600100, "result": False, "message": "Param error", "data": None})

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params, headers))
        if url.endswith("/product/query"):
            return ok({"productNameEn": "Clips", "variants": [
                {"vid": "V1", "variantSku": "CJJT252566401AZ", "variantSellPrice": 10.33}]})
        if url.endswith("/product/stock/queryBySku"):
            return ok([{"countryCode": "CN", "totalInventoryNum": 999}, {"countryCode": "US", "totalInventoryNum": 22}])
        if url.endswith("/shopping/pay/getBalance"):
            return ok({"amount": 87.5})
        return Resp({"code": 1600100, "result": False, "message": "Param error", "data": None})


def client(tmp_path):
    s = FakeSession()
    return CJClient("KEY", token_cache=str(tmp_path / "tok.json"), session=s, min_interval=0), s


def test_token_is_fetched_once_and_cached(tmp_path):
    c, s = client(tmp_path)
    c.balance()
    c.balance()
    assert sum(1 for x in s.calls if x[1].endswith("getAccessToken")) == 1
    c2, s2 = client(tmp_path)  # new process reuses cached token file
    c2.balance()
    assert not any(x[1].endswith("getAccessToken") for x in s2.calls)
    assert s.calls[-1][3]["CJ-Access-Token"] == "TOK"


def test_variant_stock_shipping(tmp_path):
    c, _ = client(tmp_path)
    v = c.variant_by_sku("CJJT252566401AZ")
    assert (v.vid, v.sell_price) == ("V1", 10.33)
    assert c.stock_by_sku("CJJT252566401AZ", "US") == 22
    assert c.cheapest_shipping([{"vid": "V1", "quantity": 1}], "US", "US")["logisticName"] == "USPS US to US"


def test_error_envelope_raises(tmp_path):
    c, _ = client(tmp_path)
    with pytest.raises(CJError):
        c.create_order({"orderNumber": "x"})
    with pytest.raises(CJError):
        c.variant_by_sku("MISSING")
