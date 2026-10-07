"""
create_database.py
------------------
Creates all tables in the PostgreSQL database.

Dynamic stat columns (team_season_*, player_season_*) are inferred directly
from the processed CSV headers so the script never goes out of sync.
All existing tables are dropped first before being recreated.

USAGE
-----
  python database/create_database.py
"""

import csv
from pathlib import Path

from db_connection import get_connection

ROOT      = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

def get_csv_headers(filename):
    """Return the list of column names from a processed CSV file."""
    path = PROCESSED / filename
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with open(path, encoding="utf-8") as f:
        return next(csv.reader(f))


def stat_cols_as_float(headers, exclude):
    """Return SQL column definitions as FLOAT for all headers not in exclude."""
    lines = []
    for h in headers:
        if h not in exclude:
            lines.append(f"        {h:<60} FLOAT")
    return lines


# -----------------------------------------------------------------------------
# DYNAMIC TABLE BUILDERS
# (teams and players have variable stat columns read from CSV headers)
# -----------------------------------------------------------------------------

def build_teams_sql():
    headers    = get_csv_headers("teams.csv")
    fixed_names = {
        "id", "team", "edition_id", "team_female", "city",
        "stadium_name", "stadium_capacity", "squad_size", "average_age",
        "national_team_players", "table_position", "years_in_league",
    }
    fixed = [
        "        id                                          INTEGER PRIMARY KEY",
        "        team                                        VARCHAR(100)",
        "        edition_id                                  INTEGER REFERENCES edition(id)",
        "        team_female                                 BOOLEAN",
        "        city                                        VARCHAR(100)",
        "        stadium_name                                VARCHAR(150)",
        "        stadium_capacity                            INTEGER",
        "        squad_size                                  INTEGER",
        "        average_age                                 FLOAT",
        "        national_team_players                       INTEGER",
        "        table_position                              INTEGER",
        "        years_in_league                             INTEGER",
    ]
    all_lines = fixed + stat_cols_as_float(headers, fixed_names)
    return (
        "CREATE TABLE IF NOT EXISTS teams (\n"
        + ",\n".join(all_lines) + "\n"
        ");"
    )


def build_players_sql():
    headers    = get_csv_headers("players.csv")
    fixed_names = {
        "id", "player_name", "player_first_name", "player_last_name",
        "player_known_name", "team_id", "edition_id", "player_female",
        "birth_date", "age", "birth_place", "nationalities",
        "player_height", "player_weight", "primary_position",
        "secondary_position", "shirt_number", "joined_date",
        "contract_end", "market_value_m", "matches", "goals",
        "assists", "minutes", "yellow_cards", "red_cards",
        "player_season_most_recent_match",
    }
    fixed = [
        "        id                                          INTEGER PRIMARY KEY",
        "        player_name                                 VARCHAR(150)",
        "        player_first_name                           VARCHAR(100)",
        "        player_last_name                            VARCHAR(100)",
        "        player_known_name                           VARCHAR(100)",
        "        team_id                                     INTEGER REFERENCES teams(id)",
        "        edition_id                                  INTEGER REFERENCES edition(id)",
        "        player_female                               BOOLEAN",
        "        birth_date                                  DATE",
        "        age                                         INTEGER",
        "        birth_place                                 VARCHAR(100)",
        "        nationalities                               VARCHAR(200)",
        "        player_height                               FLOAT",
        "        player_weight                               FLOAT",
        "        primary_position                            VARCHAR(100)",
        "        secondary_position                          VARCHAR(100)",
        "        shirt_number                                INTEGER",
        "        joined_date                                 DATE",
        "        contract_end                                DATE",
        "        market_value_m                              FLOAT",
        "        matches                                     INTEGER",
        "        goals                                       INTEGER",
        "        assists                                     INTEGER",
        "        minutes                                     INTEGER",
        "        yellow_cards                                INTEGER",
        "        red_cards                                   INTEGER",
        "        player_season_most_recent_match             TIMESTAMP",
    ]
    all_lines = fixed + stat_cols_as_float(headers, fixed_names)
    return (
        "CREATE TABLE IF NOT EXISTS players (\n"
        + ",\n".join(all_lines) + "\n"
        ");"
    )


# -----------------------------------------------------------------------------
# STATIC TABLE DEFINITIONS
# -----------------------------------------------------------------------------

TABLES_AFTER_TEAMS_AND_PLAYERS = [

    # ── Teams Mapping ─────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS teams_mapping (
        id      INTEGER PRIMARY KEY REFERENCES teams(id),
        sb_id   INTEGER,
        sc_id   INTEGER,
        tm_id   INTEGER
    );
    """,

    # ── Players Mapping ───────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS players_mapping (
        id      INTEGER PRIMARY KEY REFERENCES players(id),
        sb_id   INTEGER,
        sc_id   INTEGER,
        tm_id   INTEGER
    );
    """,

    # ── Matches ───────────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS matches (
        id                  INTEGER PRIMARY KEY,
        match_date          DATE,
        kick_off            TIME,
        edition_id          INTEGER REFERENCES edition(id),
        match_week          INTEGER,
        competition_stage   VARCHAR(100),
        home_team_id        INTEGER REFERENCES teams(id),
        away_team_id        INTEGER REFERENCES teams(id),
        home_score          INTEGER,
        away_score          INTEGER,
        period_1_minutes    FLOAT,
        period_2_minutes    FLOAT,
        pitch_length        FLOAT,
        pitch_width         FLOAT,
        stadium             VARCHAR(150),
        referee             VARCHAR(150),
        home_managers       VARCHAR(150),
        away_managers       VARCHAR(150),
        attendance          INTEGER,
        behind_closed_doors BOOLEAN,
        neutral_ground      BOOLEAN
    );
    """,

    # ── Matches Mapping ───────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS matches_mapping (
        id      INTEGER PRIMARY KEY REFERENCES matches(id),
        sb_id   INTEGER,
        sc_id   INTEGER
    );
    """,

    # ── Match Players ─────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS match_players (
        match_id            INTEGER REFERENCES matches(id),
        player_id           INTEGER REFERENCES players(id),
        is_home_player      BOOLEAN,
        position_group      VARCHAR(100),
        position            VARCHAR(100),
        shirt_number        INTEGER,
        start_time          TIME,
        end_time            TIME,
        minutes_played      FLOAT,
        period_1_minutes    FLOAT,
        period_2_minutes    FLOAT,
        goals               INTEGER,
        own_goals           INTEGER,
        yellow_cards        INTEGER,
        red_cards           INTEGER,
        injured             BOOLEAN,
        PRIMARY KEY (match_id, player_id)
    );
    """,

    # ── Events ────────────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS events (
        id              UUID PRIMARY KEY,
        match_id        INTEGER REFERENCES matches(id),
        player_id       INTEGER REFERENCES players(id),
        period          INTEGER,
        minute          INTEGER,
        second          INTEGER,
        timestamp       TIME,
        type            VARCHAR(50),
        play_pattern    VARCHAR(100),
        possession      INTEGER,
        possession_team VARCHAR(100),
        location_x      FLOAT,
        location_y      FLOAT,
        duration        FLOAT,
        under_pressure  BOOLEAN,
        obv_for_net     FLOAT,
        obv_against_net FLOAT,
        obv_total_net   FLOAT
    );
    """,

    # ── Events Shot ───────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS events_shot (
        event_id                        UUID PRIMARY KEY REFERENCES events(id),
        location_z                      FLOAT,
        statsbomb_xg                    FLOAT,
        shot_execution_xg               FLOAT,
        shot_execution_xg_uplift        FLOAT,
        gk_save_difficulty_xg           FLOAT,
        gk_positioning_xg_suppression   FLOAT,
        gk_shot_stopping_xg_suppression FLOAT,
        end_location_x                  FLOAT,
        end_location_y                  FLOAT,
        type                            VARCHAR(100),
        technique                       VARCHAR(100),
        outcome                         VARCHAR(100),
        body_part                       VARCHAR(100),
        first_time                      BOOLEAN,
        follows_dribble                 BOOLEAN,
        key_pass_id                     UUID,
        shot_shot_assist                BOOLEAN
    );
    """,

    # ── Events Pass ───────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS events_pass (
        event_id                    UUID PRIMARY KEY REFERENCES events(id),
        recipient_id                INTEGER REFERENCES players(id),
        length                      FLOAT,
        angle                       FLOAT,
        height                      VARCHAR(100),
        end_location_x              FLOAT,
        end_location_y              FLOAT,
        pass_success_probability    FLOAT,
        body_part                   VARCHAR(100),
        type                        VARCHAR(100),
        technique                   VARCHAR(100),
        outcome                     VARCHAR(100),
        "cross"                     BOOLEAN,
        cut_back                    BOOLEAN,
        switch                      BOOLEAN,
        through_ball                BOOLEAN,
        goal_assist                 BOOLEAN,
        shot_assist                 BOOLEAN,
        assisted_shot_id            UUID,
        inswinging                  BOOLEAN,
        deflected                   BOOLEAN,
        aerial_won                  BOOLEAN,
        miscommunication            BOOLEAN,
        pass_cluster_id             INTEGER,
        pass_cluster_label          VARCHAR(100),
        pass_cluster_probability    FLOAT,
        xclaim                      FLOAT
    );
    """,

    # ── Events Carry ──────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS events_carry (
        event_id        UUID PRIMARY KEY REFERENCES events(id),
        end_location_x  FLOAT,
        end_location_y  FLOAT
    );
    """,

    # ── Events Pressure ───────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS events_pressure (
        event_id        UUID PRIMARY KEY REFERENCES events(id),
        counterpress    BOOLEAN
    );
    """,

    # ── Events Ball Recovery ──────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS events_ball_recovery (
        event_id            UUID PRIMARY KEY REFERENCES events(id),
        recovery_failure    BOOLEAN
    );
    """,

    # ── Physical ──────────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS physical (
        id                              SERIAL PRIMARY KEY,
        match_id                        INTEGER REFERENCES matches(id),
        player_id                       INTEGER REFERENCES players(id),
        match_count                     INTEGER,
        minutes_full_all                FLOAT,
        physical_check_passed           BOOLEAN,
        total_distance_full_all         FLOAT,
        total_metersperminute_full_all  FLOAT,
        running_distance_full_all       FLOAT,
        hsr_distance_full_all           FLOAT,
        hsr_count_full_all              FLOAT,
        sprint_distance_full_all        FLOAT,
        sprint_count_full_all           FLOAT,
        hi_distance_full_all            FLOAT,
        hi_count_full_all               FLOAT,
        psv99                           FLOAT,
        medaccel_count_full_all         FLOAT,
        highaccel_count_full_all        FLOAT,
        meddecel_count_full_all         FLOAT,
        highdecel_count_full_all        FLOAT,
        explacceltohsr_count_full_all   FLOAT,
        timetohsr                       FLOAT,
        timetohsrpostcod                FLOAT,
        explacceltosprint_count_full_all FLOAT,
        timetosprint                    FLOAT,
        timetosprintpostcod             FLOAT,
        cod_count_full_all              FLOAT,
        timeto505around90               FLOAT,
        timeto505around180              FLOAT
    );
    """,
]


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def create_tables():
    conn = get_connection()
    conn.autocommit = True
    cursor = conn.cursor()

    # Drop all tables in reverse dependency order
    cursor.execute("""
        DROP TABLE IF EXISTS
            events_ball_recovery, events_pressure, events_carry,
            events_pass, events_shot, physical, events,
            match_players, matches_mapping, players_mapping, teams_mapping,
            matches, players, teams, edition
        CASCADE;
    """)
    print("Dropped all existing tables.")

    # edition first (no dependencies)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS edition (
            id          INTEGER PRIMARY KEY,
            competition VARCHAR(100) NOT NULL,
            season      VARCHAR(20)  NOT NULL
        );
    """)
    print("Created table: edition")

    # teams and players with dynamic stat columns from CSV headers
    cursor.execute(build_teams_sql())
    print("Created table: teams")

    cursor.execute(build_players_sql())
    print("Created table: players")

    # All remaining static tables
    for sql in TABLES_AFTER_TEAMS_AND_PLAYERS:
        name = [line.strip() for line in sql.strip().splitlines()
                if line.strip().upper().startswith("CREATE TABLE")][0]
        name = name.split("EXISTS")[-1].strip().split("(")[0].strip()
        cursor.execute(sql)
        print("Created table: " + name)

    cursor.close()
    conn.close()
    print("\nAll tables created successfully.")


if __name__ == "__main__":
    create_tables()