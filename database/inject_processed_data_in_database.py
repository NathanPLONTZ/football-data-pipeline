"""
inject_processed_data_in_database.py
------------------------------------
Injects all processed CSV files into the PostgreSQL database.

Empty values are inserted as NULL, tables are loaded in dependency order
(parents before children), and large files are inserted in batches to keep
memory usage flat.

USAGE
-----
  python database/inject_processed_data_in_database.py
"""

import csv
import sys
from pathlib import Path

from db_connection import get_connection

ROOT      = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
MAPPING   = ROOT / "data" / "raw" / "mapping"

BATCH_SIZE = 5000


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

def clean_float_int(value):
    """Convert "7.0" -> "7" to undo pandas float serialization of int columns."""
    if value is None:
        return None
    try:
        f = float(value)
        if f == int(f):
            return str(int(f))
    except (ValueError, TypeError):
        pass
    return value


def empty_to_none(value):
    """Convert empty strings and nan representations to None, stored as NULL."""
    if value in ("", "nan", "NaN", "None", "none"):
        return None
    return value


def load_csv(path):
    """Read a CSV and return (headers, rows) with empty values as None."""
    path = Path(path)
    if not path.exists():
        print("[SKIP] File not found: " + str(path))
        return None, None

    with open(path, encoding="utf-8") as f:
        reader  = csv.DictReader(f)
        headers = list(reader.fieldnames)
        rows    = [[clean_float_int(empty_to_none(row[h])) for h in headers] for row in reader]

    return headers, rows


def inject(cursor, table, headers, rows):
    """Insert rows in batches, quoting column names to allow reserved words."""
    if not rows:
        print("[SKIP] No rows for " + table)
        return

    cols         = ", ".join(f'"{h}"' for h in headers)
    placeholders = ", ".join(["%s"] * len(headers))
    sql          = (
        f'INSERT INTO {table} ({cols}) '
        f'VALUES ({placeholders}) '
        'ON CONFLICT DO NOTHING'
    )

    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        cursor.executemany(sql, batch)
        total += len(batch)
        print(f"  {table}: {total}/{len(rows)} rows inserted", end="\r")

    print(f"Injected {len(rows)} rows into {table}              ")


def drop_id_column(headers, rows):
    """Remove the 'id' column so the PostgreSQL SERIAL can generate it."""
    if "id" not in headers:
        return headers, rows
    idx     = headers.index("id")
    headers = [h for h in headers if h != "id"]
    rows    = [row[:idx] + row[idx + 1:] for row in rows]
    return headers, rows


# -----------------------------------------------------------------------------
# INJECTION
# -----------------------------------------------------------------------------

def run():
    conn   = get_connection()
    cursor = conn.cursor()

    try:
        # ── edition ───────────────────────────────────────────────────────────
        headers, rows = load_csv(PROCESSED / "edition.csv")
        if rows:
            inject(cursor, "edition", headers, rows)

        # ── teams ─────────────────────────────────────────────────────────────
        headers, rows = load_csv(PROCESSED / "teams.csv")
        if rows:
            inject(cursor, "teams", headers, rows)

        # ── teams_mapping ─────────────────────────────────────────────────────
        headers, rows = load_csv(MAPPING / "teams_mapping.csv")
        if rows:
            # Keep only the columns the table expects
            keep    = ["id", "sb_id", "sc_id", "tm_id"]
            indices = [headers.index(h) for h in keep if h in headers]
            headers = [headers[i] for i in indices]
            rows    = [[row[i] for i in indices] for row in rows]
            inject(cursor, "teams_mapping", headers, rows)

        # ── players ───────────────────────────────────────────────────────────
        headers, rows = load_csv(PROCESSED / "players.csv")
        if rows:
            inject(cursor, "players", headers, rows)

        # ── players_mapping ───────────────────────────────────────────────────
        headers, rows = load_csv(MAPPING / "players_mapping.csv")
        if rows:
            keep    = ["id", "sb_id", "sc_id", "tm_id"]
            indices = [headers.index(h) for h in keep if h in headers]
            headers = [headers[i] for i in indices]
            rows    = [[row[i] for i in indices] for row in rows]
            inject(cursor, "players_mapping", headers, rows)

        # ── matches ───────────────────────────────────────────────────────────
        headers, rows = load_csv(PROCESSED / "matches.csv")
        if rows:
            inject(cursor, "matches", headers, rows)

        # ── matches_mapping ───────────────────────────────────────────────────
        headers, rows = load_csv(MAPPING / "matches_mapping.csv")
        if rows:
            keep    = ["id", "sb_id", "sc_id"]
            indices = [headers.index(h) for h in keep if h in headers]
            headers = [headers[i] for i in indices]
            rows    = [[row[i] for i in indices] for row in rows]
            inject(cursor, "matches_mapping", headers, rows)

        # ── match_players ─────────────────────────────────────────────────────
        headers, rows = load_csv(PROCESSED / "match_players.csv")
        if rows:
            inject(cursor, "match_players", headers, rows)

        # ── events ────────────────────────────────────────────────────────────
        headers, rows = load_csv(PROCESSED / "events.csv")
        if rows:
            inject(cursor, "events", headers, rows)

        # ── events sub-tables ─────────────────────────────────────────────────
        for filename, table in [
            ("events_shot.csv",          "events_shot"),
            ("events_pass.csv",          "events_pass"),
            ("events_carry.csv",         "events_carry"),
            ("events_pressure.csv",      "events_pressure"),
            ("events_ball_recovery.csv", "events_ball_recovery"),
        ]:
            headers, rows = load_csv(PROCESSED / filename)
            if rows:
                inject(cursor, table, headers, rows)

        # ── physical ──────────────────────────────────────────────────────────
        headers, rows = load_csv(PROCESSED / "physical.csv")
        if rows:
            # Drop id column - PostgreSQL SERIAL generates it automatically
            headers, rows = drop_id_column(headers, rows)
            inject(cursor, "physical", headers, rows)

        conn.commit()
        print("\nAll data injected successfully.")

    except Exception as e:
        conn.rollback()
        print("\n[ERROR] Injection failed: " + str(e))
        sys.exit(1)

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    run()