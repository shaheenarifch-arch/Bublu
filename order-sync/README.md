# BUBLU order sync — Amazon (Love and Care) → CJdropshipping

> Lives in `order-sync/` of the Bublu repo. Run every command from this folder.

BUBLU is the Amazon + CJ Dropshipping pod for ATLAS / ROMEO Studio (romeo-studio issue #45).
Every 15 minutes it:

1. Reads new **unshipped, merchant-fulfilled** Love and Care orders from Amazon SP-API.
2. Maps each Amazon SKU to its CJ variant (`sku_map.json`; Love and Care SKUs are `LC-` + CJ variant SKU).
3. Prices the order on CJ (variant price + cheapest **US → US** shipping) and checks US stock.
4. Holds the order and alerts you if the SKU is unknown, stock is short, or margin is under **30%**.
5. Creates the CJ order (`payType=3`, create only), re-checks the charged amount, then pays from the CJ wallet.
6. Polls CJ for tracking and confirms shipment on Amazon.

Every Amazon order is recorded in SQLite, so it is never ordered twice.

## Safety switches

| Setting | Default | Effect |
|---|---|---|
| `BUBLU_DRY_RUN` | `true` | Prices orders and emails what it *would* do; never creates/pays CJ orders or confirms on Amazon |
| `CJ_SANDBOX` | `false` | CJ `isSandbox=1`: simulated payment, no real charge or fulfilment |
| `BUBLU_MIN_MARGIN` | `0.30` | Orders below this margin are held for you |
| `BUBLU_MIN_CJ_BALANCE` | `50` | Alert when the CJ wallet drops below this |

## Commands

```bash
python -m bublu check-cj   # CJ login + wallet + price/stock/shipping/margin for every mapped SKU
python -m bublu run        # process new Amazon orders, then sync tracking
python -m bublu track      # tracking sync only
python -m pytest -q        # offline tests (no keys needed)
```

## Setup

1. **CJ API key** — CJ → Settings → API → generate. Put it in `.env` as `CJ_API_KEY`.
2. **Amazon SP-API** — Seller Central → Apps and Services → Develop Apps → register as a *private developer*,
   requesting the **Direct-to-Consumer Shipping** (restricted) role for shipping addresses. Create the app,
   self-authorize it, then put `LWA_APP_ID`, `LWA_CLIENT_SECRET`, `SP_API_REFRESH_TOKEN` in `.env`.
   Until this is approved, BUBLU runs CJ-only (`check-cj`) and orders are placed manually.
3. **Deploy on the Oracle VPS**: clone the repo, `cd order-sync`, `sudo bash deploy/install.sh`, edit `/opt/bublu/.env`,
   run `check-cj`, then `sudo systemctl enable --now bublu.timer`.
4. Keep `BUBLU_DRY_RUN=true` for the first week, review the emails, then set it to `false`.

## Adding a product

Add a line to `sku_map.json`: `"LC-<CJ variant SKU>": {"cj_sku": "<CJ variant SKU>", "name": "...", "amazon_price": 0.00}`.
Before listing, confirm the CJ product page does **not** say "Non-sellable platforms: ... Amazon".

## API references

- CJ API v2: <https://developers.cjdropshipping.com/en/api/api2/api/auth.html>
- Amazon SP-API Orders: <https://developer-docs.amazon.com/sp-api/>
