# Music Royalty Data Pipeline

A Python and SQL pipeline that takes messy monthly royalty statements from several music distributors, cleans them into a single standard format, loads them into a SQLite database, and answers business questions with SQL.

## The problem

Artists and catalog owners get paid through distributors, and every distributor reports earnings differently:

| Distributor | Format quirks |
|---|---|
| SoundRoute | Comma separated, `YYYY-MM` months, USD |
| TuneVault | Semicolon separated, `MM/YYYY` months, EUR with decimal commas (`27,50`), full country names |
| IndieWave | Day level dates (`31/01/2025`), dashed and lowercase ISRCs, extra spaces in titles, GBP and USD mixed in one file |

Each one also spells platforms its own way: `SPOTIFY`, `spotify`, `itunes/apple music`, `Apple_Music`, `TIDAL`, `tidal hifi`, and so on. You can't answer a simple question like "which song earned the most?" until all of that is standardized.

## How it works

```
data/raw/*.csv ──► EXTRACT ──► TRANSFORM ──► LOAD ──► royalties.db ──► queries.sql
 (3 formats)       one parser   clean, validate,  SQLite              report.py
                   per format   convert to USD
                                      │
                                      └──► rejected_rows.csv (for review)
```

**Extract:** Each distributor has its own parser that maps its columns to one standard schema. Files are fingerprinted with SHA-256, so a statement sent twice is detected and skipped.

**Transform:**
- Normalizes ISRCs (`gb-qr1-21-00009` becomes `GBQR12100009`) and validates them against the official format
- Maps every platform spelling to one name and every country to its 2 letter code
- Converts EUR and GBP to USD using the exchange rate for that month
- Rejects bad rows with a reason instead of silently dropping them
- Combines sales and clawbacks that share the same key

**Load:** Writes artists, tracks, and royalty lines into SQLite inside a single transaction. Reruns do a full refresh, so running the pipeline twice never duplicates data. Every run is logged in an `etl_runs` audit table.

## Data quality problems handled

| Problem | How it's handled |
|---|---|
| Statement sent twice | Detected by file hash and skipped |
| Missing or malformed ISRC | Rejected and saved to `rejected_rows.csv` |
| ISRC not in the catalog | Rejected for review |
| Three currencies | Converted to USD with monthly FX rates |
| Inconsistent platform and country names | Mapped to standard values |
| Negative clawback lines | Kept and netted against sales |
| Distributor statement never arrived | Flagged by the `missing_statements` query |

## Database schema

```
artists (artist_id, name)
tracks (isrc, title, artist_id, release_date)
royalty_lines (statement_month, isrc, platform, country, streams,
               revenue_usd, original_amount, original_currency,
               distributor, source_file)
etl_runs (run_at, files_read, files_skipped, rows_extracted,
          rows_loaded, rows_rejected)
```

`royalty_lines` has a UNIQUE constraint on month, ISRC, platform, country, and distributor, and `source_file` keeps every number traceable back to the raw statement it came from.

## Setup

```bash
git clone https://github.com/jalenowens766-cmd/royalty-pipeline.git
cd royalty-pipeline
pip install -r requirements.txt

python generate_sample_data.py   # create sample statements
python etl.py                    # run the pipeline
python report.py                 # run all analysis queries
python report.py top_tracks      # or just one
python -m pytest                 # run the tests
```

## Sample output

```
WARNING Skipping indiewave_2025-06_resend.csv: identical to indiewave_2025-06.csv (duplicate statement)
INFO    Extracted 4611 rows from 35 files
INFO    Transformed into 4570 clean rows, rejected 41
WARNING   40 rows rejected: missing or invalid ISRC
WARNING   1 rows rejected: ISRC not in catalog

=== revenue_by_platform ===
     platform  streams  revenue_usd  usd_per_1000_streams
      Spotify  8109823     22556.92                  2.78
  Apple Music  2963772     16562.55                  5.59
 Amazon Music  1037175      3303.29                  3.18
        Tidal   446172      3192.31                  7.15
YouTube Music  1768185      2821.64                  1.60

=== missing_statements ===
distributor statement_month
  tunevault         2025-11
```

## Analysis queries (`queries.sql`)

- **catalog_summary:** total streams, revenue, and payout per 1,000 streams
- **top_tracks:** top 10 earning songs
- **revenue_by_platform:** total and per stream payout by platform
- **monthly_revenue_growth:** month over month growth using the `LAG` window function
- **artist_share:** each artist's percent of catalog revenue
- **top_countries:** revenue and payout rate by country
- **track_momentum:** first half vs second half streams, which spots growing and fading songs
- **missing_statements:** months where a distributor sent nothing
- **negative_adjustments:** clawbacks and corrections
- **etl_run_history:** pipeline audit log

## Findings from the sample data

- Spotify brings in the most money, but Apple Music pays about twice as much per stream.
- "Porch Light," a 2021 song, grew 87% in the second half of the year after going viral. Older songs normally lose listeners over time, so a catalog buyer would want to know about this.
- November revenue drops about 40%. The `missing_statements` check shows this is because TuneVault's statement never arrived, not because listening fell. Without that check, the drop could easily be misread as a real decline.

## Project structure

```
royalty-pipeline/
├── generate_sample_data.py   # creates messy sample statements
├── etl.py                    # extract, transform, load
├── schema.sql                # database tables
├── queries.sql               # analysis queries
├── report.py                 # runs the queries
├── tests/test_etl.py         # unit tests for the cleaning logic
├── data/
│   ├── raw/                  # distributor statements
│   ├── reference/            # catalog and exchange rates
│   └── output/               # database and rejected rows (not committed)
└── requirements.txt
```

All artists, songs, and distributors in this project are fictional.

## What I learned

- Designing one standard schema that many messy sources can map into
- Writing validation that rejects bad data visibly instead of hiding it
- Making a pipeline idempotent so it is safe to rerun
- SQL joins, CTEs, and window functions such as `LAG` and `SUM() OVER ()`
- Why data quality checks matter: a missing file can look exactly like a business problem

## Future improvements

- Incremental loads that process only new files instead of a full refresh
- Move from SQLite to PostgreSQL
- A Streamlit dashboard on top of the database
- Schedule monthly runs with Airflow or GitHub Actions
- Use the cleaned data to forecast future earnings and estimate a catalog's value
