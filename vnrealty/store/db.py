"""The local data store: one SQLite file (stdlib sqlite3), default ``data/vnr.sqlite``.

Design rules, enforced here rather than hoped for:

* **Every price is an observation.** A listing is an identity (``listing``); each time its price is seen it gets a
  row in ``listing_obs`` with when, where (url), what kind (``asking`` | ``sale`` | ``rent``) and a pointer to the
  raw page text it came from. Price history is therefore a query, never an overwrite.
* **Point in time.** Every reader that takes ``as_of`` sees only rows with ``seen_at <= as_of``.
* **Citations.** Projects carry ``project_evidence`` rows (url, title, date); sale evidence carries its source.
* **Money in VND, area in m², dates ISO-8601 (YYYY-MM-DD or full timestamp).**

Override the location with ``VNR_DB`` or the ``path`` argument. ``connect()`` creates and migrates on first use.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

__all__ = ["REPO", "default_path", "connect", "SCHEMA_VERSION"]

REPO = Path(os.environ.get("VNR_REPO") or Path(__file__).resolve().parents[2])
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- a ward / commune; code is our stable slug, name_vi the official name; old_* keeps the pre-2025 unit it came from
CREATE TABLE IF NOT EXISTS ward (
  code TEXT PRIMARY KEY, name_vi TEXT NOT NULL, name_en TEXT, city TEXT NOT NULL DEFAULT 'da-nang',
  old_district TEXT, old_ward TEXT, lat REAL, lng REAL, notes TEXT);

-- one physical property as listed (deduplicated across sites by fingerprint)
CREATE TABLE IF NOT EXISTS listing (
  id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
  ptype TEXT NOT NULL,            -- land | house | apartment | shophouse | villa | chdv | room | other
  deal TEXT NOT NULL DEFAULT 'sale', -- sale | rent
  title TEXT, address TEXT, street TEXT, ward_code TEXT REFERENCES ward(code), city TEXT DEFAULT 'da-nang',
  lat REAL, lng REAL, area_m2 REAL, floor_area_m2 REAL, frontage_m REAL, depth_m REAL, alley_m REAL,
  floors REAL, bedrooms REAL, corner INTEGER, direction TEXT, legal TEXT,   -- legal: so_hong | so_do | hdmb | giay_tay | unknown
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', -- active | gone | sold
  watch INTEGER NOT NULL DEFAULT 0, notes TEXT);

-- every sighting of a price (the price history)
CREATE TABLE IF NOT EXISTS listing_obs (
  id INTEGER PRIMARY KEY, listing_id INTEGER NOT NULL REFERENCES listing(id),
  seen_at TEXT NOT NULL, site TEXT NOT NULL, url TEXT, site_id TEXT,
  kind TEXT NOT NULL,             -- asking | sale | rent  (rent = VND per month)
  price REAL,                     -- NULL when 'thỏa thuận' (negotiable): an observation without a number
  price_m2 REAL, posted_at TEXT, raw_ref TEXT, extra TEXT,
  UNIQUE (listing_id, site, seen_at));

-- a sale that actually happened (notarised, broker-confirmed, court/auction): the only ground truth for price
CREATE TABLE IF NOT EXISTS sale_evidence (
  id INTEGER PRIMARY KEY, listing_id INTEGER REFERENCES listing(id), sold_at TEXT NOT NULL, price REAL NOT NULL,
  ward_code TEXT, ptype TEXT, area_m2 REAL, source TEXT NOT NULL, url TEXT, confidence TEXT, notes TEXT);

-- infrastructure / zoning / large private projects that can move prices
CREATE TABLE IF NOT EXISTS project (
  id TEXT PRIMARY KEY, name_vi TEXT, name_en TEXT, kind TEXT,  -- road | bridge | university | river | estate | zoning | port | airport | other
  status TEXT,                    -- proposed | approved | under_construction | done | stalled | cancelled
  lat REAL, lng REAL, radius_km REAL, ward_codes TEXT, budget_vnd REAL,
  start_year INTEGER, done_year INTEGER, p_done REAL, uplift REAL, notes TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS project_evidence (
  id INTEGER PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(id), url TEXT NOT NULL, title TEXT,
  published TEXT, seen_at TEXT NOT NULL, claim TEXT);

-- what we own and operate
CREATE TABLE IF NOT EXISTS unit (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, ptype TEXT, ward_code TEXT, address TEXT, lat REAL, lng REAL, area_m2 REAL,
  bought_at TEXT, cost REAL, share REAL NOT NULL DEFAULT 1.0, loan REAL DEFAULT 0, loan_rate REAL, loan_term_years REAL,
  value REAL, value_at TEXT, legal TEXT, status TEXT DEFAULT 'held', listing_id INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS lease (
  id INTEGER PRIMARY KEY, unit_id TEXT NOT NULL REFERENCES unit(id), tenant TEXT, start TEXT NOT NULL, end TEXT,
  rent REAL NOT NULL, deposit REAL, due_day INTEGER DEFAULT 5, status TEXT DEFAULT 'active', notes TEXT);
CREATE TABLE IF NOT EXISTS txn (
  id INTEGER PRIMARY KEY, unit_id TEXT REFERENCES unit(id), lease_id INTEGER REFERENCES lease(id), at TEXT NOT NULL,
  amount REAL NOT NULL,           -- + money in, − money out
  category TEXT NOT NULL,         -- rent | deposit | repair | tax | fee | utility | loan_interest | loan_principal | purchase | sale | capex | other
  period TEXT, memo TEXT);

-- every valuation we publish, so it can be graded later (the calibration record)
CREATE TABLE IF NOT EXISTS valuation (
  id INTEGER PRIMARY KEY, subject TEXT NOT NULL,   -- 'listing:<id>' | 'unit:<id>' | 'lot:<name>'
  as_of TEXT NOT NULL, method TEXT NOT NULL, value REAL, lo REAL, hi REAL, n INTEGER, inputs TEXT, created_at TEXT NOT NULL);

-- paper deals: decisions recorded with their reasoning, graded later
CREATE TABLE IF NOT EXISTS deal (
  id INTEGER PRIMARY KEY, subject TEXT NOT NULL, opened_at TEXT NOT NULL, action TEXT NOT NULL,  -- buy | pass | sell | hold | build
  price REAL, est_value REAL, spec TEXT, verdict TEXT, review TEXT, closed_at TEXT, outcome TEXT);

-- saved searches re-run by the tracker
CREATE TABLE IF NOT EXISTS search (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, site TEXT NOT NULL, url TEXT NOT NULL, criteria TEXT, last_run TEXT);

CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT, body TEXT);

-- external and derived price series: a published area price chart, a research-house report, or our own index
CREATE TABLE IF NOT EXISTS price_series (
  id INTEGER PRIMARY KEY, source TEXT NOT NULL,     -- e.g. batdongsan-chart | guland-street | dkra-report | own-repeat | own-hedonic
  scope_kind TEXT NOT NULL,                         -- city | ward | old_district | street | project
  scope TEXT NOT NULL, ptype TEXT, kind TEXT NOT NULL DEFAULT 'asking',
  month TEXT NOT NULL,                              -- YYYY-MM
  value REAL NOT NULL, unit TEXT NOT NULL,          -- e.g. vnd_m2 | index
  url TEXT, seen_at TEXT NOT NULL, notes TEXT,
  UNIQUE (source, scope_kind, scope, ptype, kind, month, seen_at));

-- every forecast published, so it can be graded against what happened
CREATE TABLE IF NOT EXISTS forecast (
  id INTEGER PRIMARY KEY, subject TEXT NOT NULL,    -- 'series:<source>:<scope>:<ptype>' | 'listing:<id>' | 'unit:<id>'
  as_of TEXT NOT NULL, model TEXT NOT NULL, horizon_months INTEGER NOT NULL, target_month TEXT NOT NULL,
  p10 REAL, p50 REAL, p90 REAL, inputs TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_series ON price_series(scope_kind, scope, ptype, month);
CREATE INDEX IF NOT EXISTS ix_forecast ON forecast(subject, as_of);

CREATE INDEX IF NOT EXISTS ix_obs_listing ON listing_obs(listing_id, seen_at);
CREATE INDEX IF NOT EXISTS ix_listing_ward ON listing(ward_code, ptype);
CREATE INDEX IF NOT EXISTS ix_val_subject ON valuation(subject, as_of);
"""


def default_path() -> Path:
    return Path(os.environ.get("VNR_DB") or REPO / "data" / "vnr.sqlite")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (creating and migrating if needed). ``':memory:'`` is allowed for tests."""
    p = str(path) if path is not None else str(default_path())
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    con.commit()
    return con


def rows(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, sort_keys=True, default=str)
