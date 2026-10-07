"""
process_data.py
---------------
Entry point for all data processing tasks.
Each entity (teams, players, matches, ...) has its own dedicated function.
Run this script to regenerate all processed CSV files used as database tables.
"""

import json
import os

import pandas as pd


# Project root is one level above the scripts folder
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

RAW       = os.path.join(ROOT, "data", "raw")
PROCESSED = os.path.join(ROOT, "data", "processed")


# ============================================================
# HELPERS
# ============================================================

def load_json(path):
    # Load a JSON file and always return a list
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def save_csv(df, filename):
    # Save a dataframe to data/processed/<filename>.csv
    os.makedirs(PROCESSED, exist_ok=True)
    output_path = os.path.join(PROCESSED, filename + ".csv")
    df.to_csv(output_path, index=False, encoding="utf-8")
    print("Created " + output_path)


# ============================================================
# EDITION
# ============================================================

# Single edition for this project - used as a constant across all tables
EDITION_ID = 1

def process_edition():
    # Static table with one row representing the competition edition
    df = pd.DataFrame([{
        "id":          EDITION_ID,
        "competition": "Ligue 1",
        "season":      "2025/2026",
    }])
    save_csv(df, "edition")


# ============================================================
# TEAMS
# ============================================================

def load_teams_skillcorner():
    # Extract stadium city for each team
    path = os.path.join(RAW, "skillcorner", "teams", "ligue1_teams_2025_2026.json")
    rows = []
    for team in load_json(path):
        city = team.get("stadium", {}).get("city") if team.get("stadium") else None
        rows.append({"sc_id": team["id"], "city": city})
    return pd.DataFrame(rows).drop_duplicates("sc_id")


def load_teams_statsbomb():
    # Extract season metadata and all team_season_* statistics
    path = os.path.join(RAW, "statsbomb", "teams", "ligue1_teams_2025_2026.json")
    meta_fields = ["competition_name", "season_name", "team_female"]
    rows = []
    for team in load_json(path):
        row = {"sb_id": team.get("team_id") or team.get("id")}
        for field in meta_fields:
            row[field] = team.get(field)
        for key, value in team.items():
            if key.startswith("team_season_"):
                row[key] = value
        rows.append(row)
    return pd.DataFrame(rows).drop_duplicates("sb_id")


def load_teams_transfermarkt():
    # Extract club info columns
    path = os.path.join(RAW, "transfermarkt", "ligue1_teams_2025_2026.csv")
    keep = [
        "id", "team", "squad_size", "average_age", "national_team_players",
        "stadium_name", "stadium_capacity", "table_position", "years_in_league",
    ]
    df = pd.read_csv(path, usecols=lambda c: c in keep)
    return df.rename(columns={"id": "tm_id"}).drop_duplicates("tm_id")


def process_teams():
    mapping = pd.read_csv(os.path.join(RAW, "mapping", "teams_mapping.csv"))

    result = mapping.copy()
    result = result.merge(load_teams_statsbomb(),    on="sb_id", how="left")
    result = result.merge(load_teams_skillcorner(),  on="sc_id", how="left")
    result = result.merge(load_teams_transfermarkt(), on="tm_id", how="left")

    # Remove all source IDs and source name columns (handled by the mapping table)
    source_cols = ["sb_id", "sb_name", "sc_id", "sc_name", "tm_id", "tm_name"]
    result = result.drop(columns=[c for c in source_cols if c in result.columns])

    # Replace competition_name and season_name with edition_id
    result["edition_id"] = EDITION_ID
    result = result.drop(columns=[c for c in ["competition_name", "season_name"] if c in result.columns])

    # Put descriptive columns first, then all stats at the end
    identity_cols = [
        "id", "team", "edition_id", "team_female",
        "city", "stadium_name", "stadium_capacity",
        "squad_size", "average_age", "national_team_players",
        "table_position", "years_in_league",
    ]
    identity_cols = [c for c in identity_cols if c in result.columns]
    stat_cols = sorted([c for c in result.columns if c not in identity_cols])
    result = result[identity_cols + stat_cols]

    save_csv(result, "teams")


# ============================================================
# PLAYERS
# ============================================================

def load_players_transfermarkt():
    # Extract player info columns from Transfermarkt
    path = os.path.join(RAW, "transfermarkt", "ligue1_players_2025_2026.csv")
    keep = [
        "id", "age", "birth_place", "nationalities",
        "shirt_number", "joined_date", "contract_end", "market_value_m",
        "matches", "goals", "assists", "minutes", "yellow_cards", "red_cards",
    ]
    df = pd.read_csv(path, usecols=lambda c: c in keep)
    return df.rename(columns={"id": "tm_id"}).drop_duplicates("tm_id")


def load_players_statsbomb(teams_mapping):
    # Extract player name, team reference, season metadata and all player_season_* stats
    # teams_mapping is used to resolve the StatsBomb team_id into our internal team id
    path = os.path.join(RAW, "statsbomb", "players", "ligue1_players_2025_2026.json")

    # Build a lookup: sb team_id -> our internal team id
    sb_team_lookup = dict(zip(teams_mapping["sb_id"], teams_mapping["id"]))

    meta_fields = ["player_name", "competition_name", "season_name",
                   "birth_date", "player_female", "player_first_name",
                   "player_last_name", "player_known_name",
                   "player_weight", "player_height",
                   "primary_position", "secondary_position"]

    rows = []
    for player in load_json(path):
        row = {"sb_id": player.get("player_id") or player.get("id")}

        # Resolve StatsBomb team_id to our internal team id
        sb_team_id = player.get("team_id")
        row["team_id"] = sb_team_lookup.get(sb_team_id)

        for field in meta_fields:
            row[field] = player.get(field)

        # Dynamically add all player_season_* statistics
        for key, value in player.items():
            if key.startswith("player_season_"):
                row[key] = value

        rows.append(row)

    return pd.DataFrame(rows).drop_duplicates("sb_id")


def process_players():
    players_mapping = pd.read_csv(os.path.join(RAW, "mapping", "players_mapping.csv"))
    teams_mapping   = pd.read_csv(os.path.join(RAW, "mapping", "teams_mapping.csv"))

    result = players_mapping.copy()
    result = result.merge(load_players_statsbomb(teams_mapping), on="sb_id", how="left")
    result = result.merge(load_players_transfermarkt(),          on="tm_id", how="left")

    # Remove all source IDs, source names and match flag columns
    source_cols = [
        "sb_id", "sb_name", "sb_birth_date",
        "sc_id", "sc_name", "sc_birth_date",
        "tm_id", "tm_name", "tm_birth_date",
        "match_sb_sc", "match_sb_tm", "match_sc_tm",
    ]
    result = result.drop(columns=[c for c in source_cols if c in result.columns])

    # Replace competition_name and season_name with edition_id
    result["edition_id"] = EDITION_ID
    result = result.drop(columns=[c for c in ["competition_name", "season_name"] if c in result.columns])

    # Put descriptive columns first, then all stats at the end
    identity_cols = [
        "id", "player_name", "player_first_name", "player_last_name", "player_known_name",
        "team_id", "edition_id", "player_female",
        "birth_date", "age", "birth_place", "nationalities",
        "player_height", "player_weight",
        "primary_position", "secondary_position",
        "shirt_number", "joined_date", "contract_end", "market_value_m",
        "matches", "goals", "assists", "minutes", "yellow_cards", "red_cards",
    ]
    identity_cols = [c for c in identity_cols if c in result.columns]
    stat_cols = sorted([c for c in result.columns if c not in identity_cols])
    result = result[identity_cols + stat_cols]

    save_csv(result, "players")


# ============================================================
# MATCHES
# ============================================================

def load_matches_statsbomb():
    # Extract match metadata from StatsBomb
    path = os.path.join(RAW, "statsbomb", "matches", "ligue1_matches_2025_2026.json")
    rows = []
    for match in load_json(path):
        rows.append({
            "sb_id":          match.get("match_id"),
            "match_date":     match.get("match_date"),
            "kick_off":       match.get("kick_off"),
            "competition":    match.get("competition"),
            "season":         match.get("season"),
            "home_score":     match.get("home_score"),
            "away_score":     match.get("away_score"),
            "attendance":          match.get("attendance"),
            "behind_closed_doors": match.get("behind_closed_doors"),
            "neutral_ground":      match.get("neutral_ground"),
            "match_week":          match.get("match_week"),
            "competition_stage": match.get("competition_stage"),
            "stadium":        match.get("stadium"),
            "referee":        match.get("referee"),
            "home_managers":  match.get("home_managers"),
            "away_managers":  match.get("away_managers"),
        })
    return pd.DataFrame(rows).drop_duplicates("sb_id")


def load_match_skillcorner(sc_id, sc_team_lookup):
    # Load a single SkillCorner match file and extract required fields
    path = os.path.join(RAW, "skillcorner", "matches", f"match_{sc_id}.json")
    if not os.path.exists(path):
        return {}

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Duration of each period
    period_1_minutes = None
    period_2_minutes = None
    for period in data.get("match_periods", []):
        if period.get("period") == 1:
            period_1_minutes = period.get("duration_minutes")
        elif period.get("period") == 2:
            period_2_minutes = period.get("duration_minutes")

    # Resolve SkillCorner team IDs to our internal team IDs
    home_sc_id = data.get("home_team", {}).get("id")
    away_sc_id = data.get("away_team", {}).get("id")

    return {
        "period_1_minutes": period_1_minutes,
        "period_2_minutes": period_2_minutes,
        "pitch_length":     data.get("pitch_length"),
        "pitch_width":      data.get("pitch_width"),
        "home_team_id":     sc_team_lookup.get(home_sc_id),
        "away_team_id":     sc_team_lookup.get(away_sc_id),
    }


def process_matches():
    matches_mapping = pd.read_csv(os.path.join(RAW, "mapping", "matches_mapping.csv"))
    teams_mapping   = pd.read_csv(os.path.join(RAW, "mapping", "teams_mapping.csv"))

    # Build a lookup: SkillCorner team sc_id -> our internal team id
    sc_team_lookup = dict(zip(teams_mapping["sc_id"], teams_mapping["id"]))

    # Load StatsBomb matches and join on mapping
    sb_df  = load_matches_statsbomb()
    result = matches_mapping.merge(sb_df, on="sb_id", how="left")

    # Load SkillCorner data match by match and attach to result
    sc_rows = []
    for _, row in matches_mapping.iterrows():
        sc_data = load_match_skillcorner(row["sc_id"], sc_team_lookup)
        sc_data["sc_id"] = row["sc_id"]
        sc_rows.append(sc_data)

    sc_df  = pd.DataFrame(sc_rows).drop_duplicates("sc_id")
    result = result.merge(sc_df, on="sc_id", how="left")

    # Remove source ID columns (handled by the mapping table)
    source_cols = ["sb_id", "sc_id", "date"]
    result = result.drop(columns=[c for c in source_cols if c in result.columns])

    # Replace competition and season columns with edition_id
    result["edition_id"] = EDITION_ID
    result = result.drop(columns=[c for c in ["competition", "season"] if c in result.columns])

    # Reorder columns
    identity_cols = [
        "id",
        "match_date", "kick_off",
        "edition_id", "match_week", "competition_stage",
        "home_team_id", "away_team_id",
        "home_score", "away_score",
        "period_1_minutes", "period_2_minutes",
        "pitch_length", "pitch_width",
        "stadium", "referee", "home_managers", "away_managers",
        "attendance", "behind_closed_doors", "neutral_ground",
    ]
    identity_cols = [c for c in identity_cols if c in result.columns]
    remaining     = [c for c in result.columns if c not in identity_cols]
    result        = result[identity_cols + remaining]

    save_csv(result, "matches")


# ============================================================
# LINEUPS  (match_players join table)
# ============================================================

def process_match_players():
    matches_mapping = pd.read_csv(os.path.join(RAW, "mapping", "matches_mapping.csv"))
    players_mapping = pd.read_csv(os.path.join(RAW, "mapping", "players_mapping.csv"))

    # Build lookups
    # SkillCorner match sc_id -> our internal match id
    sc_match_lookup = dict(zip(matches_mapping["sc_id"], matches_mapping["id"]))
    # SkillCorner player sc_id -> our internal player id
    sc_player_lookup = dict(zip(players_mapping["sc_id"], players_mapping["id"]))

    rows = []

    for sc_match_id, match_id in sc_match_lookup.items():
        path = os.path.join(RAW, "skillcorner", "matches", f"match_{sc_match_id}.json")
        if not os.path.exists(path):
            continue

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        home_sc_team_id = data.get("home_team", {}).get("id")

        for player in data.get("players", []):
            sc_player_id = player.get("id")

            # Extract position info from player_role
            role = player.get("player_role", {})

            # Extract minutes played from playing_time
            # total can be null for unused substitutes, default to 0
            playing_time   = player.get("playing_time") or {}
            total          = playing_time.get("total") or {}
            minutes_played = total.get("minutes_played", 0)

            # Extract minutes by period, default to 0 if period not present
            period_1_minutes = 0
            period_2_minutes = 0
            for period in playing_time.get("by_period") or []:
                if period.get("name") == "period_1":
                    period_1_minutes = period.get("minutes_played")
                elif period.get("name") == "period_2":
                    period_2_minutes = period.get("minutes_played")

            rows.append({
                "match_id":        match_id,
                "player_id":       sc_player_lookup.get(sc_player_id),
                "is_home_player":  player.get("team_id") == home_sc_team_id,
                "position_group":  role.get("position_group"),
                "position":        role.get("name"),
                "shirt_number":    player.get("number"),
                "start_time":      player.get("start_time"),
                "end_time":        player.get("end_time"),
                "minutes_played":  minutes_played,
                "period_1_minutes": period_1_minutes,
                "period_2_minutes": period_2_minutes,
                "goals":           player.get("goal"),
                "own_goals":       player.get("own_goal"),
                "yellow_cards":    player.get("yellow_card"),
                "red_cards":       player.get("red_card"),
                "injured":         player.get("injured"),
            })

    result = pd.DataFrame(rows)
    save_csv(result, "match_players")

# ============================================================
# EVENTS
# ============================================================

# Event types to process and their specific sub-key in the JSON
EVENT_TYPES = {
    "Shot":          "shot",
    "Pass":          "pass",
    "Carry":         "carry",
    "Pressure":      "pressure",
    "Ball Recovery": "ball_recovery",
}

# Specific sub-fields to extract for each event type
EVENT_SUBFIELDS = {
    "shot": [
        "statsbomb_xg", "shot_execution_xg", "shot_execution_xg_uplift",
        "gk_save_difficulty_xg", "gk_positioning_xg_suppression",
        "gk_shot_stopping_xg_suppression",
        "end_location", "type", "technique", "outcome", "body_part",
        "first_time", "follows_dribble", "key_pass_id", "shot_shot_assist",
    ],
    "pass": [
        "recipient", "length", "angle", "height", "end_location",
        "pass_success_probability", "body_part", "type", "technique",
        "outcome", "cross", "cut_back", "switch", "through_ball",
        "goal_assist", "shot_assist", "assisted_shot_id",
        "inswinging", "deflected", "aerial_won", "miscommunication",
        "pass_cluster_id", "pass_cluster_label", "pass_cluster_probability", "xclaim",
    ],
    "carry": [
        "end_location",
    ],
    "ball_recovery": [
        "recovery_failure",
    ],
    "pressure": [
        "counterpress",
    ],
}


def parse_location(location):
    # Split a [x, y] or [x, y, z] location list into separate floats
    if location and len(location) >= 2:
        x = location[0]
        y = location[1]
        z = location[2] if len(location) == 3 else None
        return x, y, z
    return None, None, None


def load_events_for_match(sb_match_id, match_id, sb_player_lookup):
    # Load a single StatsBomb events file and return (events_rows, sub_rows_by_type)
    path = os.path.join(RAW, "statsbomb", "events", f"match_{sb_match_id}_events.json")
    if not os.path.exists(path):
        return [], {t: [] for t in EVENT_TYPES}

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    event_rows = []
    sub_rows   = {t: [] for t in EVENT_TYPES}

    for e in raw:
        event_type = e.get("type", {}).get("name")

        # Only process the five selected event types with a player
        if event_type not in EVENT_TYPES or "player" not in e:
            continue

        sb_player_id = e.get("player", {}).get("id")
        player_id    = sb_player_lookup.get(sb_player_id)

        location_x, location_y, location_z = parse_location(e.get("location"))

        # Common fields for events.csv
        event_rows.append({
            "id":               e.get("id"),
            "match_id":         match_id,
            "player_id":        player_id,
            "period":           e.get("period"),
            "minute":           e.get("minute"),
            "second":           e.get("second"),
            "timestamp":        e.get("timestamp"),
            "type":             event_type,
            "play_pattern":     e.get("play_pattern", {}).get("name"),
            "possession":       e.get("possession"),
            "possession_team":  e.get("possession_team", {}).get("name"),
            "location_x":       location_x,
            "location_y":       location_y,
            "duration":         e.get("duration"),
            "under_pressure":   e.get("under_pressure"),
            "obv_for_net":      e.get("obv_for_net"),
            "obv_against_net":  e.get("obv_against_net"),
            "obv_total_net":    e.get("obv_total_net"),
        })

        # Specific sub-fields for the event type sub-table
        sub_key = EVENT_TYPES[event_type]

        # Pressure has no sub-object, its specific fields are at the root level
        if sub_key == "pressure":
            sub_data = e
        else:
            sub_data = e.get(sub_key, {}) or {}
        row = {"event_id": e.get("id")}

        # For shots, add the z coordinate of the location
        if sub_key == "shot":
            row["location_z"] = location_z

        for field in EVENT_SUBFIELDS.get(sub_key, []):
            value = sub_data.get(field)
            # Flatten nested objects to their name, flatten end_location to x/y
            if field == "end_location":
                ex, ey, _ = parse_location(value)
                row["end_location_x"] = ex
                row["end_location_y"] = ey
            elif field == "recipient":
                row["recipient_id"] = sb_player_lookup.get(
                    value.get("id") if isinstance(value, dict) else None
                )
            elif isinstance(value, dict):
                row[field] = value.get("name")
            else:
                row[field] = value

        sub_rows[event_type].append(row)

    return event_rows, sub_rows


def process_events():
    matches_mapping = pd.read_csv(os.path.join(RAW, "mapping", "matches_mapping.csv"))
    players_mapping = pd.read_csv(os.path.join(RAW, "mapping", "players_mapping.csv"))

    # Build lookups
    # StatsBomb match sb_id -> our internal match id
    sb_match_lookup  = dict(zip(matches_mapping["sb_id"], matches_mapping["id"]))
    # StatsBomb player sb_id -> our internal player id
    sb_player_lookup = dict(zip(players_mapping["sb_id"], players_mapping["id"]))

    all_events   = []
    all_sub_rows = {t: [] for t in EVENT_TYPES}

    for sb_match_id, match_id in sb_match_lookup.items():
        event_rows, sub_rows = load_events_for_match(
            sb_match_id, match_id, sb_player_lookup
        )
        all_events.extend(event_rows)
        for event_type in EVENT_TYPES:
            all_sub_rows[event_type].extend(sub_rows[event_type])

    # Save events.csv
    save_csv(pd.DataFrame(all_events), "events")

    # Save one sub-table per event type
    for event_type, sub_key in EVENT_TYPES.items():
        save_csv(pd.DataFrame(all_sub_rows[event_type]), "events_" + sub_key)


# ============================================================
# PHYSICAL
# ============================================================

def process_physical():
    players_mapping = pd.read_csv(os.path.join(RAW, "mapping", "players_mapping.csv"))
    matches_mapping = pd.read_csv(os.path.join(RAW, "mapping", "matches_mapping.csv"))

    # Build lookups: SkillCorner ids -> our internal ids
    sc_player_lookup = dict(zip(players_mapping["sc_id"], players_mapping["id"]))
    sc_match_lookup  = dict(zip(matches_mapping["sc_id"], matches_mapping["id"]))

    # Physical fields to extract from each result entry
    PHYSICAL_FIELDS = [
        "minutes_full_all", "physical_check_passed",
        "total_distance_full_all", "total_metersperminute_full_all",
        "running_distance_full_all",
        "hsr_distance_full_all", "hsr_count_full_all",
        "sprint_distance_full_all", "sprint_count_full_all",
        "hi_distance_full_all", "hi_count_full_all",
        "psv99",
        "medaccel_count_full_all", "highaccel_count_full_all",
        "meddecel_count_full_all", "highdecel_count_full_all",
        "explacceltohsr_count_full_all", "timetohsr", "timetohsrpostcod",
        "explacceltosprint_count_full_all", "timetosprint", "timetosprintpostcod",
        "cod_count_full_all", "timeto505around90", "timeto505around180",
    ]

    rows = []
    physical_dir = os.path.join(RAW, "skillcorner", "physical")

    for filename in os.listdir(physical_dir):
        if not filename.endswith(".json"):
            continue

        with open(os.path.join(physical_dir, filename), encoding="utf-8") as f:
            data = json.load(f)

        # Total number of match entries in this file
        match_count = data.get("count", 0)

        for entry in data.get("results", []):
            sc_player_id = entry.get("player_id")
            sc_match_id  = entry.get("match_id")

            row = {
                "player_id":   sc_player_lookup.get(sc_player_id),
                "match_id":    sc_match_lookup.get(sc_match_id),
                "match_count": match_count,
            }

            for field in PHYSICAL_FIELDS:
                row[field] = entry.get(field)

            rows.append(row)

    # Generate a simple auto-incremented id
    result = pd.DataFrame(rows)
    result.insert(0, "id", range(1, len(result) + 1))

    save_csv(result, "physical")


if __name__ == "__main__":
    process_edition()
    process_teams()
    process_players()
    process_matches()
    process_match_players()
    process_events()
    process_physical()