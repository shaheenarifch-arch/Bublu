"""Minimal CJdropshipping API v2 client (https://developers.cjdropshipping.com)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

BASE = "https://developers.cjdropshipping.com/api2.0/v1"


class CJError(RuntimeError):
    def __init__(self, message: str, code: Any = None, payload: Any = None):
        super().__init__(f"CJ API error {code}: {message}")
        self.code = code
        self.payload = payload


@dataclass
class Variant:
    vid: str
    sku: str
    sell_price: float
    name: str = ""


class CJClient:
    """Handles token caching, the 1 request/second limit and CJ's {code,result,data} envelope."""

    def __init__(self, api_key: str, token_cache: str = ".cj_token.json", session: requests.Session | None = None,
                 min_interval: float = 1.1):
        if not api_key:
            raise ValueError("CJ_API_KEY is not set")
        self.api_key = api_key
        self.token_cache = Path(token_cache)
        self.http = session or requests.Session()
        self.min_interval = min_interval
        self._last_call = 0.0
        self._token: str | None = None

    # ---------- low level ----------
    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @staticmethod
    def _unwrap(resp: requests.Response) -> Any:
        try:
            body = resp.json()
        except ValueError:
            raise CJError(f"non-JSON response (HTTP {resp.status_code})", resp.status_code, resp.text)
        if not body.get("result") or body.get("code") not in (200, "200"):
            raise CJError(body.get("message", "unknown error"), body.get("code"), body)
        return body.get("data")

    def _post_raw(self, path: str, payload: dict, token: bool = True) -> Any:
        self._throttle()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["CJ-Access-Token"] = self.token()
        return self._unwrap(self.http.post(f"{BASE}{path}", json=payload, headers=headers, timeout=30))

    def _get(self, path: str, params: dict | None = None) -> Any:
        self._throttle()
        headers = {"CJ-Access-Token": self.token()}
        return self._unwrap(self.http.get(f"{BASE}{path}", params=params or {}, headers=headers, timeout=30))

    def _patch(self, path: str, payload: dict) -> Any:
        self._throttle()
        headers = {"Content-Type": "application/json", "CJ-Access-Token": self.token()}
        return self._unwrap(self.http.patch(f"{BASE}{path}", json=payload, headers=headers, timeout=30))

    # ---------- auth ----------
    def token(self) -> str:
        if self._token:
            return self._token
        cached = self._load_cache()
        if cached and cached.get("expires_at", 0) > time.time() + 86400:
            self._token = cached["accessToken"]
            return self._token
        if cached and cached.get("refresh_expires_at", 0) > time.time() + 3600:
            try:
                data = self._post_raw("/authentication/refreshAccessToken",
                                      {"refreshToken": cached["refreshToken"]}, token=False)
                return self._store(data)
            except CJError:
                pass  # fall back to a fresh token
        data = self._post_raw("/authentication/getAccessToken", {"apiKey": self.api_key}, token=False)
        return self._store(data)

    def _load_cache(self) -> dict | None:
        try:
            return json.loads(self.token_cache.read_text())
        except (OSError, ValueError):
            return None

    def _store(self, data: dict) -> str:
        def ts(s: str | None, default_days: int) -> float:
            if not s:
                return time.time() + default_days * 86400
            try:
                return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                return time.time() + default_days * 86400

        cache = {
            "accessToken": data["accessToken"],
            "refreshToken": data.get("refreshToken"),
            "expires_at": ts(data.get("accessTokenExpiryDate"), 170),
            "refresh_expires_at": ts(data.get("refreshTokenExpiryDate"), 170),
        }
        try:
            self.token_cache.write_text(json.dumps(cache))
            self.token_cache.chmod(0o600)
        except OSError:
            pass
        self._token = cache["accessToken"]
        return self._token

    # ---------- products / stock / freight ----------
    def variant_by_sku(self, variant_sku: str) -> Variant:
        data = self._get("/product/query", {"variantSku": variant_sku})
        for v in (data or {}).get("variants", []) or []:
            if v.get("variantSku") == variant_sku:
                return Variant(vid=v["vid"], sku=variant_sku, sell_price=float(v.get("variantSellPrice") or 0),
                               name=v.get("variantNameEn") or data.get("productNameEn", ""))
        raise CJError(f"variant {variant_sku} not found", "NOT_FOUND", data)

    def stock_by_sku(self, variant_sku: str, country: str = "US") -> int:
        data = self._get("/product/stock/queryBySku", {"sku": variant_sku}) or []
        total = 0
        for row in data if isinstance(data, list) else [data]:
            if not country or row.get("countryCode") == country:
                total += int(row.get("totalInventoryNum") or row.get("storageNum") or 0)
        return total

    def cheapest_shipping(self, items: list[dict], from_country: str, to_country: str, zip_code: str = "") -> dict:
        """items: [{"vid":..., "quantity":...}] -> {"logisticName", "logisticPrice", "logisticAging"}"""
        payload = {"startCountryCode": from_country, "endCountryCode": to_country, "products": items}
        if zip_code:
            payload["zip"] = zip_code
        options = self._post_raw("/logistic/freightCalculate", payload) or []
        if not options:
            raise CJError("no shipping method available", "NO_LOGISTICS", payload)
        def cost(o: dict) -> float:
            for k in ("totalPostageFee", "logisticPrice"):
                if o.get(k) is not None:
                    return float(o[k])
            return 1e9

        return min(options, key=cost)

    # ---------- orders / payment ----------
    def create_order(self, payload: dict) -> dict:
        return self._post_raw("/shopping/order/createOrderV2", payload)

    def order_detail(self, order_id: str) -> dict:
        return self._get("/shopping/order/getOrderDetail", {"orderId": order_id})

    def confirm_order(self, cj_order_id: str) -> Any:
        return self._patch("/shopping/order/confirmOrder", {"orderId": cj_order_id})

    def pay_balance(self, shipment_order_id: str) -> Any:
        return self._post_raw("/shopping/pay/payBalanceV2", {"shipmentOrderId": shipment_order_id})

    def balance(self) -> float:
        data = self._get("/shopping/pay/getBalance") or {}
        return float(data.get("amount") or 0)
