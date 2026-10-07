"""
mapping_teams.py
----------------
Builds the team ID mapping table between:
  - StatsBomb   (team_id)
  - SkillCorner (id)
  - Transfermarkt (id + team name)

Strategy:
  1. SC <-> TM : bijective matching (Hungarian algorithm)
  2. SB <-> SC/TM pairs : bijective matching idem
  No stopwords — normalization only strips accents, casing and punctuation.

OUTPUT
------
data/raw/mapping/teams_mapping.csv
"""

import csv
import json
import re
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

from common import print_separator, strip_accents_lower, write_csv_rows

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

SB_TEAMS_JSON = ROOT / "data" / "raw" / "statsbomb"     / "teams" / "ligue1_teams_2025_2026.json"
SC_TEAMS_JSON = ROOT / "data" / "raw" / "skillcorner"   / "teams" / "ligue1_teams_2025_2026.json"
TM_TEAMS_CSV  = ROOT / "data" / "raw" / "transfermarkt" / "ligue1_teams_2025_2026.csv"

OUTPUT_DIR  = ROOT / "data" / "raw" / "mapping"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "teams_mapping.csv"

FIELDNAMES = [
    "id",
    "sb_id", "sb_name",
    "sc_id", "sc_name",
    "tm_id", "tm_name",
]

# -----------------------------------------------------------------------------
# NORMALISATION
# -----------------------------------------------------------------------------

def normalize_name(name):
    """Lowercase, strip accents, and replace punctuation with spaces."""
    name = re.sub(r"[^a-z0-9 ]", " ", strip_accents_lower(name))
    return " ".join(name.split())


# -----------------------------------------------------------------------------
# SCORE
# -----------------------------------------------------------------------------

def fuzzy_score(a, b):
    if not a or not b:
        return 0.0
    return round(
        0.40 * fuzz.token_set_ratio(a, b)
        + 0.35 * fuzz.token_sort_ratio(a, b)
        + 0.25 * fuzz.ratio(a, b),
        2,
    )


# -----------------------------------------------------------------------------
# BIJECTIVE MATCHING (Hungarian algorithm)
# -----------------------------------------------------------------------------

def bijective_match(sources, targets, score_fn):
    matrix = np.array([
        [score_fn(s["_norm"], t["_norm"]) for t in targets]
        for s in sources
    ])
    row_ind, col_ind = linear_sum_assignment(-matrix)
    return [
        (sources[r], targets[c], round(float(matrix[r, c]), 2))
        for r, c in zip(row_ind, col_ind)
    ]


# -----------------------------------------------------------------------------
# LOADERS
# -----------------------------------------------------------------------------

def load_statsbomb():
    with open(SB_TEAMS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    teams = [
        {"sb_id": t["team_id"], "sb_name": t["team_name"],
         "_norm": normalize_name(t["team_name"])}
        for t in data
    ]
    print(f"[SB] {len(teams)} teams loaded")
    return teams


def load_skillcorner():
    with open(SC_TEAMS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    teams = [
        {"sc_id": t["id"], "sc_name": t["name"],
         "_norm": normalize_name(t["name"])}
        for t in data
    ]
    print(f"[SC] {len(teams)} teams loaded")
    return teams


def load_transfermarkt():
    teams = []
    with open(TM_TEAMS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            teams.append({
                "tm_id":   row["id"],
                "tm_name": row["team"],
                "_norm":   normalize_name(row["team"]),
            })
    print(f"[TM] {len(teams)} teams loaded")
    return teams


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("BUILD TEAMS MAPPING")
    print("=" * 60)

    sb_teams = load_statsbomb()
    sc_teams = load_skillcorner()
    tm_teams = load_transfermarkt()

    # Step 1: SC - TM bijective matching
    sc_tm_matches = bijective_match(sc_teams, tm_teams, fuzzy_score)

    pairs = []
    for sc, tm, sc_tm_score in sc_tm_matches:
        pairs.append({
            "sc_id":   sc["sc_id"],
            "sc_name": sc["sc_name"],
            "tm_id":   tm["tm_id"],
            "tm_name": tm["tm_name"],
            "_norm":   sc["_norm"] + " " + tm["_norm"],
        })

    # Step 2: SB - SC/TM pairs bijective matching
    sb_pair_matches = bijective_match(sb_teams, pairs, fuzzy_score)

    rows = sorted([
        {
            "sb_id":   sb["sb_id"],
            "sb_name": sb["sb_name"],
            "sc_id":   pair["sc_id"],
            "sc_name": pair["sc_name"],
            "tm_id":   pair["tm_id"],
            "tm_name": pair["tm_name"],
        }
        for sb, pair, _ in sb_pair_matches
    ], key=lambda r: r["sb_id"])

    # Assign internal id starting from 1, after sorting by sb_id
    for i, row in enumerate(rows, start=1):
        row["id"] = i

    write_csv_rows(OUTPUT_FILE, FIELDNAMES, rows)

    # Display
    print(f"\n{'ID':>4}  {'SB Name':<25} {'SB ID':>6}  {'SC Name':<28}  {'SC ID':>6}  {'TM Name':<28}  {'TM ID':>6}")
    print_separator("-", 110)
    for r in rows:
        print(
            f"{str(r['id']):>4}  "
            f"{r['sb_name']:<25} {str(r['sb_id']):>6}  "
            f"{r['sc_name']:<28}  {str(r['sc_id']):>6}  "
            f"{r['tm_name']:<28}  {str(r['tm_id']):>6}"
        )

    print(f"\nOutput : {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()