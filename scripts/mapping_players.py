"""
mapping_players.py
------------------
Builds the player ID mapping table between:
  - StatsBomb   (player_id)
  - SkillCorner (id)
  - Transfermarkt (id)

Matching by: normalized name + date of birth (exact then fuzzy)

OUTPUT
------
  data/raw/mapping/players_mapping.csv
"""

import csv
import json
import re
from pathlib import Path

from rapidfuzz import fuzz

from common import strip_accents_lower, write_csv_rows

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

SB_PLAYERS_JSON = ROOT / "data" / "raw" / "statsbomb"    / "players" / "ligue1_players_2025_2026.json"
SC_PLAYERS_JSON = ROOT / "data" / "raw" / "skillcorner"  / "players" / "ligue1_players_2025_2026.json"
TM_PLAYERS_CSV  = ROOT / "data" / "raw" / "transfermarkt" / "ligue1_players_2025_2026.csv"

OUTPUT_DIR = ROOT / "data" / "raw" / "mapping"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "players_mapping.csv"

FIELDNAMES = [
    "id",
    "sb_id",  "sb_name",  "sb_birth_date",
    "sc_id",  "sc_name",  "sc_birth_date",
    "tm_id",  "tm_name",  "tm_birth_date",
    "match_sb_sc", "match_sb_tm", "match_sc_tm",
]

# -----------------------------------------------------------------------------
# NORMALISATION
# -----------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Lowercase, strip accents, and drop everything but letters and spaces."""
    name = re.sub(r"[^a-z ]", "", strip_accents_lower(name))
    return " ".join(name.split())


def normalize_date(date_str: str) -> str:
    if not date_str:
        return ""
    date_str = str(date_str).strip()
    if re.match(r"\d{2}/\d{2}/\d{4}", date_str):
        d, m, y = date_str.split("/")
        return f"{y}-{m}-{d}"
    if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
        return date_str[:10]
    return date_str


# -----------------------------------------------------------------------------
# LOADERS
# -----------------------------------------------------------------------------

def load_statsbomb():
    with open(SB_PLAYERS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    players = []
    for p in data:
        players.append({
            "sb_id":         p["player_id"],
            "sb_name":       p.get("player_name", ""),
            "sb_birth_date": normalize_date(p.get("birth_date", "")),
            "_norm_name":    normalize_name(p.get("player_name", "")),
            "_norm_known":   normalize_name(p.get("player_known_name", "")),
        })
    return players


def load_skillcorner():
    with open(SC_PLAYERS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    players = []
    for p in data:
        full_name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        players.append({
            "sc_id":         p["id"],
            "sc_name":       p.get("short_name", full_name),
            "sc_birth_date": normalize_date(p.get("birthday", "")),
            "_norm_name":    normalize_name(full_name),
            "_norm_short":   normalize_name(p.get("short_name", "")),
        })
    return players


def load_transfermarkt():
    players = []
    with open(TM_PLAYERS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            players.append({
                "tm_id":         row["id"],
                "tm_name":       row["name"],
                "tm_birth_date": normalize_date(row.get("birth_date", "")),
                "_norm_name":    normalize_name(row["name"]),
            })
    return players


# -----------------------------------------------------------------------------
# MATCHING
# -----------------------------------------------------------------------------

def name_similarity(a: str, b: str) -> int:
    return max(
        fuzz.token_sort_ratio(a, b),
        fuzz.token_set_ratio(a, b)
    )


def match_players(source, target, source_key, target_key):
    exact_index = {}
    for p in target:
        key = (p["_norm_name"], p[f"{target_key}_birth_date"])
        if key not in exact_index:
            exact_index[key] = p

    date_index = {}
    for p in target:
        d = p[f"{target_key}_birth_date"]
        date_index.setdefault(d, []).append(p)

    matched = {}
    for p in source:
        sid   = p[f"{source_key}_id"]
        name  = p["_norm_name"]
        date  = p[f"{source_key}_birth_date"]
        known = p.get("_norm_known", "")

        # 1. Exact match (name + date)
        if (name, date) in exact_index:
            matched[sid] = (exact_index[(name, date)], "exact")
            continue

        # 2. Fuzzy name only >= 95
        best_score     = 0.0
        best_candidate = None
        for candidate in target:
            score = name_similarity(name, candidate["_norm_name"])
            if score > best_score:
                best_score     = score
                best_candidate = candidate
        if best_score >= 95 and best_candidate:
            matched[sid] = (best_candidate, "fuzzy_name")
            continue

        # 3. Fuzzy name + date: same date, threshold >= 45
        if date and date in date_index:
            best_score     = 0.0
            best_candidate = None
            for candidate in date_index[date]:
                score = name_similarity(name, candidate["_norm_name"])
                if score > best_score:
                    best_score     = score
                    best_candidate = candidate
            if best_score >= 45 and best_candidate:
                matched[sid] = (best_candidate, "fuzzy_date")
                continue

        # 4. Alias + date: same DOB, nickname variants >= 95
        if date and date in date_index:
            best_score     = 0.0
            best_candidate = None
            for candidate in date_index[date]:
                alias_scores = []
                if known:
                    alias_scores.append(name_similarity(known, candidate["_norm_name"]))
                tgt_short = candidate.get("_norm_short", "")
                if tgt_short:
                    alias_scores.append(name_similarity(name, tgt_short))
                if known and tgt_short:
                    alias_scores.append(name_similarity(known, tgt_short))
                if alias_scores:
                    score = max(alias_scores)
                    if score > best_score:
                        best_score, best_candidate = score, candidate
            if best_score >= 95 and best_candidate:
                matched[sid] = (best_candidate, "alias_date")

    return matched


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    sb_players = load_statsbomb()
    sc_players = load_skillcorner()
    tm_players = load_transfermarkt()

    sb_to_sc = match_players(sb_players, sc_players, "sb", "sc")
    sb_to_tm = match_players(sb_players, tm_players, "sb", "tm")
    sc_to_tm = match_players(sc_players, tm_players, "sc", "tm")

    print("Players per source:")
    print(f"  StatsBomb    : {len(sb_players)}")
    print(f"  SkillCorner  : {len(sc_players)}")
    print(f"  Transfermarkt: {len(tm_players)}")

    # Build rows
    rows    = []
    seen_sc = set()
    seen_tm = set()

    for sb in sb_players:
        sb_id  = sb["sb_id"]
        sc, _  = sb_to_sc.get(sb_id, (None, None))
        tm, _  = sb_to_tm.get(sb_id, (None, None))

        if sc:
            seen_sc.add(sc["sc_id"])
        if tm:
            seen_tm.add(tm["tm_id"])

        rows.append({
            "id":            len(rows) + 1,
            "sb_id":         sb_id,
            "sb_name":       sb["sb_name"],
            "sb_birth_date": sb["sb_birth_date"],
            "sc_id":         sc["sc_id"]         if sc else "",
            "sc_name":       sc["sc_name"]        if sc else "",
            "sc_birth_date": sc["sc_birth_date"]  if sc else "",
            "tm_id":         tm["tm_id"]          if tm else "",
            "tm_name":       tm["tm_name"]         if tm else "",
            "tm_birth_date": tm["tm_birth_date"]  if tm else "",
            "match_sb_sc":   "yes" if sc else "no",
            "match_sb_tm":   "yes" if tm else "no",
            "match_sc_tm":   "",
        })

    for sc in sc_players:
        if sc["sc_id"] in seen_sc:
            continue
        tm, _ = sc_to_tm.get(sc["sc_id"], (None, None))
        if tm:
            seen_tm.add(tm["tm_id"])
        rows.append({
            "id":            len(rows) + 1,
            "sb_id": "", "sb_name": "", "sb_birth_date": "",
            "sc_id":         sc["sc_id"],
            "sc_name":       sc["sc_name"],
            "sc_birth_date": sc["sc_birth_date"],
            "tm_id":         tm["tm_id"]          if tm else "",
            "tm_name":       tm["tm_name"]         if tm else "",
            "tm_birth_date": tm["tm_birth_date"]  if tm else "",
            "match_sb_sc": "no",
            "match_sb_tm": "no",
            "match_sc_tm": "yes" if tm else "no",
        })

    for tm in tm_players:
        if tm["tm_id"] in seen_tm:
            continue
        rows.append({
            "id":            len(rows) + 1,
            "sb_id": "", "sb_name": "", "sb_birth_date": "",
            "sc_id": "", "sc_name": "", "sc_birth_date": "",
            "tm_id":         tm["tm_id"],
            "tm_name":       tm["tm_name"],
            "tm_birth_date": tm["tm_birth_date"],
            "match_sb_sc": "no",
            "match_sb_tm": "no",
            "match_sc_tm": "no",
        })

    for row in rows:
        if row["match_sc_tm"] == "":
            row["match_sc_tm"] = "yes" if (row["sc_id"] and row["tm_id"]) else "no"

    write_csv_rows(OUTPUT_FILE, FIELDNAMES, rows)

    total      = len(rows)
    all_three  = sum(1 for r in rows if r["sb_id"] and r["sc_id"] and r["tm_id"])
    sb_sc_only = sum(1 for r in rows if r["sb_id"] and r["sc_id"] and not r["tm_id"])
    sb_tm_only = sum(1 for r in rows if r["sb_id"] and r["tm_id"] and not r["sc_id"])
    sb_only    = sum(1 for r in rows if r["sb_id"] and not r["sc_id"] and not r["tm_id"])
    sc_only    = sum(1 for r in rows if r["sc_id"] and not r["sb_id"] and not r["tm_id"])
    tm_only    = sum(1 for r in rows if r["tm_id"] and not r["sb_id"] and not r["sc_id"])

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total rows         : {total}")
    print(f"SB + SC + TM       : {all_three}")
    print(f"SB + SC only       : {sb_sc_only}")
    print(f"SB + TM only       : {sb_tm_only}")
    print(f"SB only            : {sb_only}")
    print(f"SC only            : {sc_only}")
    print(f"TM only            : {tm_only}")
    print(f"\nOutput: {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()