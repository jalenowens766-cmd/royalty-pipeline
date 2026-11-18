-- Database schema for the royalty pipeline.
-- Raw files use many layouts; everything lands here in one standard shape.

CREATE TABLE IF NOT EXISTS artists (
    artist_id   INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS tracks (
    isrc          TEXT PRIMARY KEY,          -- International Standard Recording Code
    title         TEXT NOT NULL,
    artist_id     INTEGER NOT NULL REFERENCES artists(artist_id),
    release_date  TEXT
);

CREATE TABLE IF NOT EXISTS royalty_lines (
    id                 INTEGER PRIMARY KEY,
    statement_month    TEXT NOT NULL,        -- YYYY-MM
    isrc               TEXT NOT NULL REFERENCES tracks(isrc),
    platform           TEXT NOT NULL,
    country            TEXT NOT NULL,        -- ISO 2 letter code
    streams            INTEGER NOT NULL,
    revenue_usd        REAL NOT NULL,
    original_amount    REAL NOT NULL,        -- amount in the distributor's currency
    original_currency  TEXT NOT NULL,
    distributor        TEXT NOT NULL,
    source_file        TEXT NOT NULL,        -- which raw file this came from
    UNIQUE (statement_month, isrc, platform, country, distributor)
);

CREATE INDEX IF NOT EXISTS idx_lines_month ON royalty_lines(statement_month);
CREATE INDEX IF NOT EXISTS idx_lines_isrc  ON royalty_lines(isrc);

CREATE TABLE IF NOT EXISTS etl_runs (
    run_id         INTEGER PRIMARY KEY,
    run_at         TEXT NOT NULL,
    files_read     INTEGER NOT NULL,
    files_skipped  INTEGER NOT NULL,
    rows_extracted INTEGER NOT NULL,
    rows_loaded    INTEGER NOT NULL,
    rows_rejected  INTEGER NOT NULL
);
