import pandas as pd

from etl import (normalize_country, normalize_isrc, normalize_platform,
                 parse_decimal_comma, transform)


def test_isrc_removes_dashes_and_uppercases():
    assert normalize_isrc("gb-qr1-21-00009") == "GBQR12100009"


def test_isrc_rejects_bad_values():
    for bad in ["", "N/A", None, "TOOSHORT", float("nan")]:
        assert normalize_isrc(bad) is None


def test_platform_spellings_map_to_one_name():
    assert normalize_platform("  SPOTIFY ") == "Spotify"
    assert normalize_platform("Apple_Music") == "Apple Music"
    assert normalize_platform("itunes/apple music") == "Apple Music"
    assert normalize_platform("Napster") == "Other"


def test_country_names_and_codes():
    assert normalize_country("United Kingdom") == "GB"
    assert normalize_country("us") == "US"
    assert normalize_country("Atlantis") is None


def test_decimal_comma():
    assert parse_decimal_comma("0,1234") == 0.1234
    assert parse_decimal_comma("-1,50") == -1.5
    assert parse_decimal_comma("1.234,56") == 1234.56


def make_row(**overrides):
    row = {"statement_month": "2025-01", "isrc": "QZAB12300001", "track_title": "Song",
           "platform": "Spotify", "country": "US", "streams": "1000", "amount": 3.5,
           "currency": "USD", "distributor": "soundroute", "source_file": "f.csv"}
    row.update(overrides)
    return row


def test_transform_converts_currency_and_rejects_bad_rows():
    raw = pd.DataFrame([
        make_row(),
        make_row(country="GB", amount=10.0, currency="GBP"),
        make_row(isrc=""),                 # missing ISRC
        make_row(isrc="QZAB19999999"),     # not in catalog
    ])
    fx = pd.DataFrame({"month": ["2025-01"], "currency": ["GBP"], "usd_per_unit": [1.25]})

    clean, rejected = transform(raw, {"QZAB12300001"}, fx)

    assert len(clean) == 2
    assert len(rejected) == 2
    gb = clean[clean["country"] == "GB"].iloc[0]
    assert gb["revenue_usd"] == 12.5
    assert set(rejected["reject_reason"]) == {"missing or invalid ISRC", "ISRC not in catalog"}


def test_transform_combines_sale_and_clawback():
    raw = pd.DataFrame([make_row(amount=50.0), make_row(streams="0", amount=-20.0)])
    fx = pd.DataFrame(columns=["month", "currency", "usd_per_unit"])

    clean, _ = transform(raw, {"QZAB12300001"}, fx)

    assert len(clean) == 1
    assert clean.iloc[0]["revenue_usd"] == 30.0
    assert clean.iloc[0]["streams"] == 1000
