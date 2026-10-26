"""Amazon SP-API side: read unshipped MFN orders, read shipping address, confirm shipment."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .config import Settings


@dataclass
class OrderLine:
    order_item_id: str
    seller_sku: str
    quantity: int
    item_price: float          # total for the line (ItemPrice.Amount), USD
    title: str = ""


@dataclass
class AmazonOrder:
    order_id: str
    purchase_date: str
    lines: list[OrderLine] = field(default_factory=list)
    name: str = ""
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = "US"
    phone: str = ""


# CJ carrier name -> Amazon carrierCode (anything unknown is sent as "Other" + carrierName)
CARRIER_CODES = {"usps": "USPS", "ups": "UPS", "fedex": "FedEx", "dhl": "DHL", "ontrac": "OnTrac"}


class AmazonClient:
    def __init__(self, settings: Settings):
        from sp_api.api import Orders  # imported lazily so CJ-only runs work without SP-API creds
        from sp_api.base import Marketplaces

        self.s = settings
        self.creds = dict(
            refresh_token=settings.sp_refresh_token,
            lwa_app_id=settings.sp_lwa_app_id,
            lwa_client_secret=settings.sp_lwa_client_secret,
        )
        self._Orders = Orders
        self.marketplace = Marketplaces.US

    def _orders(self):
        return self._Orders(marketplace=self.marketplace, credentials=self.creds)

    def unshipped_orders(self) -> list[AmazonOrder]:
        since = (datetime.now(timezone.utc) - timedelta(days=self.s.lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        api = self._orders()
        out: list[AmazonOrder] = []
        token = None
        while True:
            kw = dict(CreatedAfter=since, OrderStatuses=["Unshipped", "PartiallyShipped"],
                      FulfillmentChannels=["MFN"], MarketplaceIds=[self.s.sp_marketplace_id])
            if token:
                kw = {"NextToken": token}
            res = api.get_orders(**kw).payload
            for o in res.get("Orders", []):
                out.append(AmazonOrder(order_id=o["AmazonOrderId"], purchase_date=o.get("PurchaseDate", "")))
            token = res.get("NextToken")
            if not token:
                break
        for order in out:
            self._fill(order)
        return out

    def _fill(self, order: AmazonOrder) -> None:
        api = self._orders()
        items = api.get_order_items(order.order_id).payload.get("OrderItems", [])
        for it in items:
            qty = int(it.get("QuantityOrdered", 0)) - int(it.get("QuantityShipped", 0))
            if qty <= 0:
                continue
            order.lines.append(OrderLine(
                order_item_id=it["OrderItemId"], seller_sku=it.get("SellerSKU", ""), quantity=qty,
                item_price=float((it.get("ItemPrice") or {}).get("Amount") or 0), title=it.get("Title", "")))
        # Shipping address is PII -> needs a Restricted Data Token (Direct-to-Consumer Shipping role).
        detail = self._orders().get_order(order.order_id, RestrictedResources=["shippingAddress"]).payload
        a = detail.get("ShippingAddress") or {}
        order.name = a.get("Name", "")
        order.address1 = a.get("AddressLine1", "")
        order.address2 = " ".join(x for x in (a.get("AddressLine2"), a.get("AddressLine3")) if x)
        order.city = a.get("City", "")
        order.state = a.get("StateOrRegion", "")
        order.zip = a.get("PostalCode", "")
        order.country = a.get("CountryCode", "US")
        order.phone = a.get("Phone", "")

    def confirm_shipment(self, order: AmazonOrder, carrier: str, tracking: str, ship_date: datetime | None = None):
        code = CARRIER_CODES.get((carrier or "").strip().lower().split(" ")[0], "Other")
        pkg = {
            "packageReferenceId": "1",
            "carrierCode": code,
            "trackingNumber": tracking,
            "shipDate": (ship_date or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "orderItems": [{"orderItemId": l.order_item_id, "quantity": l.quantity} for l in order.lines],
        }
        if code == "Other":
            pkg["carrierName"] = carrier or "Other"
        return self._orders().confirm_shipment(order.order_id, marketplaceId=self.s.sp_marketplace_id,
                                               packageDetail=pkg)
