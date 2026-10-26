"""SQLite record of every Amazon order BUBLU has seen, so nothing is ever ordered twice."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    amazon_order_id   TEXT PRIMARY KEY,
    status            TEXT NOT NULL,        -- seen | held | dry_run | placed | paid | shipped | failed
    cj_order_id       TEXT,
    cj_shipment_id    TEXT,
    cj_amount         REAL,
    amazon_amount     REAL,
    margin            REAL,
    tracking          TEXT,
    carrier           TEXT,
    note              TEXT,
    raw               TEXT,
    updated_at        TEXT NOT NULL
);
"""


class State:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def get(self, amazon_order_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM orders WHERE amazon_order_id=?", (amazon_order_id,)).fetchone()

    def upsert(self, amazon_order_id: str, **fields) -> None:
        fields["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if "raw" in fields and not isinstance(fields["raw"], str):
            fields["raw"] = json.dumps(fields["raw"], default=str)
        existing = self.get(amazon_order_id)
        if existing is None:
            fields.setdefault("status", "seen")
            cols = ["amazon_order_id", *fields]
            self.db.execute(f"INSERT INTO orders ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                            [amazon_order_id, *fields.values()])
        else:
            sets = ",".join(f"{k}=?" for k in fields)
            self.db.execute(f"UPDATE orders SET {sets} WHERE amazon_order_id=?", [*fields.values(), amazon_order_id])
        self.db.commit()

    def awaiting_tracking(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM orders WHERE status IN ('paid','placed') AND cj_order_id IS NOT NULL").fetchall()
