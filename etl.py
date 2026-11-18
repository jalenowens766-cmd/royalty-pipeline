"""
Royalty ETL pipeline.

Extract:   read monthly statements from three distributors, each in its own layout.
Transform: map every layout to one standard schema, clean values, convert all
           money to USD, and reject rows that fail validation.
Load:      write the clean rows into a SQLite database.

Usage:
    python etl.py
"""

import hashlib
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent
RAW_DIR = BASE / "data" / "raw"
REF_DIR = BASE / "data" / "reference"
OUT_DIR = BASE / "data" / "output"
DB_PATH = OUT_DIR / "royalties.db"
SCHEMA_PATH = BASE / "schema.sql"

log = logging.getLogger("etl")

# Every distributor format is converted to these columns
STANDARD_COLUMNS = ["statement_month", "isrc", "track_title", "platform", "country",
                    "streams", "amount", "currency", "distributor", "source_file"]

# One row per sale is identified by these fields
BUSINESS_KEY = ["statement_month", "isrc", "platform", "country", "distributor"]

PLATFORM_MAP = {
    "spotify": "Spotify",
    "apple music": "Apple Music", "apple_music": "Apple Music",
    "itunes/apple music": "Apple Music",
    "youtube": "YouTube Music", "youtube music": "YouTube Music",
    "amazon": "Amazon Music", "amazon music": "Amazon Music",
    "amazon unlimited": "Amazon Music",
    "tidal": "Tidal", "tidal hifi": "Tidal",
    "deezer": "Deezer",
}

COUNTRY_MAP = {
    "united states": "US", "united kingdom": "GB", "germany": "DE",
    "brazil": "BR", "nigeria": "NG", "japan": "JP",
}

# 2 letter country, 3 character registrant, 2 digit year, 5 digit designation
ISRC_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")


# ------------------------------------------------------------- cleaning helpers

def normalize_isrc(value) -> str | None:
    """'gb-qr1-21-00009' -> 'GBQR12100009'. Returns None if invalid."""
    if value is None or pd.isna(value):
        return None
    cleaned = re.sub(r"[\s-]", "", str(value)).upper()
    return cleaned if ISRC_PATTERN.match(cleaned) else None


def normalize_platform(value) -> str:
    """Map each distributor's spelling to one name. Unknown names become 'Other'."""
    if value is None or pd.isna(value):
        return "Other"
    return PLATFORM_MAP.get(str(value).strip().lower(), "Other")


def normalize_country(value) -> str | None:
    """Accept 2 letter codes or full names and return the 2 letter code."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if len(text) == 2 and text.isalpha():
        return text.upper()
    return COUNTRY_MAP.get(text.lower())


def parse_decimal_comma(value) -> float:
    """European number format: '1.234,56' -> 1234.56"""
    return float(str(value).strip().replace(".", "").replace(",", "."))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------- extract

def read_soundroute(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    return pd.DataFrame({
        "statement_month": pd.to_datetime(df["Reporting Month"], format="%Y-%m").dt.strftime("%Y-%m"),
        "isrc": df["ISRC"],
        "track_title": df["Track Title"],
        "platform": df["Store"],
        "country": df["Country"],
        "streams": df["Quantity"],
        "amount": pd.to_numeric(df["Earnings (USD)"], errors="coerce"),
        "currency": "USD",
    })


def read_tunevault(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", dtype=str)
    return pd.DataFrame({
        "statement_month": pd.to_datetime(df["period"], format="%m/%Y").dt.strftime("%Y-%m"),
        "isrc": df["isrc"],
        "track_title": df["song_name"],
        "platform": df["platform"],
        "country": df["territory"],
        "streams": df["streams"],
        "amount": df["net_revenue_eur"].map(parse_decimal_comma),
        "currency": "EUR",
    })


def read_indiewave(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    return pd.DataFrame({
        "statement_month": pd.to_datetime(df["Sale Date"], format="%d/%m/%Y").dt.strftime("%Y-%m"),
        "isrc": df["ISRC Code"],
        "track_title": df["Title"],
        "platform": df["Service"],
        "country": df["Country Code"],
        "streams": df["Units"],
        "amount": pd.to_numeric(df["Royalty"], errors="coerce"),
        "currency": df["Currency"].str.strip().str.upper(),
    })


# The file name prefix tells us which parser to use: soundroute_2025-01.csv
PARSERS = {
    "soundroute": read_soundroute,
    "tunevault": read_tunevault,
    "indiewave": read_indiewave,
}


def extract(raw_dir: Path) -> tuple[pd.DataFrame, dict]:
    frames, seen_hashes = [], {}
    stats = {"files_read": 0, "files_skipped": 0}

    for path in sorted(raw_dir.glob("*.csv")):
        distributor = path.stem.split("_")[0].lower()
        parser = PARSERS.get(distributor)
        if parser is None:
            log.warning("Skipping %s: no parser for distributor '%s'", path.name, distributor)
            stats["files_skipped"] += 1
            continue

        # Identical file contents mean the statement was sent twice
        digest = file_sha256(path)
        if digest in seen_hashes:
            log.warning("Skipping %s: identical to %s (duplicate statement)",
                        path.name, seen_hashes[digest])
            stats["files_skipped"] += 1
            continue
        seen_hashes[digest] = path.name

        df = parser(path)
        df["distributor"] = distributor
        df["source_file"] = path.name
        frames.append(df[STANDARD_COLUMNS])
        stats["files_read"] += 1

    if not frames:
        raise SystemExit(f"No statement files found in {raw_dir}. Run generate_sample_data.py first.")

    return pd.concat(frames, ignore_index=True), stats


# ------------------------------------------------------------- transform

def transform(raw: pd.DataFrame, valid_isrcs: set, fx: pd.DataFrame
              ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (clean rows ready to load, rejected rows with a reason)."""
    df = raw.copy()
    df["track_title"] = df["track_title"].astype(str).str.strip()
    df["isrc_raw"] = df["isrc"]
    df["isrc"] = df["isrc"].map(normalize_isrc)
    df["platform"] = df["platform"].map(normalize_platform)
    df["country"] = df["country"].map(normalize_country)
    df["streams"] = pd.to_numeric(df["streams"], errors="coerce")

    # Attach the exchange rate for each row's month and currency (USD = 1.0)
    df = df.merge(fx, how="left", left_on=["statement_month", "currency"],
                  right_on=["month", "currency"]).drop(columns="month")
    df.loc[df["currency"] == "USD", "usd_per_unit"] = 1.0

    # Validation: the first failed rule is recorded as the reason
    rules = [
        (df["isrc"].isna(), "missing or invalid ISRC"),
        (~df["isrc"].isin(valid_isrcs), "ISRC not in catalog"),
        (df["country"].isna(), "unknown country"),
        (df["streams"].isna() | (df["streams"] < 0), "invalid stream count"),
        (df["amount"].isna(), "invalid amount"),
        (df["usd_per_unit"].isna(), "no exchange rate for currency"),
    ]
    reason = pd.Series("", index=df.index, dtype=object)
    for failed, message in rules:
        reason[failed & (reason == "")] = message

    rejected = df[reason != ""].assign(reject_reason=reason[reason != ""])
    clean = df[reason == ""].copy()

    clean["revenue_usd"] = clean["amount"] * clean["usd_per_unit"]

    # Combine lines that share a key (for example a sale plus a clawback)
    clean = (clean.groupby(BUSINESS_KEY, as_index=False)
                  .agg(streams=("streams", "sum"),
                       revenue_usd=("revenue_usd", "sum"),
                       original_amount=("amount", "sum"),
                       original_currency=("currency", "first"),
                       source_file=("source_file", "first")))
    clean["streams"] = clean["streams"].astype(int)
    clean["revenue_usd"] = clean["revenue_usd"].round(6)

    rejected_cols = ["source_file", "distributor", "statement_month", "isrc_raw",
                     "track_title", "platform", "country", "streams", "amount",
                     "currency", "reject_reason"]
    return clean, rejected[rejected_cols]


# ------------------------------------------------------------- load

def load(clean: pd.DataFrame, catalog: pd.DataFrame, run_stats: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text())

        with conn:  # one transaction: everything loads or nothing does
            # Full refresh so running the pipeline twice never duplicates data
            conn.execute("DELETE FROM royalty_lines")
            conn.execute("DELETE FROM tracks")
            conn.execute("DELETE FROM artists")

            conn.executemany("INSERT INTO artists (name) VALUES (?)",
                             [(name,) for name in sorted(catalog["artist"].unique())])
            artist_ids = dict(conn.execute("SELECT name, artist_id FROM artists"))

            conn.executemany(
                "INSERT INTO tracks (isrc, title, artist_id, release_date) VALUES (?, ?, ?, ?)",
                [(r.isrc, r.title, artist_ids[r.artist], r.release_date)
                 for r in catalog.itertuples()])

            conn.executemany(
                """INSERT INTO royalty_lines
                   (statement_month, isrc, platform, country, streams, revenue_usd,
                    original_amount, original_currency, distributor, source_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                clean[["statement_month", "isrc", "platform", "country", "streams",
                       "revenue_usd", "original_amount", "original_currency",
                       "distributor", "source_file"]].itertuples(index=False, name=None))

            conn.execute(
                """INSERT INTO etl_runs (run_at, files_read, files_skipped,
                   rows_extracted, rows_loaded, rows_rejected) VALUES (?, ?, ?, ?, ?, ?)""",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 run_stats["files_read"], run_stats["files_skipped"],
                 run_stats["rows_extracted"], run_stats["rows_loaded"],
                 run_stats["rows_rejected"]))
    finally:
        conn.close()


# ------------------------------------------------------------- main

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    catalog = pd.read_csv(REF_DIR / "catalog.csv", dtype=str)
    fx = pd.read_csv(REF_DIR / "fx_rates.csv", dtype={"month": str, "currency": str})

    raw, stats = extract(RAW_DIR)
    log.info("Extracted %d rows from %d files", len(raw), stats["files_read"])

    clean, rejected = transform(raw, set(catalog["isrc"]), fx)
    log.info("Transformed into %d clean rows, rejected %d", len(clean), len(rejected))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rejected.to_csv(OUT_DIR / "rejected_rows.csv", index=False)
    for message, count in rejected["reject_reason"].value_counts().items():
        log.warning("  %d rows rejected: %s", count, message)

    stats.update(rows_extracted=len(raw), rows_loaded=len(clean), rows_rejected=len(rejected))
    load(clean, catalog, stats)
    log.info("Loaded into %s", DB_PATH.relative_to(BASE))
    log.info("Rejected rows saved to %s for review",
             (OUT_DIR / "rejected_rows.csv").relative_to(BASE))


if __name__ == "__main__":
    main()
