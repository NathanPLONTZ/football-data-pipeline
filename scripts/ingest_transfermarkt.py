"""
ingest_transfermarkt.py
───────────────────────
Transfermarkt data ingestion — Ligue 1 2025.

USAGE
─────
  Re-fetch everything from scratch:
      python ingest_transfermarkt.py --all

  Teams only (deletes and recreates the file):
      python ingest_transfermarkt.py --teams

  All players (resumable — skips already scraped):
      python ingest_transfermarkt.py --players

  Update specific players by Transfermarkt ID (re-scrapes team pages to get fresh data):
      python ingest_transfermarkt.py --players 12345 67890

  Test mode:
      python ingest_transfermarkt.py --all --limit 5

WHAT EACH ARGUMENT COVERS
──────────────────────────
  --teams              -> Scrapes league page, extracts all clubs with details.
                         Deletes existing teams file and recreates it.

  --players            -> Step 1: scrapes player list (id, name, link) from all clubs.
                         Step 2: scrapes detailed stats for each player.
                         No IDs : resumable, skips already scraped players.
                         With IDs : re-scrapes team pages to find each player,
                                    then fetches fresh stats and updates the CSV.
                         NOTE: if the teams file is missing, --teams is run automatically first.

  --all                -> Deletes all files, then runs --teams then --players (full rescrape).
"""

import argparse
import csv
import random
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from common import print_section, print_separator, write_csv_rows

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

BASE_URL    = "https://www.transfermarkt.com"
LEAGUE_CODE = "FR1"
SEASON_ID   = 2025

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "raw" / "transfermarkt"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# File names in season_season+1 format
TEAMS_FILE   = DATA_DIR / f"ligue1_teams_{SEASON_ID}_{SEASON_ID + 1}.csv"
PLAYERS_FILE = DATA_DIR / f"ligue1_players_{SEASON_ID}_{SEASON_ID + 1}.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

REQUEST_TIMEOUT = 10
MAX_RETRIES     = 3

PLAYER_FIELDNAMES = [
    "id", "name", "link", "age", "birth_date", "birth_place",
    "nationalities", "height_cm", "current_club", "position",
    "shirt_number", "joined_date", "contract_end", "market_value_m",
    "matches", "goals", "assists", "minutes", "yellow_cards", "red_cards"
]

TEAMS_FIELDNAMES = [
    "id", "team", "link", "league", "season", "squad_size", "average_age",
    "national_team_players", "stadium_name", "stadium_capacity",
    "table_position", "years_in_league"
]


# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def random_delay(min_sec=1, max_sec=3):
    time.sleep(random.uniform(min_sec, max_sec))


def fetch_url(url) -> Optional[str]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"  [WARNING] Attempt {attempt} failed for {url}: {e}")
            time.sleep(1 + random.random() * 2)
    print(f"  [ERROR] Failed to fetch {url} after {MAX_RETRIES} attempts")
    return None


def extract_id(url: str) -> str:
    """Extracts the Transfermarkt ID from a /verein/ID/... URL"""
    m = re.search(r"/verein/(\d+)", url)
    return m.group(1) if m else ""


def convert_height_to_cm(height_str: str) -> int:
    if not height_str:
        return 0
    match = re.search(r"(\d+),(\d+)", height_str)
    if match:
        return int(match.group(1)) * 100 + int(match.group(2))
    return 0


def load_csv_as_dict(filepath, key_field) -> dict:
    """Load a CSV into a dict keyed by key_field."""
    result = {}
    if not filepath.exists():
        return result
    with open(filepath, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row[key_field]] = row
    return result


def append_to_csv(filepath, row, fieldnames):
    file_exists = filepath.exists()
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def get_team_links_from_csv() -> list:
    if not TEAMS_FILE.exists():
        raise FileNotFoundError(
            f"Teams file not found: {TEAMS_FILE}\n"
            "Run --teams first to generate it."
        )
    links = []
    with open(TEAMS_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            links.append(row["link"])
    return links


def ensure_teams_file():
    """
    If the teams file doesn't exist, automatically run --teams before continuing.
    """
    if not TEAMS_FILE.exists():
        print("[INFO] Teams file not found — running --teams automatically first...")
        print_separator("-", 80)
        run_teams()
        print_separator("-", 80)


# ─────────────────────────────────────────────────────────────────────────────
# TEAMS SCRAPING
# ─────────────────────────────────────────────────────────────────────────────

def scrape_teams() -> list:
    """Scrape all Ligue 1 teams with details. Returns list of team dicts."""
    url  = (f"{BASE_URL}/ligue-1/startseite/wettbewerb/{LEAGUE_CODE}"
            f"/plus/?saison_id={SEASON_ID}")
    html = fetch_url(url)
    if not html:
        raise RuntimeError("Failed to fetch league page")

    soup  = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="items")
    teams = []

    if not table:
        print("[WARN] No teams table found on league page")
        return teams

    for row in table.find("tbody").find_all("tr", recursive=False):
        link_cell = row.find("td", class_="zentriert no-border-rechts")
        if not (link_cell and link_cell.a):
            continue

        team_name = link_cell.a["title"]
        team_link = f"{BASE_URL}{link_cell.a['href']}"
        id        = extract_id(team_link)

        print(f"  Extracting details for {team_name} (id={id})...")
        details = _extract_team_details(team_link)

        teams.append({
            "id":                    id,
            "team":                  team_name,
            "link":                  team_link,
            "league":                LEAGUE_CODE,
            "season":                SEASON_ID,
            "squad_size":            details.get("squad_size", 0),
            "average_age":           details.get("average_age", 0.0),
            "national_team_players": details.get("national_team_players", 0),
            "stadium_name":          details.get("stadium_name", ""),
            "stadium_capacity":      details.get("stadium_capacity", 0),
            "table_position":        details.get("table_position", 0),
            "years_in_league":       details.get("years_in_league", 0),
        })
        random_delay(1, 2)

    return teams


def _extract_team_details(team_url: str) -> dict:
    html = fetch_url(team_url)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    data = {
        "squad_size": 0, "average_age": 0.0, "national_team_players": 0,
        "stadium_name": None, "stadium_capacity": 0,
        "table_position": 0, "years_in_league": 0
    }

    for item in soup.find_all("li", class_="data-header__label"):
        label   = item.get_text(strip=True)
        content = item.find("span", class_="data-header__content")
        if not content:
            continue

        if "Squad size:" in label:
            t = content.get_text(strip=True)
            if t.isdigit():
                data["squad_size"] = int(t)

        elif "Average age:" in label:
            try:
                data["average_age"] = float(content.get_text(strip=True))
            except ValueError:
                pass

        elif "National team players:" in label:
            lnk = content.find("a")
            if lnk and lnk.get_text(strip=True).isdigit():
                data["national_team_players"] = int(lnk.get_text(strip=True))

        elif "Stadium:" in label:
            lnk = content.find("a")
            if lnk:
                data["stadium_name"] = lnk.get_text(strip=True)
            cap = content.find("span", class_="tabellenplatz")
            if cap:
                m = re.search(r"([\d.,]+)\s+Seats", cap.get_text(strip=True))
                if m:
                    try:
                        data["stadium_capacity"] = int(
                            m.group(1).replace(".", "").replace(",", "")
                        )
                    except ValueError:
                        pass

    club_info = soup.find("div", class_="data-header__club-info")
    if club_info:
        for label in club_info.find_all("span", class_="data-header__label"):
            label_text = label.get_text(strip=True)
            content    = label.find("span", class_="data-header__content")
            if not content:
                continue
            if "Table position:" in label_text:
                lnk = content.find("a")
                if lnk and lnk.get_text(strip=True).isdigit():
                    data["table_position"] = int(lnk.get_text(strip=True))
            elif "In league since:" in label_text:
                lnk = content.find("a")
                if lnk:
                    m = re.search(r"(\d+)\s+year", lnk.get_text(strip=True))
                    if m:
                        data["years_in_league"] = int(m.group(1))

    return data


# ─────────────────────────────────────────────────────────────────────────────
# PLAYER LIST SCRAPING
# ─────────────────────────────────────────────────────────────────────────────

def get_all_player_stubs() -> list:
    """
    Scrape player stubs (id, name, link) from all club pages.
    Returns deduplicated list.
    """
    team_links  = get_team_links_from_csv()
    all_players = []
    seen_ids    = set()

    for team_url in team_links:
        print(f"  {team_url}")
        html = fetch_url(team_url)
        if not html:
            continue

        soup  = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="items")
        if not table:
            continue

        for row in table.find("tbody").find_all("tr", recursive=False):
            cell = row.find("td", class_="hauptlink")
            if not (cell and cell.a):
                continue
            href = cell.a["href"]
            pid  = href.split("/")[-1]
            if pid not in seen_ids:
                seen_ids.add(pid)
                all_players.append({
                    "name": cell.a.text.strip(),
                    "id":   pid,
                    "link": f"{BASE_URL}{href}",
                })

        random_delay(1, 2)

    return all_players


def find_players_in_teams(target_ids: List[str]) -> Dict[str, dict]:
    """
    Browse all team pages and collect fresh stubs (id, name, link)
    for the requested player IDs.
    Stops early once all players are found.
    Returns a dict {player_id: {"id": ..., "name": ..., "link": ...}}.
    """
    team_links = get_team_links_from_csv()
    remaining  = set(target_ids)
    found      = {}

    print(f"  Searching {len(target_ids)} player(s) across {len(team_links)} team pages...")
    print_separator("-", 80)

    for team_url in team_links:
        if not remaining:
            break  # all players found, stop early

        print(f"  Scanning {team_url} ...", end=" ")
        html = fetch_url(team_url)
        if not html:
            print("[FAILED]")
            continue

        soup  = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="items")
        if not table:
            print("[NO TABLE]")
            continue

        hits = 0
        for row in table.find("tbody").find_all("tr", recursive=False):
            cell = row.find("td", class_="hauptlink")
            if not (cell and cell.a):
                continue
            href = cell.a["href"]
            pid  = href.split("/")[-1]
            if pid in remaining:
                found[pid] = {
                    "id":   pid,
                    "name": cell.a.text.strip(),
                    "link": f"{BASE_URL}{href}",
                }
                remaining.discard(pid)
                hits += 1

        print(f"[{hits} hit(s)]")
        random_delay(1, 2)

    print_separator("-", 80)

    if remaining:
        print(f"[WARN] {len(remaining)} player(s) not found in any team page: {remaining}")

    return found


# ─────────────────────────────────────────────────────────────────────────────
# PLAYER DETAIL SCRAPING
# ─────────────────────────────────────────────────────────────────────────────

def _extract_player_stats(html: str, player_name: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "name": player_name, "age": 0, "birth_date": None, "birth_place": None,
        "nationalities": None, "height_cm": 0,
        "current_club": None, "position": None, "shirt_number": 0,
        "joined_date": None, "contract_end": None, "market_value_m": 0,
        "matches": 0, "goals": 0, "assists": 0,
        "minutes": 0, "yellow_cards": 0, "red_cards": 0,
    }

    span = soup.find("span", class_="data-header__shirt-number")
    if span:
        m = re.search(r"#(\d+)", span.get_text(strip=True))
        if m:
            data["shirt_number"] = int(m.group(1))

    for item in soup.find_all("li", class_="data-header__label"):
        label = item.get_text(strip=True)
        if "Date of birth" in label or "Age" in label:
            span = item.find("span", itemprop="birthDate")
            if span:
                m = re.search(r"(\d{2}/\d{2}/\d{4})\s*\((\d+)\)", span.get_text(strip=True))
                if m:
                    data["birth_date"] = m.group(1)
                    data["age"]        = int(m.group(2))
        elif "Place of birth" in label:
            span = item.find("span", itemprop="birthPlace")
            if span:
                data["birth_place"] = span.get_text(strip=True)
        elif "Citizenship" in label:
            span = item.find("span", itemprop="nationality")
            if span:
                data["nationalities"] = span.get_text(strip=True)
        elif "Height" in label:
            span = item.find("span", itemprop="height")
            if span:
                data["height_cm"] = convert_height_to_cm(span.get_text(strip=True))
        elif "Position" in label:
            span = item.find("span", class_="data-header__content")
            if span:
                data["position"] = span.get_text(strip=True)

    club_header = soup.find("span", class_="data-header__club")
    if club_header:
        lnk = club_header.find("a")
        if lnk:
            data["current_club"] = lnk.get_text(strip=True)

    for label in soup.find_all("span", class_="data-header__label"):
        text = label.get_text(strip=True)
        if "Joined:" in text:
            m = re.search(r"Joined:\s*(\d{2}/\d{2}/\d{4})", text)
            if m:
                data["joined_date"] = m.group(1)
        elif "Contract expires:" in text:
            m = re.search(r"Contract expires:\s*(\d{2}/\d{2}/\d{4})", text)
            if m:
                data["contract_end"] = m.group(1)

    mv_div = soup.find("div", class_="data-header__box--small")
    if mv_div:
        lnk = mv_div.find("a")
        if lnk:
            mv_text = lnk.get_text(strip=True)
            m = re.search(r"([\d.]+)\s*m", mv_text, re.IGNORECASE)
            if m:
                data["market_value_m"] = float(m.group(1))
            else:
                m = re.search(r"([\d.]+)\s*K", mv_text, re.IGNORECASE)
                if m:
                    data["market_value_m"] = float(m.group(1)) / 1000

    is_goalkeeper = data["position"] and "Goalkeeper" in data["position"]

    for table in soup.find_all("table", class_="items"):
        tfoot      = table.find("tfoot")
        footer_row = tfoot.find("tr") if tfoot else None

        if not footer_row:
            tbody = table.find("tbody")
            if tbody:
                footer_row = tbody.find("tr", class_="bg_blau_20")
                if not footer_row:
                    for row in tbody.find_all("tr"):
                        first = row.find("td")
                        if first and ("Insgesamt" in first.get_text(strip=True)
                                      or "Total" in first.get_text(strip=True)):
                            footer_row = row
                            break
                if not footer_row:
                    rows = (tbody.find_all("tr", class_="odd")
                            + tbody.find_all("tr", class_="even"))
                    if rows:
                        footer_row = rows[0]

        if not footer_row:
            continue

        cells    = footer_row.find_all("td")
        is_total = cells and ("Insgesamt" in cells[0].get_text(strip=True)
                              or "Total" in cells[0].get_text(strip=True))

        if len(cells) < 8:
            continue

        try:
            start = 0
            if is_total:
                for idx, cell in enumerate(cells):
                    if "hide" in cell.get("class", []):
                        start = idx + 1
                        break

            dc = cells[start:]

            if is_goalkeeper:
                if len(dc) >= 6:
                    if dc[0].get_text(strip=True).isdigit():
                        data["matches"]      = int(dc[0].get_text(strip=True))
                    if dc[1].get_text(strip=True).isdigit():
                        data["goals"]        = int(dc[1].get_text(strip=True))
                    data["assists"] = 0
                    if dc[2].get_text(strip=True).isdigit():
                        data["yellow_cards"] = int(dc[2].get_text(strip=True))
                    if len(dc) > 4 and dc[4].get_text(strip=True).isdigit():
                        data["red_cards"]    = int(dc[4].get_text(strip=True))
                    if len(dc) > 6:
                        mt = dc[-1].get_text(strip=True).replace("'", "").replace(".", "").replace(",", "").strip()
                        if mt.isdigit():
                            data["minutes"]  = int(mt)
            else:
                if len(dc) >= 6:
                    if dc[0].get_text(strip=True).isdigit():
                        data["matches"]      = int(dc[0].get_text(strip=True))
                    if dc[1].get_text(strip=True).isdigit():
                        data["goals"]        = int(dc[1].get_text(strip=True))
                    if dc[2].get_text(strip=True).isdigit():
                        data["assists"]      = int(dc[2].get_text(strip=True))
                    if dc[3].get_text(strip=True).isdigit():
                        data["yellow_cards"] = int(dc[3].get_text(strip=True))
                    if len(dc) > 5 and dc[5].get_text(strip=True).isdigit():
                        data["red_cards"]    = int(dc[5].get_text(strip=True))
                    if len(dc) > 6:
                        mt = dc[-1].get_text(strip=True).replace("'", "").replace(".", "").replace(",", "").strip()
                        if mt.isdigit():
                            data["minutes"]  = int(mt)
            break

        except Exception as e:
            print(f"    [ERROR] Stats extraction: {e}")
            continue

    return data


def scrape_player_details(player_id: str, player_name: str, profile_url: str) -> Optional[dict]:
    stats_url  = profile_url.replace("/profil/", "/leistungsdaten/")
    stats_html = fetch_url(stats_url)

    if not stats_html:
        print(f"  [FAILED] {player_name} ({player_id})")
        return None

    data         = _extract_player_stats(stats_html, player_name)
    data["id"]   = player_id
    data["link"] = profile_url
    return data


# ─────────────────────────────────────────────────────────────────────────────
# HIGH-LEVEL RUNNERS
# ─────────────────────────────────────────────────────────────────────────────

def run_teams():
    """Scrape teams — deletes existing file and recreates it."""
    print_section("STEP: TEAMS")
    t0 = time.time()

    if TEAMS_FILE.exists():
        TEAMS_FILE.unlink()
        print(f"Deleted existing file: {TEAMS_FILE}")

    teams = scrape_teams()
    write_csv_rows(TEAMS_FILE, TEAMS_FIELDNAMES, teams)

    elapsed = time.time() - t0
    print_separator("=", 80)
    print("TEAMS SUMMARY")
    print_separator("=", 80)
    print(f"Total teams scraped : {len(teams)}")
    print(f"Output              : {TEAMS_FILE}")
    print(f"Duration            : {elapsed:.2f}s ({elapsed/60:.2f} min)")
    print_separator("=", 80)


def run_players(player_ids=None, limit=None):
    """
    Scrape player data.
    - player_ids=None : resumable full scrape (skips already scraped)
    - player_ids=[...]: re-scrapes team pages to find fresh stubs for each ID,
                        then fetches stats and updates the CSV
    """
    print_section("STEP: PLAYERS")
    t0 = time.time()

    if player_ids:
        # ── UPDATE MODE: re-scrape team pages to find fresh player stubs ─────
        print(f"Targeting {len(player_ids)} specific player(s) — update mode")
        print("Browsing team pages to find fresh data for each player...")
        print_separator("-", 80)

        ensure_teams_file()

        # Browse all team pages to get fresh stubs for requested IDs
        fresh_stubs = find_players_in_teams(player_ids)

        if not fresh_stubs:
            print("\n[ABORT] No requested players found in any team page.")
            return

        # Load existing CSV (create empty structure if missing)
        existing = load_csv_as_dict(PLAYERS_FILE, "id") if PLAYERS_FILE.exists() else {}

        print(f"\nScraping detailed stats for {len(fresh_stubs)} found player(s)...")
        print_separator("-", 80)

        ok        = 0
        fail      = 0
        not_found_ids = set(player_ids) - set(fresh_stubs.keys())

        for i, (pid, stub) in enumerate(fresh_stubs.items(), 1):
            print(f"  [{i}/{len(fresh_stubs)}] {stub['name']} (ID: {pid})...", end=" ")
            data = scrape_player_details(stub["id"], stub["name"], stub["link"])
            if data:
                existing[pid] = {k: data.get(k, "") for k in PLAYER_FIELDNAMES}
                print("[OK - UPDATED]")
                ok += 1
            else:
                print("[FAILED]")
                fail += 1
            random_delay(2, 3)

        # Rewrite the full CSV with updated rows
        write_csv_rows(PLAYERS_FILE, PLAYER_FIELDNAMES, list(existing.values()))

        elapsed = time.time() - t0
        print_separator("=", 80)
        print("PLAYERS UPDATE SUMMARY")
        print_separator("=", 80)
        print(f"IDs requested          : {len(player_ids)}")
        print(f"  Found on team pages  : {len(fresh_stubs)}")
        print(f"  Not found            : {len(not_found_ids)}"
              + (f"  {not_found_ids}" if not_found_ids else ""))
        print(f"  Updated successfully : {ok}")
        print(f"  Failed               : {fail}")
        print(f"Output                 : {PLAYERS_FILE}")
        print(f"Duration               : {elapsed:.2f}s ({elapsed/60:.2f} min)")
        print_separator("=", 80)

    else:
        # ── FULL / RESUMABLE MODE ─────────────────────────────────────────────
        ensure_teams_file()

        already_scraped = set()
        if PLAYERS_FILE.exists():
            with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    already_scraped.add(row["id"])
            print(f"[INFO] {len(already_scraped)} players already scraped — will skip them")

        print("\nStep 1: Fetching player list from all clubs...")
        all_players = get_all_player_stubs()
        print(f"  {len(all_players)} players found")

        if limit:
            all_players = all_players[:limit]
            print(f"  [TEST MODE] Limited to first {limit} players")

        to_scrape = [p for p in all_players if p["id"] not in already_scraped]

        if not to_scrape:
            print(f"\n[INFO] All {len(all_players)} players are already scraped.")
            return

        print(f"\nStep 2: Scraping detailed stats for {len(to_scrape)} players...")
        print(f"  ({len(already_scraped)} already done, {len(to_scrape)} remaining)")
        print_separator("=", 80)

        ok = fail = 0
        for i, player in enumerate(to_scrape, 1):
            total_progress = len(already_scraped) + i
            print(f"  [{total_progress}/{len(all_players)}] {player['name']}...", end=" ")

            data = scrape_player_details(player["id"], player["name"], player["link"])
            if data:
                append_to_csv(PLAYERS_FILE, data, PLAYER_FIELDNAMES)
                print("[OK - SAVED]")
                ok += 1
            else:
                print("[FAILED]")
                fail += 1

            random_delay(2, 3)

        elapsed = time.time() - t0
        total_in_file = len(already_scraped) + ok

        print_separator("=", 80)
        print("PLAYERS SUMMARY")
        print_separator("=", 80)
        print(f"Total players in file : {total_in_file}")
        print(f"  Already scraped     : {len(already_scraped)}")
        print(f"  Newly scraped       : {ok}")
        print(f"  Failed              : {fail}")
        print(f"Output                : {PLAYERS_FILE}")
        print(f"Duration              : {elapsed:.2f}s ({elapsed/60:.2f} min)")
        print_separator("=", 80)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Transfermarkt data ingestion — Ligue 1 2025",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_transfermarkt.py --all
  python ingest_transfermarkt.py --teams
  python ingest_transfermarkt.py --players
  python ingest_transfermarkt.py --players 12345 67890
  python ingest_transfermarkt.py --all --limit 5
        """
    )

    parser.add_argument("--all", action="store_true",
        help="Delete all files and re-scrape everything (teams + players)")
    parser.add_argument("--teams", action="store_true",
        help="Re-scrape teams (deletes and recreates the file)")
    parser.add_argument("--players", nargs="*", metavar="ID",
        help="Re-scrape players. No ID: resumable. With IDs: update only those.")
    parser.add_argument("--limit", type=int, default=None,
        help="Max number of players to scrape (test mode)")

    args = parser.parse_args()

    if not args.all and not args.teams and args.players is None:
        parser.print_help()
        sys.exit(1)

    return args


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args    = parse_args()
    t_start = time.time()

    print_separator("=", 80)
    print("INGEST TRANSFERMARKT — Ligue 1 2025-2026")
    print_separator("=", 80)

    if args.all:
        print("Mode  : ALL (teams + players — full rescrape)")
    else:
        parts = []
        if args.teams:
            parts.append("teams")
        if args.players is not None:
            parts.append(f"players {args.players if args.players else '(all — resumable)'}")
        print(f"Mode  : {' | '.join(parts)}")

    if args.limit:
        print(f"Limit : {args.limit} (TEST MODE)")
    print_separator("=", 80)

    if args.all:
        for f in [TEAMS_FILE, PLAYERS_FILE]:
            if f.exists():
                f.unlink()
                print(f"Deleted: {f}")
        run_teams()
        run_players(limit=args.limit)

    else:
        if args.teams:
            run_teams()
        if args.players is not None:
            if args.players:
                run_players(player_ids=args.players, limit=args.limit)
            else:
                run_players(limit=args.limit)

    total = time.time() - t_start
    print("\n" + "=" * 80)
    print(f"  DONE — Total duration: {total:.2f}s ({total/60:.2f} min)")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()