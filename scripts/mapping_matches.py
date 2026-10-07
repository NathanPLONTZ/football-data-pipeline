"""
mapping_matches.py
------------------
Builds the match ID mapping table between:
  - StatsBomb   (match_id)
  - SkillCorner (id)

Strategy:
  1. Load teams_mapping to convert sb_id <-> sc_id
  2. For each SB match, retrieve the sc_id of both teams
  3. Find the SC match with the same teams and date

OUTPUT
------
data/raw/mapping/matches_mapping.csv
"""

import csv
import json
from datetime import datetime
from pathlib import Path

from common import print_separator, write_csv_rows

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

SB_MATCHES_JSON   = ROOT / "data" / "raw" / "statsbomb"   / "matches" / "ligue1_matches_2025_2026.json"
SC_MATCHES_JSON   = ROOT / "data" / "raw" / "skillcorner" / "matches" / "ligue1_matches_2025_2026.json"
TEAMS_MAPPING_CSV = ROOT / "data" / "raw" / "mapping" / "teams_mapping.csv"

OUTPUT_DIR  = ROOT / "data" / "raw" / "mapping"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "matches_mapping.csv"

FIELDNAMES = ["id", "sb_id", "sc_id", "date"]

# -----------------------------------------------------------------------------
# LOADERS
# -----------------------------------------------------------------------------

def load_teams_mapping():
    """
    Read teams_mapping.csv once and return two lookups:
      - sb_id   -> sc_id
      - sb_name -> sb_id
    """
    sb_to_sc      = {}
    name_to_sb_id = {}
    with open(TEAMS_MAPPING_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sb_id = int(row["sb_id"])
            sb_to_sc[sb_id] = int(row["sc_id"])
            name_to_sb_id[row["sb_name"]] = sb_id
    print(f"[TEAMS] {len(sb_to_sc)} teams loaded")
    return sb_to_sc, name_to_sb_id


def load_statsbomb_matches():
    data = json.loads(SB_MATCHES_JSON.read_text(encoding="utf-8"))
    print(f"[SB] {len(data)} matches")
    return data


def load_skillcorner_matches():
    data = json.loads(SC_MATCHES_JSON.read_text(encoding="utf-8"))
    # Index: (home_sc_id, away_sc_id, date_str) -> match
    index = {}
    for m in data:
        date = datetime.fromisoformat(m["date_time"].replace("Z", "+00:00")).date()
        key  = (m["home_team"]["id"], m["away_team"]["id"], str(date))
        index[key] = m
    print(f"[SC] {len(data)} matches")
    return index


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    print_separator("=", 60)
    print("BUILD MATCHES MAPPING")
    print_separator("=", 60)

    sb_to_sc, name_to_sb_id = load_teams_mapping()
    sb_matches = load_statsbomb_matches()
    sc_index   = load_skillcorner_matches()

    rows      = []
    not_found = []

    for m in sb_matches:
        sb_match_id = m["match_id"]
        date        = m["match_date"]  # "YYYY-MM-DD"

        # Resolve each team name to its sb_id, then to its sc_id
        home_sc_id = sb_to_sc.get(name_to_sb_id.get(m["home_team"]))
        away_sc_id = sb_to_sc.get(name_to_sb_id.get(m["away_team"]))

        if home_sc_id is None or away_sc_id is None:
            not_found.append({
                "sb_id":  sb_match_id,
                "reason": f"unmapped team: {m['home_team']} / {m['away_team']}",
            })
            continue

        # Look up the SC match played by the same two teams on the same date
        sc_match = sc_index.get((home_sc_id, away_sc_id, date))

        if sc_match is None:
            not_found.append({
                "sb_id":  sb_match_id,
                "reason": f"match not found in SC: {m['home_team']} vs {m['away_team']} on {date}",
            })
            continue

        rows.append({
            "id":    len(rows) + 1,
            "sb_id": sb_match_id,
            "sc_id": sc_match["id"],
            "date":  date,
        })

    write_csv_rows(OUTPUT_FILE, FIELDNAMES, rows)

    # Display
    print(f"\n{'ID':<6} {'SB ID':<12} {'SC ID':<12} {'Date'}")
    print_separator("-", 44)
    for r in rows:
        print(f"{str(r['id']):<6} {str(r['sb_id']):<12} {str(r['sc_id']):<12} {r['date']}")

    print(f"\nMatches mapped   : {len(rows)}/{len(sb_matches)}")
    if not_found:
        print(f"Not found      : {len(not_found)}")
        for nf in not_found:
            print(f"  [SB {nf['sb_id']}] {nf['reason']}")

    print(f"\nOutput : {OUTPUT_FILE}")
    print_separator("=", 60)


if __name__ == "__main__":
    main()
