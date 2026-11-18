"""
Generate fake monthly royalty statements from three fictional distributors.

Real royalty data arrives from many distributors, each using its own file
layout, column names, date formats, currencies, and platform spellings.
This script recreates that problem so the ETL pipeline has something
realistic to clean. Every artist, track, and company here is made up.

Usage:
    python generate_sample_data.py
"""

import calendar
import csv
import random
import shutil
from datetime import date
from pathlib import Path

random.seed(42)  # same "random" data every run, so results are reproducible

BASE = Path(__file__).parent / "data"
RAW = BASE / "raw"
REF = BASE / "reference"

# isrc, title, artist, release date, distributor that delivers it
CATALOG = [
    ("QZAB12300001", "Midnight Drive",   "Nova Reyes",      "2023-03-10", "soundroute"),
    ("QZAB12300002", "Glass Houses",     "Nova Reyes",      "2023-03-10", "soundroute"),
    ("QZAB12400003", "Static Hearts",    "Nova Reyes",      "2024-06-21", "soundroute"),
    ("QZAB12500004", "Run It Back",      "Nova Reyes",      "2025-02-14", "soundroute"),
    ("DEXY12200005", "Northern Lines",   "Kai Lindqvist",   "2022-09-02", "tunevault"),
    ("DEXY12300006", "Paper Satellites", "Kai Lindqvist",   "2023-11-17", "tunevault"),
    ("DEXY12400007", "Slow Bloom",       "Kai Lindqvist",   "2024-04-05", "tunevault"),
    ("DEXY12500008", "Afterglow City",   "Kai Lindqvist",   "2025-05-23", "tunevault"),
    ("GBQR12100009", "Porch Light",      "The Late Shifts", "2021-07-30", "indiewave"),
    ("GBQR12300010", "Overtime",         "The Late Shifts", "2023-01-13", "indiewave"),
    ("GBQR12400011", "Last Train Home",  "The Late Shifts", "2024-10-11", "indiewave"),
    ("GBQR12500012", "Bright Static",    "The Late Shifts", "2025-08-08", "indiewave"),
]

MONTHS = [date(2025, m, 1) for m in range(1, 13)]

PLATFORM_SHARE = {"Spotify": 0.55, "Apple Music": 0.20, "YouTube Music": 0.12,
                  "Amazon Music": 0.07, "Tidal": 0.03, "Deezer": 0.03}
PER_STREAM_USD = {"Spotify": 0.0035, "Apple Music": 0.0070, "YouTube Music": 0.0020,
                  "Amazon Music": 0.0040, "Tidal": 0.0090, "Deezer": 0.0030}
COUNTRY_SHARE = {"US": 0.40, "GB": 0.15, "DE": 0.12, "BR": 0.13, "NG": 0.10, "JP": 0.10}
COUNTRY_RATE_FACTOR = {"US": 1.0, "GB": 0.9, "DE": 0.85, "BR": 0.35, "NG": 0.25, "JP": 0.9}
COUNTRY_NAMES = {"US": "United States", "GB": "United Kingdom", "DE": "Germany",
                 "BR": "Brazil", "NG": "Nigeria", "JP": "Japan"}

# Each distributor spells platform names differently
SOUNDROUTE_STORES = {"Spotify": "Spotify", "Apple Music": "Apple Music",
                     "YouTube Music": "YouTube Music", "Amazon Music": "Amazon Music",
                     "Tidal": "TIDAL", "Deezer": "Deezer"}
TUNEVAULT_PLATFORMS = {"Spotify": "spotify", "Apple Music": "itunes/apple music",
                       "YouTube Music": "youtube", "Amazon Music": "amazon unlimited",
                       "Tidal": "tidal hifi", "Deezer": "deezer"}
INDIEWAVE_SERVICES = {"Spotify": "SPOTIFY", "Apple Music": "Apple_Music",
                      "YouTube Music": "YouTube", "Amazon Music": "Amazon",
                      "Tidal": "Tidal", "Deezer": "Deezer"}

# An old song goes viral on social media in July through September
VIRAL_BOOST = {("GBQR12100009", 7): 4.0, ("GBQR12100009", 8): 3.0, ("GBQR12100009", 9): 2.0}


def months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def make_fx_rates() -> dict:
    """USD value of one EUR or GBP for each month."""
    rates = {}
    for month in MONTHS:
        key = f"{month:%Y-%m}"
        rates[(key, "EUR")] = round(1.08 + random.uniform(-0.03, 0.03), 4)
        rates[(key, "GBP")] = round(1.27 + random.uniform(-0.03, 0.03), 4)
    return rates


def build_true_lines() -> list[dict]:
    """The 'real' earnings in USD, before any distributor formats them."""
    peaks = {row[0]: random.randint(150_000, 800_000) for row in CATALOG}
    lines = []
    for isrc, title, _artist, release, dist in CATALOG:
        released = date.fromisoformat(release)
        for month in MONTHS:
            age = months_between(released, month)
            if age < 0:
                continue  # not released yet
            # Streams are highest at release and decay over time
            total = (peaks[isrc] * (age + 1) ** -0.6
                     * VIRAL_BOOST.get((isrc, month.month), 1.0)
                     * random.uniform(0.9, 1.1))
            for platform, p_share in PLATFORM_SHARE.items():
                for country, c_share in COUNTRY_SHARE.items():
                    streams = int(total * p_share * c_share * random.uniform(0.85, 1.15))
                    if streams == 0:
                        continue
                    usd = (streams * PER_STREAM_USD[platform]
                           * COUNTRY_RATE_FACTOR[country] * random.uniform(0.95, 1.05))
                    lines.append({"dist": dist, "month": month, "isrc": isrc, "title": title,
                                  "platform": platform, "country": country,
                                  "streams": streams, "usd": usd})
    return lines


def add_problems(rows: list[dict], dist: str, month: date) -> list[dict]:
    """Inject the kinds of errors real statements contain."""
    rows = [dict(r) for r in rows]
    for r in rows:
        if random.random() < 0.01:
            r["isrc"] = ""  # missing identifier
    if dist == "soundroute" and month.month == 4:
        # A clawback: money taken back for an earlier overpayment
        rows.append({**rows[0], "platform": "Spotify", "country": "CA",
                     "isrc": "QZAB12300001", "title": "Midnight Drive",
                     "streams": 0, "usd": -25.0})
    if dist == "indiewave" and month.month == 3:
        rows.append({**rows[0], "isrc": "GBQR12599999", "title": "Unknown Demo"})
    if dist == "tunevault" and month.month == 9:
        rows.append({**rows[0], "isrc": "N/A"})
    return rows


def format_isrc_messy(isrc: str) -> str:
    if not isrc or len(isrc) != 12:
        return isrc
    dashed = f"{isrc[:2]}-{isrc[2:5]}-{isrc[5:7]}-{isrc[7:]}"
    return dashed.lower() if random.random() < 0.3 else dashed


def write_soundroute(month, rows, fx):
    path = RAW / f"soundroute_{month:%Y-%m}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Reporting Month", "Track Title", "ISRC", "Store",
                    "Country", "Quantity", "Earnings (USD)"])
        for r in rows:
            w.writerow([f"{month:%Y-%m}", r["title"], r["isrc"],
                        SOUNDROUTE_STORES[r["platform"]], r["country"],
                        r["streams"], f"{r['usd']:.6f}"])


def write_tunevault(month, rows, fx):
    """European style: semicolons, MM/YYYY dates, EUR with decimal commas."""
    path = RAW / f"tunevault_{month:%Y-%m}.csv"
    eur_rate = fx[(f"{month:%Y-%m}", "EUR")]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["period", "song_name", "isrc", "platform", "territory",
                    "streams", "net_revenue_eur"])
        for r in rows:
            eur = f"{r['usd'] / eur_rate:.6f}".replace(".", ",")
            w.writerow([f"{month:%m/%Y}", r["title"], r["isrc"],
                        TUNEVAULT_PLATFORMS[r["platform"]],
                        COUNTRY_NAMES[r["country"]], r["streams"], eur])


def write_indiewave(month, rows, fx):
    """Day level dates, dashed ISRCs, stray spaces, and mixed currencies."""
    path = RAW / f"indiewave_{month:%Y-%m}.csv"
    gbp_rate = fx[(f"{month:%Y-%m}", "GBP")]
    last_day = calendar.monthrange(month.year, month.month)[1]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Sale Date", "Title", "ISRC Code", "Service",
                    "Country Code", "Units", "Royalty", "Currency"])
        for r in rows:
            if r["country"] == "GB":
                amount, currency = r["usd"] / gbp_rate, "GBP"
            else:
                amount, currency = r["usd"], "USD"
            title = r["title"] + ("  " if random.random() < 0.2 else "")
            w.writerow([f"{last_day:02d}/{month:%m/%Y}", title,
                        format_isrc_messy(r["isrc"]),
                        INDIEWAVE_SERVICES[r["platform"]], r["country"],
                        r["streams"], f"{amount:.6f}", currency])


WRITERS = {"soundroute": write_soundroute, "tunevault": write_tunevault,
           "indiewave": write_indiewave}


def main() -> None:
    if RAW.exists():
        shutil.rmtree(RAW)
    RAW.mkdir(parents=True)
    REF.mkdir(parents=True, exist_ok=True)

    fx = make_fx_rates()
    lines = build_true_lines()

    files = 0
    for dist, writer in WRITERS.items():
        for month in MONTHS:
            if dist == "tunevault" and month.month == 11:
                continue  # this statement is "late" and never arrived
            rows = [l for l in lines if l["dist"] == dist and l["month"] == month]
            if rows:
                writer(month, add_problems(rows, dist, month), fx)
                files += 1

    # IndieWave accidentally sends its June statement twice
    shutil.copy(RAW / "indiewave_2025-06.csv", RAW / "indiewave_2025-06_resend.csv")
    files += 1

    with (REF / "catalog.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["isrc", "title", "artist", "release_date"])
        for isrc, title, artist, release, _ in CATALOG:
            w.writerow([isrc, title, artist, release])

    with (REF / "fx_rates.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "currency", "usd_per_unit"])
        for (month, currency), rate in sorted(fx.items()):
            w.writerow([month, currency, rate])

    print(f"Wrote {files} statement files to {RAW}")
    print(f"Wrote catalog and FX rates to {REF}")


if __name__ == "__main__":
    main()
