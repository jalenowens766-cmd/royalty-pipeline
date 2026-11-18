-- Analysis queries for the royalty database.
-- Each query starts with a "-- name:" line so report.py can run them one by one.


-- name: catalog_summary
-- Headline numbers for the whole catalog.
SELECT
    COUNT(DISTINCT isrc)                          AS tracks,
    SUM(streams)                                  AS total_streams,
    ROUND(SUM(revenue_usd), 2)                    AS total_revenue_usd,
    ROUND(1000 * SUM(revenue_usd) / SUM(streams), 2) AS usd_per_1000_streams
FROM royalty_lines;


-- name: top_tracks
-- Top 10 earning tracks.
SELECT
    t.title,
    a.name                         AS artist,
    SUM(r.streams)                 AS streams,
    ROUND(SUM(r.revenue_usd), 2)   AS revenue_usd
FROM royalty_lines r
JOIN tracks  t ON t.isrc = r.isrc
JOIN artists a ON a.artist_id = t.artist_id
GROUP BY t.isrc
ORDER BY revenue_usd DESC
LIMIT 10;


-- name: revenue_by_platform
-- Which platforms pay the most in total and per stream.
SELECT
    platform,
    SUM(streams)                                      AS streams,
    ROUND(SUM(revenue_usd), 2)                        AS revenue_usd,
    ROUND(1000 * SUM(revenue_usd) / NULLIF(SUM(streams), 0), 2) AS usd_per_1000_streams
FROM royalty_lines
GROUP BY platform
ORDER BY revenue_usd DESC;


-- name: monthly_revenue_growth
-- Revenue per month and percent change from the previous month (window function).
WITH monthly AS (
    SELECT statement_month,
           SUM(revenue_usd) AS revenue_usd,
           SUM(streams)     AS streams
    FROM royalty_lines
    GROUP BY statement_month
)
SELECT
    statement_month,
    streams,
    ROUND(revenue_usd, 2) AS revenue_usd,
    ROUND(100.0 * (revenue_usd - LAG(revenue_usd) OVER (ORDER BY statement_month))
          / LAG(revenue_usd) OVER (ORDER BY statement_month), 1) AS mom_growth_pct
FROM monthly
ORDER BY statement_month;


-- name: artist_share
-- Each artist's revenue and share of the total catalog.
SELECT
    a.name                                              AS artist,
    ROUND(SUM(r.revenue_usd), 2)                        AS revenue_usd,
    ROUND(100.0 * SUM(r.revenue_usd) / SUM(SUM(r.revenue_usd)) OVER (), 1) AS pct_of_catalog
FROM royalty_lines r
JOIN tracks  t ON t.isrc = r.isrc
JOIN artists a ON a.artist_id = t.artist_id
GROUP BY a.artist_id
ORDER BY revenue_usd DESC;


-- name: top_countries
-- Where the money comes from.
SELECT
    country,
    SUM(streams)                                      AS streams,
    ROUND(SUM(revenue_usd), 2)                        AS revenue_usd,
    ROUND(1000 * SUM(revenue_usd) / NULLIF(SUM(streams), 0), 2) AS usd_per_1000_streams
FROM royalty_lines
GROUP BY country
ORDER BY revenue_usd DESC;


-- name: track_momentum
-- Streams in the first half vs second half of the year.
-- Growing tracks are worth more to a catalog buyer than fading ones.
WITH halves AS (
    SELECT
        r.isrc,
        SUM(CASE WHEN r.statement_month <= '2025-06' THEN r.streams ELSE 0 END) AS h1_streams,
        SUM(CASE WHEN r.statement_month >  '2025-06' THEN r.streams ELSE 0 END) AS h2_streams
    FROM royalty_lines r
    GROUP BY r.isrc
)
SELECT
    t.title,
    a.name AS artist,
    t.release_date,
    h.h1_streams,
    h.h2_streams,
    ROUND(100.0 * (h.h2_streams - h.h1_streams) / NULLIF(h.h1_streams, 0), 1) AS change_pct
FROM halves h
JOIN tracks  t ON t.isrc = h.isrc
JOIN artists a ON a.artist_id = t.artist_id
ORDER BY change_pct DESC;


-- name: missing_statements
-- Data quality check: months where a distributor sent nothing.
WITH months AS (SELECT DISTINCT statement_month FROM royalty_lines),
     dists  AS (SELECT DISTINCT distributor     FROM royalty_lines)
SELECT d.distributor, m.statement_month
FROM dists d
CROSS JOIN months m
LEFT JOIN royalty_lines r
       ON r.distributor = d.distributor
      AND r.statement_month = m.statement_month
GROUP BY d.distributor, m.statement_month
HAVING COUNT(r.id) = 0
ORDER BY d.distributor, m.statement_month;


-- name: negative_adjustments
-- Clawbacks and corrections that reduced revenue.
SELECT statement_month, distributor, isrc, platform, country,
       streams, ROUND(revenue_usd, 2) AS revenue_usd
FROM royalty_lines
WHERE revenue_usd < 0
ORDER BY revenue_usd;


-- name: etl_run_history
-- Audit log of pipeline runs.
SELECT run_at, files_read, files_skipped, rows_extracted, rows_loaded, rows_rejected
FROM etl_runs
ORDER BY run_id DESC
LIMIT 5;
