"""
Run the analysis queries in queries.sql and print each result as a table.

Usage:
    python report.py                  # run every query
    python report.py top_tracks       # run one query by name
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent
DB_PATH = BASE / "data" / "output" / "royalties.db"
QUERIES_PATH = BASE / "queries.sql"


def load_queries(path: Path) -> dict[str, str]:
    """Split queries.sql into {name: sql} using the '-- name:' markers."""
    queries, name, lines = {}, None, []
    for line in path.read_text().splitlines():
        if line.startswith("-- name:"):
            if name:
                queries[name] = "\n".join(lines).strip()
            name, lines = line.split(":", 1)[1].strip(), []
        elif name:
            lines.append(line)
    if name:
        queries[name] = "\n".join(lines).strip()
    return queries


def main() -> None:
    if not DB_PATH.exists():
        sys.exit("Database not found. Run: python etl.py")

    queries = load_queries(QUERIES_PATH)
    wanted = sys.argv[1:] or list(queries)

    pd.set_option("display.width", 140)
    with sqlite3.connect(DB_PATH) as conn:
        for name in wanted:
            if name not in queries:
                print(f"Unknown query '{name}'. Options: {', '.join(queries)}")
                continue
            result = pd.read_sql_query(queries[name], conn)
            print(f"\n=== {name} ===")
            print(result.to_string(index=False) if not result.empty else "(no rows)")


if __name__ == "__main__":
    main()
