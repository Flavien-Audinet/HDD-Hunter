from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DATA = Path.home() / "Library" / "Application Support" / "HDDHunter"
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "hddhunter.sqlite"
CONFIG_PATH = DATA / "config.json"

DEFAULTS = {
    "price_min": 500, "price_max": 750,
    "capacity_min": 16, "capacity_max": 28,
    "cache_min": 256, "cache_max": 512,
    "rpm": 7200,
    "classes": ["serveur"],                     # + "nas_pro" pour IronWolf Pro / Red Pro…
    "conditions": ["neuf", "reconditionné"],
    "interfaces": ["SATA", "SAS"],
    "interval_min": 60,
    "disabled_sources": [],
    "notify": True,
    "port": 8777,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers(
  id INTEGER PRIMARY KEY, key TEXT UNIQUE, source TEXT, site TEXT, country TEXT, url TEXT,
  title TEXT, brand TEXT, family TEXT, model_no TEXT, capacity_tb REAL, rpm INTEGER,
  cache_mb INTEGER, cache_estimated INTEGER, interface TEXT, condition TEXT, klass TEXT,
  price REAL, price_fr REAL, in_stock INTEGER, active INTEGER DEFAULT 1,
  first_seen REAL, last_seen REAL);
CREATE TABLE IF NOT EXISTS prices(offer_id INTEGER, ts REAL, price_fr REAL, in_stock INTEGER);
CREATE INDEX IF NOT EXISTS prices_offer ON prices(offer_id, ts);
CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY, source TEXT, started REAL, finished REAL,
  status TEXT, found INTEGER, matched INTEGER, message TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, offer_id INTEGER, kind TEXT, text TEXT);
"""


NEW_COLUMNS = {
    "offers": ["condition_src TEXT DEFAULT 'titre'", "condition_note TEXT DEFAULT ''", "seller TEXT DEFAULT ''",
               "page_checked REAL", "page_condition TEXT", "page_src TEXT", "page_note TEXT"],
}


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    for table, cols in NEW_COLUMNS.items():
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for col in cols:
            if col.split()[0] not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
    return c


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except ValueError:
            pass
    return cfg


def save_config(new: dict) -> dict:
    cfg = load_config()
    for k, v in new.items():
        if k not in DEFAULTS:
            continue
        d = DEFAULTS[k]
        if isinstance(d, bool):
            cfg[k] = bool(v)
        elif isinstance(d, (int, float)):
            cfg[k] = float(v) if "." in str(v) else int(v)
        elif isinstance(d, list):
            cfg[k] = [str(x) for x in v]
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    return cfg


def matches(o: dict, cfg: dict) -> bool:
    """Le disque correspond-il à la recherche ? (prix France, capacité, cache, vitesse…)"""
    p = o.get("price_fr")
    cache = o.get("cache_mb")
    return bool(
        p is not None and cfg["price_min"] <= p <= cfg["price_max"]
        and o.get("capacity_tb") and cfg["capacity_min"] <= o["capacity_tb"] <= cfg["capacity_max"]
        and o.get("rpm") == cfg["rpm"]
        and cache is not None and cfg["cache_min"] <= cache <= cfg["cache_max"]
        and o.get("klass") in cfg["classes"]
        and o.get("condition") in cfg["conditions"]
        and o.get("interface") in cfg["interfaces"]
        and o.get("in_stock") != 0
    )


def now() -> float:
    return time.time()
