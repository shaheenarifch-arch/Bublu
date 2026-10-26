"""Settings for BUBLU, read from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def load_dotenv(path: str = ".env") -> None:
    """Tiny .env loader so we don't need python-dotenv on the VPS."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Settings:
    # --- CJdropshipping ---
    cj_api_key: str = ""
    cj_store_name: str = "loveandcare-amazon"
    cj_from_country: str = "US"          # ship from CJ US warehouses only
    cj_sandbox: bool = False             # CJ isSandbox=1 (simulated payment)

    # --- Amazon SP-API (Love and Care, US marketplace) ---
    sp_refresh_token: str = ""
    sp_lwa_app_id: str = ""
    sp_lwa_client_secret: str = ""
    sp_marketplace_id: str = "ATVPDKIKX0DER"

    # --- Business rules ---
    dry_run: bool = True                 # first week: never pays CJ, never confirms on Amazon
    min_margin: float = 0.30             # profit / Amazon item price, after referral fee
    amazon_fee_rate: float = 0.15        # Amazon referral fee
    min_cj_balance: float = 50.0         # alert below this wallet balance
    lookback_days: int = 7

    # --- Files / alerts ---
    db_path: str = "bublu.db"
    sku_map_path: str = field(default_factory=lambda: str(Path(__file__).resolve().parent.parent / "sku_map.json"))
    alert_email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        e = os.getenv
        return cls(
            cj_api_key=e("CJ_API_KEY", ""),
            cj_store_name=e("CJ_STORE_NAME", "loveandcare-amazon"),
            cj_from_country=e("CJ_FROM_COUNTRY", "US"),
            cj_sandbox=_bool("CJ_SANDBOX", False),
            sp_refresh_token=e("SP_API_REFRESH_TOKEN", ""),
            sp_lwa_app_id=e("LWA_APP_ID", ""),
            sp_lwa_client_secret=e("LWA_CLIENT_SECRET", ""),
            sp_marketplace_id=e("SP_MARKETPLACE_ID", "ATVPDKIKX0DER"),
            dry_run=_bool("BUBLU_DRY_RUN", True),
            min_margin=float(e("BUBLU_MIN_MARGIN", "0.30")),
            amazon_fee_rate=float(e("BUBLU_AMAZON_FEE_RATE", "0.15")),
            min_cj_balance=float(e("BUBLU_MIN_CJ_BALANCE", "50")),
            lookback_days=int(e("BUBLU_LOOKBACK_DAYS", "7")),
            db_path=e("BUBLU_DB_PATH", "bublu.db"),
            sku_map_path=e("BUBLU_SKU_MAP", cls().sku_map_path),
            alert_email_to=e("ALERT_EMAIL_TO", ""),
            smtp_host=e("SMTP_HOST", ""),
            smtp_port=int(e("SMTP_PORT", "587")),
            smtp_user=e("SMTP_USER", ""),
            smtp_password=e("SMTP_PASSWORD", ""),
            smtp_from=e("SMTP_FROM", ""),
        )

    @property
    def amazon_configured(self) -> bool:
        return bool(self.sp_refresh_token and self.sp_lwa_app_id and self.sp_lwa_client_secret)
