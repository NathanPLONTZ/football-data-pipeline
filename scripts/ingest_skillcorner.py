"""
ingest_skillcorner.py
─────────────────────
SkillCorner data ingestion — Ligue 1 2025/2026.

USAGE
─────
  Re-fetch everything:
      python ingest_skillcorner.py --all

  All players:
      python ingest_skillcorner.py --players

  Specific players (SkillCorner IDs):
      python ingest_skillcorner.py --players 14 18 202

  All matches (skip already downloaded):
      python ingest_skillcorner.py --matches

  Specific matches (force re-download):
      python ingest_skillcorner.py --matches 2038827 2038828

  Teams only:
      python ingest_skillcorner.py --teams

  Mix:
      python ingest_skillcorner.py --players 14 18 --matches 2038827

  Test mode (limit number of items):
      python ingest_skillcorner.py --all --limit 10

WHAT EACH ARGUMENT COVERS
──────────────────────────
  --players  -> players reference JSON + physical
               No IDs  : all players (overwrites existing files)
               With IDs: only those players (overwrites)

  --teams    -> teams reference JSON
               No IDs  : all teams

  --matches  -> matches reference JSON
               No IDs  : all matches, SKIP if file already exists
               With IDs: only those matches, FORCE re-download

  --all      -> equivalent to --players --teams --matches (no IDs)
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from skillcorner.client import SkillcornerClient

from common import api_get, print_section, print_separator, save_json

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()
USERNAME = os.getenv("SKILLCORNER_USERNAME")
PASSWORD = os.getenv("SKILLCORNER_PASSWORD")
AUTH     = (USERNAME, PASSWORD)

COMPETITION = {
    "area":      "FRA",
    "name":      "Ligue 1",
    "gender":    "male",
    "age_group": "adult",
    "season":    "2025/2026",
}

# Output directories
ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "raw" / "skillcorner"
DIR_PLAYERS  = DATA_DIR / "players"
DIR_TEAMS    = DATA_DIR / "teams"
DIR_MATCHES  = DATA_DIR / "matches"
DIR_PHYSICAL = DATA_DIR / "physical"

# Reference JSON files
PLAYERS_JSON = DIR_PLAYERS / "ligue1_players_2025_2026.json"
TEAMS_JSON   = DIR_TEAMS   / "ligue1_teams_2025_2026.json"
MATCHES_JSON = DIR_MATCHES / "ligue1_matches_2025_2026.json"


# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def create_dirs():
    for d in [DIR_PLAYERS, DIR_TEAMS, DIR_MATCHES, DIR_PHYSICAL]:
        d.mkdir(parents=True, exist_ok=True)


def safe_print(text):
    try:
        print(text, end=" ", flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), end=" ", flush=True)


def paginate(url, extra_params=None):
    """Fetches all pages from a paginated endpoint. Returns full list."""
    items, offset, limit = [], 0, 100
    params = {**(extra_params or {}), "limit": limit}
    while True:
        params["offset"] = offset
        data, status = api_get(url, AUTH, params)
        if status != 200:
            raise RuntimeError(f"API error {status} on {url}")
        items.extend(data["results"])
        print(f"   Fetched {len(items)}/{data['count']}...", end="\r", flush=True)
        if data["next"] is None:
            break
        offset += limit
    print()
    return items


# ─────────────────────────────────────────────────────────────────────────────
# EDITION RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

def resolve_edition(client):
    """Finds the edition_id matching the configured competition and season."""
    comps = client.get_competitions()
    comp  = next(
        (c for c in comps
         if c.get("area")       == COMPETITION["area"]
         and c.get("name")      == COMPETITION["name"]
         and c.get("gender")    == COMPETITION["gender"]
         and c.get("age_group") == COMPETITION["age_group"]),
        None
    )
    if not comp:
        raise RuntimeError("Competition not found — check COMPETITION config")

    editions = client.get_competition_competition_editions(
        competition_id=str(comp["id"])
    )
    edition = next(
        (e for e in editions
         if e.get("season", {}).get("name") == COMPETITION["season"]),
        None
    )
    if not edition:
        raise RuntimeError(f"Season {COMPETITION['season']} not found")

    print(f"[OK] Competition ID={comp['id']}  Edition ID={edition['id']}")
    return edition["id"]


# ─────────────────────────────────────────────────────────────────────────────
# REFERENCE DATA
# ─────────────────────────────────────────────────────────────────────────────

def refresh_players_ref(edition_id):
    print("\nFetching players reference list...")
    players = paginate(
        "https://skillcorner.com/api/players/",
        {"competition_edition": edition_id}
    )
    save_json(PLAYERS_JSON, players)
    print(f"[OK] {len(players)} players saved -> {PLAYERS_JSON}")
    return players


def refresh_teams_ref(edition_id):
    print("\nFetching teams reference list...")
    teams = paginate(
        "https://skillcorner.com/api/teams/",
        {"competition_edition": edition_id}
    )
    save_json(TEAMS_JSON, teams)
    print(f"[OK] {len(teams)} teams saved -> {TEAMS_JSON}")

    print("\nTEAMS LIST:")
    print_separator("-", 60)
    for i, t in enumerate(teams, 1):
        stadium = t.get("stadium", {})
        print(f"  {i:2}. {t.get('name')} (ID: {t.get('id')}) "
              f"— {stadium.get('name', 'N/A')}, {stadium.get('city', 'N/A')}")
    print_separator("-", 60)

    return teams


def refresh_matches_ref(edition_id):
    print("\nFetching matches reference list...")
    matches = paginate(
        "https://skillcorner.com/api/matches/",
        {"competition_edition": edition_id, "user": "true"}
    )
    save_json(MATCHES_JSON, matches)
    print(f"[OK] {len(matches)} matches saved -> {MATCHES_JSON}")
    return matches


# ─────────────────────────────────────────────────────────────────────────────
# PLAYER DATA FETCH
# ─────────────────────────────────────────────────────────────────────────────

PLAYER_ENDPOINTS = [
    {
        "name": "physical",
        "url":  "https://skillcorner.com/api/physical/",
        "dir":  DIR_PHYSICAL,
        "params": {
            "results": "win,lose,draw", "venue": "home,away",
            "period": "full", "possession": "all",
            "physical_check_passed": "true", "response_format": "json"
        }
    },
]


def _fetch_player_endpoint(player, ep, edition_id):
    """
    Fetch one endpoint for one player.
    Deletes the old file first (record count in filename may change).
    Returns the number of records saved, or "error" / "no_data".
    """
    pid    = player["id"]
    outdir = ep["dir"]

    # Remove old file for this player (filename encodes record count)
    for old in outdir.glob(f"player_{pid}_*"):
        old.unlink()

    data, status = api_get(
        ep["url"],
        AUTH,
        {**ep["params"], "player": pid, "competition_edition": edition_id},
    )

    if status != 200 or data is None:
        save_json(outdir / f"player_{pid}_0_records.json",
                  {"error": f"HTTP {status}", "player_id": pid})
        return "error"

    if (isinstance(data, list) and len(data) == 0) or \
       (isinstance(data, dict) and not data.get("results")):
        save_json(outdir / f"player_{pid}_0_records.json", data)
        return "no_data"

    n = len(data) if isinstance(data, list) else len(data.get("results", []))
    save_json(outdir / f"player_{pid}_{n}_records.json", data)
    return n


def fetch_players_data(players, edition_id):
    """Fetch all player endpoints for the given list of players."""
    ep_timings = {}

    for ep in PLAYER_ENDPOINTS:
        ep_start = time.time()
        print(f"\n\nFetching {ep['name'].upper()} data for {len(players)} players...")
        print_separator("=", 80)

        ok = no_data = errors = 0

        for i, player in enumerate(players):
            pid   = player["id"]
            pname = player.get("short_name", "?")
            safe_print(f"[{i+1}/{len(players)}] {pname} (ID: {pid})...")

            result = _fetch_player_endpoint(player, ep, edition_id)

            if result == "error":
                print("[ERROR]")
                errors += 1
            elif result == "no_data":
                print("[NO DATA]")
                no_data += 1
            else:
                print(f"[OK] {result} records saved")
                ok += 1

            time.sleep(0.2)

        ep_duration = time.time() - ep_start
        ep_timings[ep["name"]] = ep_duration

        print_separator("=", 80)
        print(f"\n{ep['name'].upper()} SUMMARY")
        print_separator("=", 80)
        print(f"Total players processed : {len(players)}")
        print(f"Success                 : {ok}")
        print(f"No data                 : {no_data}")
        print(f"Errors                  : {errors}")
        print(f"Output directory        : {ep['dir']}")
        print(f"Duration                : {ep_duration:.2f}s ({ep_duration/60:.2f} min)")
        print_separator("=", 80)

    return ep_timings


# ─────────────────────────────────────────────────────────────────────────────
# MATCH DATA FETCH
# ─────────────────────────────────────────────────────────────────────────────

def fetch_matches_data(matches, force=False):
    """Fetch match reference data for the given list of matches."""
    print(f"\nFetching match data for {len(matches)} matches...")
    print_separator("=", 80)

    ok = skip = errors = 0

    for i, match in enumerate(matches):
        mid  = match["id"]
        home = match.get("home_team", {}).get("short_name", "?")
        away = match.get("away_team", {}).get("short_name", "?")
        safe_print(f"[{i+1}/{len(matches)}] [{mid}] {home} vs {away}...")

        match_file = DIR_MATCHES / f"match_{mid}.json"

        if match_file.exists() and not force:
            print("[SKIP]")
            skip += 1
        else:
            data, status = api_get(f"https://skillcorner.com/api/match/{mid}/", AUTH)
            if status == 200 and data:
                save_json(match_file, data)
                print("[OK]")
                ok += 1
            else:
                print(f"[ERROR HTTP {status}]")
                errors += 1

        time.sleep(0.3)

    print_separator("=", 80)
    print("\nMATCHES SUMMARY")
    print_separator("=", 80)
    print(f"Total matches processed : {len(matches)}")
    print(f"Success                 : {ok}")
    print(f"Skipped                 : {skip}")
    print(f"Errors                  : {errors}")
    print(f"Output                  : {DIR_MATCHES}")
    print_separator("=", 80)


# ─────────────────────────────────────────────────────────────────────────────
# CLI ARGUMENTS
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="SkillCorner data ingestion — Ligue 1 2025/2026",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_skillcorner.py --all
  python ingest_skillcorner.py --players
  python ingest_skillcorner.py --players 14 18 202
  python ingest_skillcorner.py --matches
  python ingest_skillcorner.py --matches 2038827 2038828
  python ingest_skillcorner.py --teams
  python ingest_skillcorner.py --players 14 18 --matches 2038827
  python ingest_skillcorner.py --all --limit 10
        """
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Re-fetch players + teams + matches"
    )
    parser.add_argument(
        "--players",
        nargs="*",
        metavar="ID",
        help="Re-fetch player data. No ID = all players. With IDs = only those players."
    )
    parser.add_argument(
        "--teams",
        action="store_true",
        help="Re-fetch teams."
    )
    parser.add_argument(
        "--matches",
        nargs="*",
        metavar="ID",
        help="Re-fetch match data. No ID = skip existing files. With IDs = force re-download."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of players/matches to process (test mode)"
    )

    args = parser.parse_args()

    if not args.all and args.players is None and not args.teams and args.matches is None:
        parser.print_help()
        sys.exit(1)

    return args


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    create_dirs()
    args = parse_args()
    t_start = time.time()

    print_separator("=", 80)
    print("INGEST SKILLCORNER — Ligue 1 2025/2026")
    print_separator("=", 80)

    # Print what will run
    if args.all:
        print("Mode    : ALL (players + teams + matches)")
    else:
        parts = []
        if args.players is not None:
            parts.append(f"players {args.players if args.players else '(all)'}")
        if args.teams:
            parts.append("teams")
        if args.matches is not None:
            parts.append(f"matches {args.matches if args.matches else '(all)'}")
        print(f"Mode    : {' | '.join(parts)}")
    if args.limit:
        print(f"Limit   : {args.limit} (TEST MODE)")
    print_separator("=", 80)

    # Connect
    print("\nConnecting to SkillCorner...")
    client = SkillcornerClient(username=USERNAME, password=PASSWORD)
    print("[OK] Connected")
    edition_id = resolve_edition(client)

    step_timings = {}

    # ── PLAYERS ──────────────────────────────────────────────────────────────
    if args.all or args.players is not None:
        print_section("STEP: PLAYERS")
        t_step = time.time()

        all_players = refresh_players_ref(edition_id)

        if args.players:
            # Explicit IDs
            ids     = {int(x) for x in args.players}
            targets = [p for p in all_players if p["id"] in ids]
            missing = ids - {p["id"] for p in targets}
            if missing:
                print(f"[WARN] IDs not found in reference: {missing}")
            print(f"Targeting {len(targets)} specific player(s)")
        else:
            targets = all_players[:args.limit] if args.limit else all_players
            if args.limit:
                print(f"[TEST MODE] Limited to first {args.limit} players")

        ep_timings = fetch_players_data(targets, edition_id)
        step_timings["players"] = time.time() - t_step
        step_timings.update({f"players/{k}": v for k, v in ep_timings.items()})

    # ── TEAMS ─────────────────────────────────────────────────────────────────
    if args.all or args.teams:
        print_section("STEP: TEAMS")
        t_step = time.time()
        refresh_teams_ref(edition_id)
        step_timings["teams"] = time.time() - t_step

    # ── MATCHES ───────────────────────────────────────────────────────────────
    if args.all or args.matches is not None:
        print_section("STEP: MATCHES")
        t_step = time.time()

        all_matches = refresh_matches_ref(edition_id)

        if args.matches:
            # Explicit IDs -> force re-download
            ids     = {int(x) for x in args.matches}
            targets = [m for m in all_matches if m["id"] in ids]
            missing = ids - {m["id"] for m in targets}
            if missing:
                print(f"[WARN] Match IDs not found in reference: {missing}")
            print(f"Targeting {len(targets)} specific match(es) — forcing re-download")
            fetch_matches_data(targets, force=True)
        else:
            targets = all_matches[:args.limit] if args.limit else all_matches
            if args.limit:
                print(f"[TEST MODE] Limited to first {args.limit} matches")
            fetch_matches_data(targets, force=False)

        step_timings["matches"] = time.time() - t_step

    # ── FINAL SUMMARY ─────────────────────────────────────────────────────────
    total = time.time() - t_start

    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    print(f"  {'TOTAL':<30} {total:.2f}s  ({total/60:.2f} min)")
    for step, duration in step_timings.items():
        print(f"  {step:<30} {duration:.2f}s  ({duration/60:.2f} min)")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()