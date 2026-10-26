"""BUBLU order pipeline: Amazon (Love and Care) -> CJdropshipping -> tracking back to Amazon.

Commands:
    python -m bublu check-cj     # CJ login, wallet, and price/stock/shipping/margin for every mapped SKU
    python -m bublu run          # process new Amazon orders, then sync tracking
    python -m bublu track        # only sync CJ tracking back to Amazon
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass

from .cj import CJClient, CJError
from .config import Settings
from .notify import Notifier
from .state import State

log = logging.getLogger("bublu")


def load_sku_map(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


@dataclass
class Quote:
    product_cost: float
    shipping_cost: float
    logistic_name: str
    items: list[dict]

    @property
    def total(self) -> float:
        return round(self.product_cost + self.shipping_cost, 2)


def margin(amazon_total: float, cj_total: float, fee_rate: float) -> float:
    """Profit after Amazon referral fee and CJ cost, as a share of the Amazon sale price."""
    if amazon_total <= 0:
        return -1.0
    return round((amazon_total * (1 - fee_rate) - cj_total) / amazon_total, 4)


class Bublu:
    def __init__(self, settings: Settings, cj: CJClient, amazon=None, state: State | None = None,
                 notifier: Notifier | None = None):
        self.s = settings
        self.cj = cj
        self.amazon = amazon
        self.state = state or State(settings.db_path)
        self.notify = notifier or Notifier(settings)
        self.sku_map = load_sku_map(settings.sku_map_path)

    # ---------- pricing ----------
    def quote(self, lines: list[tuple[str, int]], zip_code: str = "") -> Quote:
        """lines: [(cj_variant_sku, qty)] -> CJ product + cheapest US->US shipping cost."""
        items, product_cost = [], 0.0
        for cj_sku, qty in lines:
            v = self.cj.variant_by_sku(cj_sku)
            stock = self.cj.stock_by_sku(cj_sku, self.s.cj_from_country)
            if stock < qty:
                raise CJError(f"{cj_sku} has only {stock} in {self.s.cj_from_country} stock, need {qty}", "NO_STOCK")
            items.append({"vid": v.vid, "quantity": qty, "sku": cj_sku})
            product_cost += v.sell_price * qty
        ship = self.cj.cheapest_shipping([{"vid": i["vid"], "quantity": i["quantity"]} for i in items],
                                         self.s.cj_from_country, "US", zip_code)
        ship_cost = float(ship["totalPostageFee"] if ship.get("totalPostageFee") is not None
                          else ship.get("logisticPrice") or 0)
        return Quote(round(product_cost, 2), round(ship_cost, 2), ship["logisticName"], items)

    # ---------- health check ----------
    def check_cj(self) -> list[dict]:
        rows = []
        bal = self.cj.balance()
        for amazon_sku, m in self.sku_map.items():
            row = {"amazon_sku": amazon_sku, "name": m.get("name", ""), "amazon_price": m.get("amazon_price")}
            try:
                q = self.quote([(m["cj_sku"], 1)])
                row.update(cj_product=q.product_cost, cj_shipping=q.shipping_cost, cj_total=q.total,
                           logistic=q.logistic_name,
                           us_stock=self.cj.stock_by_sku(m["cj_sku"], self.s.cj_from_country))
                if m.get("amazon_price"):
                    row["margin"] = margin(m["amazon_price"], q.total, self.s.amazon_fee_rate)
                row["ok"] = row.get("margin", 1) >= self.s.min_margin
            except CJError as e:
                row.update(ok=False, error=str(e))
            rows.append(row)
        problems = [r for r in rows if not r["ok"]]
        lines = [f"CJ wallet balance: ${bal:.2f}"]
        for r in rows:
            if "error" in r:
                lines.append(f"!! {r['amazon_sku']} {r['name']}: {r['error']}")
            else:
                flag = "OK" if r["ok"] else "LOW MARGIN"
                lines.append(f"{flag:10} {r['amazon_sku']} {r['name'][:32]:32} Amazon ${r['amazon_price']} | "
                             f"CJ ${r['cj_total']} ({r['logistic']}) | margin {r.get('margin', 0):.0%} | "
                             f"US stock {r['us_stock']}")
        self.notify.send(f"CJ check: {len(rows) - len(problems)}/{len(rows)} SKUs OK", "\n".join(lines))
        if bal < self.s.min_cj_balance:
            self.notify.send("CJ wallet low", f"Balance ${bal:.2f} is below ${self.s.min_cj_balance:.2f}. "
                                              "Top up so orders can be paid automatically.")
        return rows

    # ---------- orders ----------
    def process_new_orders(self) -> None:
        if self.amazon is None:
            log.warning("Amazon SP-API not configured; skipping order intake")
            return
        for order in self.amazon.unshipped_orders():
            prev = self.state.get(order.order_id)
            if prev is not None and prev["status"] not in ("seen", "failed"):
                continue  # already handled (held / dry_run / placed / paid / shipped)
            self.handle_order(order)

    def handle_order(self, order) -> str:
        oid = order.order_id
        unknown = [l.seller_sku for l in order.lines if l.seller_sku not in self.sku_map]
        if unknown:
            self.state.upsert(oid, status="held", note=f"unknown SKU(s): {unknown}")
            self.notify.send(f"Order {oid} held: unknown SKU", f"SKU(s) not in sku_map.json: {', '.join(unknown)}")
            return "held"
        amazon_total = round(sum(l.item_price for l in order.lines), 2)
        try:
            q = self.quote([(self.sku_map[l.seller_sku]["cj_sku"], l.quantity) for l in order.lines], order.zip)
        except CJError as e:
            self.state.upsert(oid, status="held", amazon_amount=amazon_total, note=str(e))
            self.notify.send(f"Order {oid} held", f"Could not price order on CJ: {e}\nPlace it manually.")
            return "held"
        m = margin(amazon_total, q.total, self.s.amazon_fee_rate)
        if m < self.s.min_margin:
            self.state.upsert(oid, status="held", amazon_amount=amazon_total, cj_amount=q.total, margin=m,
                              note="margin below minimum")
            self.notify.send(f"Order {oid} held: margin {m:.0%}",
                             f"Amazon ${amazon_total} vs CJ ${q.total} (product ${q.product_cost} + shipping "
                             f"${q.shipping_cost}). Below the {self.s.min_margin:.0%} minimum. Decide manually.")
            return "held"

        payload = self.cj_payload(order, q)
        if self.s.dry_run:
            self.state.upsert(oid, status="dry_run", amazon_amount=amazon_total, cj_amount=q.total, margin=m,
                              raw=payload)
            self.notify.send(f"[DRY RUN] Would order {oid} on CJ",
                             f"Amazon ${amazon_total} | CJ ${q.total} via {q.logistic_name} | margin {m:.0%}\n"
                             f"Ship to: {order.name}, {order.city}, {order.state} {order.zip}\n"
                             + "\n".join(f"- {l.quantity} x {l.seller_sku}" for l in order.lines))
            return "dry_run"

        try:
            res = self.cj.create_order(payload)
        except CJError as e:
            self.state.upsert(oid, status="failed", amazon_amount=amazon_total, note=f"create: {e}")
            self.notify.send(f"Order {oid} FAILED on CJ", f"createOrderV2 error: {e}\nPlace it manually.")
            return "failed"
        cj_id, ship_id = res.get("orderId"), res.get("shipmentOrderId")
        cj_amount = float(res.get("orderAmount") or q.total)
        self.state.upsert(oid, status="placed", cj_order_id=cj_id, cj_shipment_id=ship_id, cj_amount=cj_amount,
                          amazon_amount=amazon_total, margin=margin(amazon_total, cj_amount, self.s.amazon_fee_rate),
                          raw=res)
        if margin(amazon_total, cj_amount, self.s.amazon_fee_rate) < self.s.min_margin:
            self.state.upsert(oid, status="held", note="CJ order amount higher than quote; not paid")
            self.notify.send(f"Order {oid} created on CJ but NOT paid",
                             f"CJ charged ${cj_amount} vs quote ${q.total}. Review CJ order {cj_id} before paying.")
            return "held"
        try:
            self.cj.pay_balance(ship_id)
        except CJError as e:
            self.state.upsert(oid, note=f"pay: {e}")
            self.notify.send(f"Order {oid} created on CJ, payment failed",
                             f"CJ order {cj_id}: {e}\nCheck your CJ wallet balance and pay it in CJ.")
            return "placed"
        self.state.upsert(oid, status="paid")
        self.notify.send(f"Order {oid} placed on CJ",
                         f"CJ order {cj_id} paid ${cj_amount} | Amazon ${amazon_total} | margin "
                         f"{margin(amazon_total, cj_amount, self.s.amazon_fee_rate):.0%}")
        return "paid"

    def cj_payload(self, order, q: Quote) -> dict:
        sku_by_vid = {i["vid"]: i["sku"] for i in q.items}
        lines_by_cj = {self.sku_map[l.seller_sku]["cj_sku"]: l for l in order.lines}
        return {
            "orderNumber": order.order_id,
            "shippingCountryCode": order.country or "US",
            "shippingCountry": "United States",
            "shippingProvince": order.state,
            "shippingCity": order.city,
            "shippingZip": order.zip,
            "shippingCustomerName": order.name,
            "shippingAddress": order.address1,
            "shippingAddress2": order.address2,
            "shippingPhone": order.phone,
            "logisticName": q.logistic_name,
            "fromCountryCode": self.s.cj_from_country,
            "payType": 3,                       # create only; BUBLU pays after re-checking the amount
            "isSandbox": 1 if self.s.cj_sandbox else 0,
            "platform": "Amazon",
            "storeName": self.s.cj_store_name,
            "remark": "Amazon order - please use neutral packaging, no CJ invoice or branding",
            "products": [{"vid": i["vid"], "quantity": i["quantity"],
                          "storeLineItemId": lines_by_cj[sku_by_vid[i["vid"]]].order_item_id} for i in q.items],
        }

    # ---------- tracking ----------
    def sync_tracking(self) -> None:
        if self.amazon is None:
            return
        for row in self.state.awaiting_tracking():
            try:
                d = self.cj.order_detail(row["cj_order_id"]) or {}
            except CJError as e:
                log.warning("tracking lookup failed for %s: %s", row["amazon_order_id"], e)
                continue
            tracking, carrier = d.get("trackNumber"), d.get("trackingProvider") or d.get("logisticName")
            if not tracking:
                continue
            if self.s.dry_run:
                self.notify.send(f"[DRY RUN] Would confirm {row['amazon_order_id']}", f"{carrier} {tracking}")
                continue
            try:
                self.amazon.confirm_shipment(self._order_stub(row), carrier, tracking)
            except Exception as e:  # SP-API raises its own exception types
                self.notify.send(f"Tracking upload failed for {row['amazon_order_id']}",
                                 f"{carrier} {tracking}: {e}\nAdd it manually in Seller Central.")
                continue
            self.state.upsert(row["amazon_order_id"], status="shipped", tracking=tracking, carrier=carrier)
            self.notify.send(f"Order {row['amazon_order_id']} shipped", f"{carrier} {tracking} sent to Amazon.")

    def _order_stub(self, row):
        """Rebuild the Amazon order lines from the stored CJ payload (order item ids + quantities)."""
        from .amazon import AmazonOrder, OrderLine
        raw = json.loads(row["raw"] or "{}")
        lines = []
        for p in raw.get("productInfoList", raw.get("products", [])):
            if p.get("storeLineItemId"):
                lines.append(OrderLine(order_item_id=p["storeLineItemId"], seller_sku="",
                                       quantity=int(p.get("quantity", 1)), item_price=0))
        return AmazonOrder(order_id=row["amazon_order_id"], purchase_date="", lines=lines)


def build(settings: Settings) -> Bublu:
    cj = CJClient(settings.cj_api_key)
    amazon = None
    if settings.amazon_configured:
        from .amazon import AmazonClient
        amazon = AmazonClient(settings)
    return Bublu(settings, cj, amazon)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="bublu")
    p.add_argument("command", choices=["check-cj", "run", "track"])
    args = p.parse_args(argv)
    s = Settings.from_env()
    b = build(s)
    log.info("BUBLU %s (dry_run=%s, sandbox=%s)", args.command, s.dry_run, s.cj_sandbox)
    if args.command == "check-cj":
        b.check_cj()
    elif args.command == "run":
        b.process_new_orders()
        b.sync_tracking()
    else:
        b.sync_tracking()
    return 0


if __name__ == "__main__":
    sys.exit(main())
