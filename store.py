"""store.py — sqlite-пул товаров и журнал публикаций.

Зачем: чтобы 4 поста в день были РАЗНЫМИ, не повторялись неделями и чтобы цена
в посте всегда соответствовала той, что реально была на Poizon в момент публикации.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    spu_id       INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    path         TEXT NOT NULL,
    price        REAL,
    price_text   TEXT,
    image        TEXT,
    gallery      TEXT,
    brand        TEXT,
    article      TEXT,
    category     TEXT,
    model        TEXT,
    color        TEXT,
    sold_text    TEXT,
    source       TEXT,
    has_white    INTEGER DEFAULT 0,
    first_seen   TEXT,
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS posted (
    spu_id       INTEGER PRIMARY KEY,
    posted_at    TEXT,
    price        REAL,
    title        TEXT,
    msg_id       INTEGER,
    photo        TEXT
);
CREATE TABLE IF NOT EXISTS events (
    ts           TEXT,
    level        TEXT,
    text         TEXT
);
CREATE TABLE IF NOT EXISTS state (
    key          TEXT PRIMARY KEY,
    value        TEXT
);
CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
CREATE INDEX IF NOT EXISTS idx_posted_at ON posted(posted_at);
"""


@dataclass
class Candidate:
    spu_id: int
    title: str
    path: str
    price: float | None
    price_text: str
    image: str
    gallery: list[str]
    brand: str
    article: str
    model: str
    color: str
    category: str
    sold_text: str
    source: str

    @property
    def url(self) -> str:
        return "https://www.thepoizon.ru" + (self.path or "")

    def images(self) -> list[str]:
        out, seen = [], set()
        for u in ([self.image] if self.image else []) + list(self.gallery):
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --------------------------------------------------------------- записи
    def upsert_product(self, p) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO products (spu_id, title, path, price, price_text, image, gallery,
                                  brand, article, category, model, color, sold_text, source,
                                  first_seen, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(spu_id) DO UPDATE SET
                title=excluded.title, path=excluded.path, price=excluded.price,
                price_text=excluded.price_text, image=excluded.image,
                gallery=excluded.gallery, brand=excluded.brand, article=excluded.article,
                category=excluded.category, model=excluded.model, color=excluded.color,
                sold_text=excluded.sold_text, updated_at=excluded.updated_at
            """,
            (p.spu_id, p.title, p.path, p.price, p.price_text, p.main_image,
             json.dumps(p.all_images(), ensure_ascii=False), p.brand, p.article,
             p.category, getattr(p, "model", ""), getattr(p, "color", ""),
             p.sold_text, p.source, now, now),
        )
        self.conn.commit()

    def mark_posted(self, spu_id: int, price: float | None, title: str,
                    msg_id, photo: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO posted (spu_id, posted_at, price, title, msg_id, photo) "
            "VALUES (?,?,?,?,?,?)",
            (spu_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             price, title, msg_id, photo),
        )
        self.conn.commit()

    def log(self, level: str, text: str) -> None:
        self.conn.execute(
            "INSERT INTO events (ts, level, text) VALUES (?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), level, text[:500]),
        )
        self.conn.execute("DELETE FROM events WHERE ts < datetime('now', '-30 day')")
        self.conn.commit()

    # ---------------------------------------------------------------- чтения
    def get_state(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO state (key, value) VALUES (?,?)", (key, str(value))
        )
        self.conn.commit()

    def candidates(self, min_price: float | None, max_price: float | None,
                   exclude_words: list[str], no_repost_days: int, limit: int = 400) -> list[Candidate]:
        sql = """
            SELECT p.* FROM products p
            LEFT JOIN posted q ON q.spu_id = p.spu_id
            WHERE (q.posted_at IS NULL OR q.posted_at < datetime('now', ?))
        """
        args: list = [f"-{int(no_repost_days)} day"]
        if min_price:
            sql += " AND p.price >= ?"
            args.append(min_price)
        if max_price:
            sql += " AND p.price <= ?"
            args.append(max_price)
        for word in exclude_words or []:
            sql += " AND lower(p.title) NOT LIKE ?"
            args.append(f"%{word.lower()}%")
        # свежие и проверенные цены идут первыми
        sql += " ORDER BY p.updated_at DESC, p.price ASC LIMIT ?"
        args.append(limit)
        rows = self.conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            try:
                gallery = json.loads(r["gallery"] or "[]")
            except json.JSONDecodeError:
                gallery = []
            out.append(Candidate(
                spu_id=r["spu_id"], title=r["title"], path=r["path"], price=r["price"],
                price_text=r["price_text"] or "", image=r["image"] or "", gallery=gallery,
                brand=r["brand"] or "", article=r["article"] or "", model=r["model"] or "",
                color=r["color"] or "", category=r["category"] or "",
                sold_text=r["sold_text"] or "", source=r["source"] or "",
            ))
        return out

    def counts(self) -> dict:
        pool = self.conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
        posted = self.conn.execute("SELECT COUNT(*) c FROM posted").fetchone()["c"]
        priced = self.conn.execute(
            "SELECT COUNT(*) c FROM products WHERE price IS NOT NULL").fetchone()["c"]
        last = self.conn.execute(
            "SELECT MAX(posted_at) t FROM posted").fetchone()["t"]
        return {"pool": pool, "priced": priced, "posted": posted, "last_posted": last}

    def recent_events(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ts, level, text FROM events ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def purge_pool_if_stale(self, max_age_hours: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM products WHERE updated_at < datetime('now', ?)",
            (f"-{int(max_age_hours)} hour",),
        )
        self.conn.commit()
        return cur.rowcount
