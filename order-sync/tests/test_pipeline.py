"""Offline tests: CJ and Amazon are faked, so no keys or network are needed."""
import json

import pytest

from bublu.amazon import AmazonOrder, OrderLine
from bublu.cj import CJError, Variant
from bublu.config import Settings
from bublu.notify import Notifier
from bublu.runner import Bublu, margin
from bublu.state import State


class FakeCJ:
    def __init__(self, price=5.0, ship=3.0, stock=100, order_amount=None):
        self.price, self.ship, self.stock, self.order_amount = price, ship, stock, order_amount
        self.created, self.paid, self.detail = [], [], {}

    def variant_by_sku(self, sku):
        return Variant(vid="vid-" + sku, sku=sku, sell_price=self.price)

    def stock_by_sku(self, sku, country="US"):
        return self.stock

    def cheapest_shipping(self, items, f, t, z=""):
        return {"logisticName": "USPS US to US", "logisticPrice": self.ship}

    def create_order(self, payload):
        self.created.append(payload)
        amt = self.order_amount if self.order_amount is not None else self.price + self.ship
        return {"orderId": "CJ1", "shipmentOrderId": "SH1", "orderAmount": amt,
                "productInfoList": [{"storeLineItemId": p["storeLineItemId"], "quantity": p["quantity"]}
                                    for p in payload["products"]]}

    def pay_balance(self, sid):
        self.paid.append(sid)

    def order_detail(self, oid):
        return self.detail

    def balance(self):
        return 100.0


class FakeAmazon:
    def __init__(self, orders):
        self.orders, self.confirmed = orders, []

    def unshipped_orders(self):
        return self.orders

    def confirm_shipment(self, order, carrier, tracking):
        self.confirmed.append((order.order_id, carrier, tracking, [l.order_item_id for l in order.lines]))


def order(sku="LC-CJJT252566401AZ", price=18.99, qty=1, oid="111-0000001-0000001"):
    return AmazonOrder(order_id=oid, purchase_date="", lines=[OrderLine("ITEM1", sku, qty, price)],
                       name="Jane Doe", address1="1 Main St", city="Boston", state="MA", zip="02110")


def make(tmp_path, cj, amazon, dry_run=False):
    s = Settings(dry_run=dry_run, db_path=str(tmp_path / "t.db"))
    return Bublu(s, cj, amazon, State(s.db_path), Notifier(s))


def test_margin_formula():
    assert margin(100, 55, 0.15) == 0.30


def test_happy_path_places_and_pays_once(tmp_path):
    cj, amz = FakeCJ(price=5, ship=3), FakeAmazon([order()])
    b = make(tmp_path, cj, amz)
    b.process_new_orders()
    b.process_new_orders()  # second run must not reorder
    assert len(cj.created) == 1 and cj.paid == ["SH1"]
    p = cj.created[0]
    assert p["payType"] == 3 and p["orderNumber"] == "111-0000001-0000001"
    assert p["products"][0]["vid"] == "vid-CJJT252566401AZ" and p["products"][0]["storeLineItemId"] == "ITEM1"
    assert b.state.get("111-0000001-0000001")["status"] == "paid"


def test_dry_run_never_orders(tmp_path):
    cj = FakeCJ()
    b = make(tmp_path, cj, FakeAmazon([order()]), dry_run=True)
    b.process_new_orders()
    assert cj.created == [] and b.state.get("111-0000001-0000001")["status"] == "dry_run"


def test_low_margin_is_held(tmp_path):
    cj = FakeCJ(price=12, ship=3)  # 15/18.99 cost -> margin ~6%
    b = make(tmp_path, cj, FakeAmazon([order()]))
    b.process_new_orders()
    assert cj.created == [] and b.state.get("111-0000001-0000001")["status"] == "held"


def test_unknown_sku_is_held(tmp_path):
    cj = FakeCJ()
    b = make(tmp_path, cj, FakeAmazon([order(sku="LC-NOPE")]))
    b.process_new_orders()
    assert cj.created == [] and "unknown SKU" in b.state.get("111-0000001-0000001")["note"]


def test_out_of_stock_is_held(tmp_path):
    cj = FakeCJ(stock=0)
    b = make(tmp_path, cj, FakeAmazon([order()]))
    b.process_new_orders()
    assert cj.created == [] and b.state.get("111-0000001-0000001")["status"] == "held"


def test_price_jump_after_create_is_not_paid(tmp_path):
    cj = FakeCJ(price=5, ship=3, order_amount=17.0)
    b = make(tmp_path, cj, FakeAmazon([order()]))
    b.process_new_orders()
    assert len(cj.created) == 1 and cj.paid == []
    assert b.state.get("111-0000001-0000001")["status"] == "held"


def test_tracking_is_sent_to_amazon(tmp_path):
    cj, amz = FakeCJ(price=5, ship=3), FakeAmazon([order()])
    b = make(tmp_path, cj, amz)
    b.process_new_orders()
    cj.detail = {"trackNumber": "9400111", "trackingProvider": "USPS"}
    b.sync_tracking()
    assert amz.confirmed == [("111-0000001-0000001", "USPS", "9400111", ["ITEM1"])]
    assert b.state.get("111-0000001-0000001")["status"] == "shipped"


def test_sku_map_matches_listing_convention():
    from bublu.runner import load_sku_map
    m = load_sku_map(Settings().sku_map_path)
    assert len(m) == 20
    for amazon_sku, v in m.items():
        assert amazon_sku == "LC-" + v["cj_sku"]
        assert margin(v["amazon_price"], v["amazon_price"] * 0.55, 0.15) >= 0.29
