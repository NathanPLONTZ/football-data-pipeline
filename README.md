# Football Multi-Source Database — Ligue 1 2025/2026

A data engineering pipeline that ingests, reconciles and centralises football data from
three independent providers — **StatsBomb**, **SkillCorner** and **Transfermarkt** — into a
single normalised PostgreSQL database.

The core problem this project solves is **cross-source identity resolution**: the same player,
team or match carries a completely different ID in each system, and no shared key exists.

> **Why this project exists.** This was the technical test I was given when applying for a data
> engineering internship at **FC Metz** (Ligue 1 club). I built it in about eight days, then
> presented and defended it in the interview that followed — and I was offered the internship on
> the strength of it. It was not a school assignment: the brief, the data access and the
> evaluation criteria all came from the club. That brief is summarised in
> [Context](#1-context) below.

**Interactive schema:** [view the ER diagram on dbdiagram.io](https://dbdiagram.io/d/699b8fd2bd82f5fce272c27a)

**Slide deck:** [`presentation.pdf`](presentation.pdf) — the deck I presented to the club at the
interview, covering the pipeline, each ingestion, the mapping algorithms, the data model, the
difficulties encountered and what I would improve *(in French)*.

---

## Table of Contents

1. [Context](#1-context)
2. [Pipeline architecture](#2-pipeline-architecture)
3. [Data sources](#3-data-sources)
4. [Repository structure](#4-repository-structure)
5. [Database schema](#5-database-schema)
6. [How to run](#6-how-to-run)
7. [Pipeline CLI reference](#7-pipeline-cli-reference)
8. [Mapping techniques](#8-mapping-techniques)
9. [Technical choices](#9-technical-choices)
10. [Results](#10-results)

---

## 1. Context

The club set the brief as the technical stage of its internship recruitment: design and
implement a database centralising, structuring and linking football data from several sources,
for the current Ligue 1 season. Credentials for the StatsBomb and SkillCorner APIs were
provided for the duration of the test. It was explicitly framed as an evaluation of reasoning
and technical choices rather than of a finished product — the stated goal was to understand how
I think, not to receive a polished deliverable in two weeks.

**What the brief asked to demonstrate:**

- the ability to ingest football-specific data;
- a clean and extensible data architecture;
- the ability to work autonomously from provider documentation.

**Required work:**

| Stage | Requirement |
|---|---|
| Ingestion | Retrieve data from each source (API / scraping) and build a **re-runnable pipeline** |
| Modelling | Design a coherent schema linking matches, teams, players, events and physical data |
| Players table | **Focus point** — merge player information coming from all three sources |
| ID mapping | Handle the ID correspondences between sources |
| Storage | Free choice of technology; what matters is model coherence and justification |

**Expected deliverable:** the project code with a README explaining the database schema, how
to run it, and the technical choices. The stated evaluation criteria were understanding of
data diversity, clarity of the architecture, and quality of the documentation.

---

## 2. Pipeline architecture

Four sequential stages, each independently re-runnable, orchestrated by `scripts/pipeline.py`:

```
                    ┌──────────────┐
  TRANSFERMARKT ───▶│              │
                    │              │    ┌─────────┐   ┌─────────┐   ┌───────────┐
  SKILLCORNER   ───▶│  INGESTION   │───▶│ MAPPING │──▶│ PROCESS │──▶│ INJECTION │
                    │              │    └─────────┘   └─────────┘   └───────────┘
  STATSBOMB     ───▶│              │         │             │              │
                    └──────────────┘         │             │              │
                           │                 │             │              │
                 ingest_transfermarkt  mapping_players  process_data  create_database
                 ingest_skillcorner    mapping_teams                  inject_processed_
                 ingest_statsbomb      mapping_matches                data_in_database

                    data/raw/         data/raw/mapping/  data/processed/   PostgreSQL
```

| Stage | What it does |
|---|---|
| **Ingestion** | Pulls raw payloads from each provider and writes them to `data/raw/<source>/` untouched. Resumable: existing files are skipped unless a re-download is forced. |
| **Mapping** | Resolves cross-source identities and emits three mapping tables under `data/raw/mapping/`, assigning the project's own internal IDs. |
| **Process** | Flattens and merges the heterogeneous raw formats (JSON, CSV, nested objects) into 12 clean, DB-ready CSVs in `data/processed/`. |
| **Injection** | Creates the schema (inferring dynamic stat columns from the CSV headers) and bulk-inserts every CSV in dependency order. |

Raw data is **always** persisted before any transformation. This makes the raw layer a local
cache — re-running the transformation never costs another API call or scraping run — and it
means that when a transformation looks wrong, the original payload is still on disk to inspect.

---

## 3. Data sources

| Source | Access method | Data provided |
|---|---|---|
| **StatsBomb** | `statsbombpy` library + direct REST API | Event-level data (passes, shots, carries, pressures, ball recoveries), player and team season stats, match reference |
| **SkillCorner** | `skillcorner.client` module + REST API | Physical / athletic tracking (distance, high-speed running, sprints, accelerations), lineups, match detail |
| **Transfermarkt** | Web scraping (`requests` + `BeautifulSoup`) | Contextual data (market value, contract expiry, age, place of birth, nationality, squad info) |

Events are fetched through **direct REST calls rather than `statsbombpy`**, because the library
flattens the response and discards nested objects (shot freeze frames, tactics lineups, pass
cluster details) that this project keeps.

### Why the data is not in this repository

`data/` is gitignored and intentionally not published:

- **Volume** — the StatsBomb event stream alone is hundreds of thousands of rows, one per
  on-ball action across 207 matches.
- **Licensing** — StatsBomb and SkillCorner data is accessed under credentialed commercial
  access and is not mine to redistribute.

The pipeline rebuilds the entire tree from scratch; see [How to run](#6-how-to-run). The
expected layout once populated:

```
data/
├── raw/
│   ├── statsbomb/
│   │   ├── players/   ligue1_players_2025_2026.json
│   │   ├── teams/     ligue1_teams_2025_2026.json
│   │   ├── matches/   ligue1_matches_2025_2026.json
│   │   └── events/    match_<sb_match_id>_events.json     (one file per match)
│   ├── skillcorner/
│   │   ├── players/   ligue1_players_2025_2026.json
│   │   ├── teams/     ligue1_teams_2025_2026.json
│   │   ├── matches/   ligue1_matches_2025_2026.json + match_<sc_id>.json
│   │   └── physical/  player_<sc_id>_<n>_records.json     (one file per player)
│   ├── transfermarkt/
│   │   ├── ligue1_players_2025_2026.csv
│   │   └── ligue1_teams_2025_2026.csv
│   └── mapping/
│       ├── teams_mapping.csv
│       ├── players_mapping.csv
│       └── matches_mapping.csv
└── processed/          12 clean CSVs, one per database table
```

Note the two different granularities the providers use: StatsBomb serves **events per match**,
while SkillCorner serves **physical data per player**. The processing stage reconciles both
onto a single (match, player) grain.

---

## 4. Repository structure

```
.
├── scripts/
│   ├── pipeline.py                 Orchestrator — entry point for every stage
│   ├── common.py                   Helpers shared across scripts
│   ├── ingest_statsbomb.py         StatsBomb ingestion (players/teams/matches/events)
│   ├── ingest_skillcorner.py       SkillCorner ingestion (players/teams/matches/physical)
│   ├── ingest_transfermarkt.py     Transfermarkt scraping (teams, then players)
│   ├── mapping_teams.py            SB ↔ SC ↔ TM team IDs (Hungarian algorithm)
│   ├── mapping_players.py          SB ↔ SC ↔ TM player IDs (multi-pass fuzzy matching)
│   ├── mapping_matches.py          SB ↔ SC match IDs (teams + date)
│   └── process_data.py             Raw → clean, DB-ready CSVs
│
├── database/
│   ├── db_connection.py            Single reusable PostgreSQL connection factory
│   ├── create_database.py          Schema creation (drops and recreates all tables)
│   └── inject_processed_data_in_database.py   Batched CSV → PostgreSQL loading
│
├── test/
│   └── remove_all_data.py          Utility: wipe data/ (supports --dry-run)
│
├── docker-compose.yml              PostgreSQL + pgAdmin + pipeline services
├── Dockerfile                      Pipeline runtime image
├── init_datestyle.sql              Sets the DB datestyle to DMY on first init
├── requirements.txt
├── .env.example                    Template for your credentials
├── presentation.pdf                Slide deck walking through the project (French)
└── README.md
```

---

## 5. Database schema

PostgreSQL, fully normalised. `matches` sits at the centre, with `teams` and `players` as the
core entities, and the mapping tables kept deliberately separate from the business data.

```
edition
  ├── teams ──────────── teams_mapping   (sb_id, sc_id, tm_id)
  ├── players ────────── players_mapping (sb_id, sc_id, tm_id)
  └── matches ────────── matches_mapping (sb_id, sc_id)
        │
        ├── match_players   (match_id + player_id)   ← lineups
        ├── events          (match_id, player_id)
        │     ├── events_shot
        │     ├── events_pass
        │     ├── events_carry
        │     ├── events_pressure
        │     └── events_ball_recovery
        └── physical        (match_id, player_id)    ← SkillCorner tracking
```

### Core tables

| Table | Content |
|---|---|
| **`edition`** | Competition + season (Ligue 1 2025/2026). Root anchor for all data. |
| **`teams`** | One row per club. Fixed descriptive columns, then all `team_season_*` stats. |
| **`players`** | **The focal table of the brief.** Merges biography and context from all three sources: names, birth date, nationality, height/weight, position, shirt number, market value, contract expiry, plus every `player_season_*` stat. |
| **`matches`** | One row per played match: date, kick-off, both teams, score, matchday, referee, stadium, pitch dimensions, period durations, attendance. |
| **`match_players`** | Lineup junction table, PK `(match_id, player_id)`: position, shirt number, minutes played per period, goals, cards, injury flag. |
| **`events`** | One row per on-ball action, holding the fields common to every event type (minute, period, location, duration, possession, OBV). |
| **`physical`** | SkillCorner per-player-per-match tracking metrics. |

### Event sub-tables

A single wide events table would be mostly NULL, since each event type carries different
attributes. Instead there is one shared base table plus one sub-table per type, each keyed by
`event_id`:

| Sub-table | Type-specific fields |
|---|---|
| `events_shot` | xG, execution xG, GK suppression metrics, technique, body part, end location |
| `events_pass` | length, angle, height, success probability, cross, switch, through ball, assist flags, pass cluster |
| `events_carry` | end location |
| `events_pressure` | counterpress |
| `events_ball_recovery` | recovery failure |

Only these five event types are processed, out of the full StatsBomb taxonomy.

### Mapping tables

These are the backbone of the whole project. Each holds the project's internal `id` as primary
key alongside the corresponding provider IDs, so the business tables never carry a foreign
provider's identifier:

| Table | Keys |
|---|---|
| `teams_mapping` | `id`, `sb_id`, `sc_id`, `tm_id` |
| `players_mapping` | `id`, `sb_id`, `sc_id`, `tm_id` |
| `matches_mapping` | `id`, `sb_id`, `sc_id` |

Keeping them separate means a fourth source can be added by appending one column, without
touching any business table.

### Dynamic stat columns

`teams` and `players` carry hundreds of `team_season_*` / `player_season_*` metrics, and the set
changes as providers add or rename them. Rather than hardcode them, `create_database.py` reads
the header row of the generated CSVs and emits one `FLOAT` column per stat, so the schema can
never drift out of sync with the data.

---

## 6. How to run

### Option A — Docker (recommended)

Nothing to install but Docker itself: no Python, PostgreSQL or pgAdmin needed on your machine.

**1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)** and wait for it
to report that it is running.

**2. Create your `.env`** from the template and fill in your provider credentials:

```bash
cp .env.example .env
```

```env
STATSBOMB_USERNAME='your_email'
STATSBOMB_PASSWORD='your_password'
SKILLCORNER_USERNAME='your_login'
SKILLCORNER_PASSWORD='your_password'
```

Wrap values in single quotes so special characters are not mangled. Leave the `DB_*` block as
provided — it is already set up for Docker networking (`DB_HOST=db`).

**3. Start the database and pgAdmin:**

```bash
docker compose up -d db pgadmin
```

**4. Run the full pipeline:**

```bash
docker compose run --rm pipeline python scripts/pipeline.py --all
```

This ingests all three sources, builds the mappings, regenerates the processed CSVs, creates
the schema and injects everything. Expect **roughly 30–40 minutes**, dominated by the
Transfermarkt scraping delays and API response times. Generated files land in your local
`data/` folder.

**5. Browse the database** at <http://localhost:5050> (pgAdmin):

- log in with `admin@fc-metz.fr` / `admin`;
- right-click **Servers** → **Register** → **Server**;
- **General** tab → Name: anything, e.g. `fc_metz`;
- **Connection** tab → Host `db`, Port `5432`, Database `fc_metz_mini_projet`, Username
  `postgres`, Password `postgres`;
- **Save**, then expand
  **Servers → fc_metz → Databases → fc_metz_mini_projet → Schemas → public → Tables**.

Right-click any table → **View/Edit Data** → **All Rows**.

**Useful commands:**

```bash
docker compose down            # stop the containers
docker compose down -v         # stop and delete the database volume (full reset)
docker compose logs -f pipeline
```

### Option B — Local Python

Requires Python 3.11+ and a reachable PostgreSQL instance.

```bash
pip install -r requirements.txt
cp .env.example .env          # then set DB_HOST=localhost and fill in your credentials
python scripts/pipeline.py --all
```

---

## 7. Pipeline CLI reference

Running the orchestrator with no arguments prints the full usage:

```bash
python scripts/pipeline.py
```

### Whole pipeline

```bash
python scripts/pipeline.py --all
```

Runs every stage end to end: all three ingestions, all three mappings, processing, schema
creation, injection.

### Individual stages

```bash
python scripts/pipeline.py --process      # regenerate the processed CSVs
python scripts/pipeline.py --create-db    # drop and recreate all tables
python scripts/pipeline.py --inject       # load the processed CSVs into PostgreSQL
python scripts/pipeline.py --mapping                   # all three mappings
python scripts/pipeline.py --mapping players teams     # only these
```

### Ingestion blocks

`--ingest <source>` opens a block; every flag until the next top-level flag belongs to it, so
several independent blocks can be combined in a single call:

```bash
# One source, specific sub-steps
python scripts/pipeline.py --ingest statsbomb --matches

# Specific entities by provider ID
python scripts/pipeline.py --ingest transfermarkt --players 36
python scripts/pipeline.py --ingest statsbomb --events 3935583 3935584

# Several blocks at once
python scripts/pipeline.py \
    --ingest statsbomb     --matches \
    --ingest transfermarkt --players 36 \
    --ingest skillcorner   --teams

# Test mode: cap the number of items processed in that block
python scripts/pipeline.py --ingest skillcorner --players --limit 10
```

Per-source flags:

| Source | Flags |
|---|---|
| `statsbomb` | `--players` `--teams` `--matches` `--events [ID ...]` `--limit N` |
| `skillcorner` | `--players [ID ...]` `--teams` `--matches [ID ...]` `--limit N` |
| `transfermarkt` | `--teams` `--players [ID ...]` `--limit N` |

Each source script can also be run directly (`python scripts/ingest_statsbomb.py --all`) and
has its own `--help`.

### Resumability

- **StatsBomb events** — `--events` with no IDs skips matches already on disk; passing explicit
  IDs forces a re-download.
- **SkillCorner matches** — same behaviour.
- **Transfermarkt players** — a full run resumes by skipping IDs already present in the CSV;
  passing explicit IDs re-scrapes the team pages to refresh just those players.

This makes the long-running stages safe to interrupt and restart without duplicating work.

Every run writes a timestamped log to `data/raw/pipeline_YYYYMMDD_HHMMSS.txt`.

> **Note on `--all`:** `--all` is a *global* flag meaning "run the whole pipeline". It is not a
> per-source modifier, so `--ingest skillcorner --all` does not mean "all of SkillCorner" — it
> triggers the entire pipeline, and the surrounding blocks are ignored. To run every sub-step of
> a single source, list its flags explicitly
> (`--ingest skillcorner --players --teams --matches`), which is also the only form that
> combines with `--limit`.

---

## 8. Mapping techniques

No shared key exists between the three providers, so identities are matched on names and dates.
The strategy differs per entity, because the constraints differ.

### Teams — bijective matching via the Hungarian algorithm

With exactly 18 clubs per source, this is an **assignment problem, not a lookup problem**. A
greedy best-match loop can assign the same club twice and strand another;
`scipy.optimize.linear_sum_assignment` over an 18×18 similarity matrix guarantees a globally
optimal one-to-one assignment.

The similarity score is a weighted blend of three `rapidfuzz` metrics, each covering a different
failure mode:

| Metric | Weight | Handles |
|---|---|---|
| `token_set_ratio` | 0.40 | duplicate and partial words |
| `token_sort_ratio` | 0.35 | word order inversions |
| `ratio` | 0.25 | raw character-by-character sequence |

Matching runs in two passes: **SkillCorner ↔ Transfermarkt first** (their naming conventions are
closest), then **StatsBomb against the resulting pairs** — merging the two most similar sources
first gives the harder third source more signal to match against.

> Example of the problem: *Olympique Lyon* (TM) / *Lyon* (SB) / *Olympique Lyonnais* (SC).

### Players — a four-pass cascade

This is the hardest of the three, and the focus point of the brief. Names are first normalised
(accents stripped, lowercased, punctuation removed), then each player is pushed through
increasingly permissive passes:

```
IF   name + date of birth match exactly        → MATCH (exact)
ELIF name similarity ≥ 95                      → MATCH (fuzzy name)
ELIF same date of birth AND similarity ≥ 45    → MATCH (fuzzy + DOB)
ELIF same date of birth AND alias/short-name
     similarity ≥ 95                           → MATCH (alias + DOB)
ELSE                                           → UNMATCHED
```

The low 45 threshold is only reachable once the date of birth already agrees, which is what
makes it safe: a shared exact DOB is strong enough evidence to tolerate very different name
spellings. The final alias pass catches nicknames by comparing StatsBomb's `player_known_name`
against SkillCorner's `short_name`.

> Real cases this handles:
> - *Marcos Aoás Corrêa* (SB) / *Marquinhos* (SC) / *Marquinhos* (TM) — same DOB, nickname
> - *Ali Yousef Ibrahim Al Musrati* (SB) / *Ali Youssef Musrati* (SC) / *Ali Youssif* (TM)
> - *Sambou Soumano* — names identical, DOB differing between sources
> - *Djaoui Cissé* — DOB off by one day, accents inconsistent

**Why this mapping cannot be perfect.** Two reasons, and only one of them is about the algorithm:

- The rosters genuinely differ. The sources list 473 (TM), 575 (SC) and 527 (SB) players, and
  each legitimately contains players the others lack — transferred players, players who have not
  yet appeared, differing squad-inclusion rules. A 100% match rate is not the target; matching
  everything that *can* be matched is.
- Some source birth dates are simply wrong, which breaks the DOB-constrained passes — hence the
  fuzzy-name-only fallback that does not depend on the date at all.

After manual verification, every player that exists in more than one source was matched
correctly except one.

### Matches — exact lookup

Once teams are resolved, a match is uniquely identified by (home `sc_id`, away `sc_id`, date),
so no fuzzy logic is needed — the team mapping does the hard work. StatsBomb and SkillCorner do
not publish matches at the same rate, so only matches present in **both** sources can be linked;
the rest are reported as unmatched in the run log rather than silently dropped.

---

## 9. Technical choices

### Why PostgreSQL

- The data is **heavily interconnected** — a relational database is the natural fit.
- **Foreign keys** push referential integrity down into the database itself, rather than relying
  on application code to maintain it.
- Robust, open source and a production standard, with good JSON support for raw payloads.

### Why a `match_players` table

A player alone, or a match alone, carries no context. The interesting grain is *"this player, in
this match"* — a textbook many-to-many relationship (a player plays many matches, a match
involves many players). `match_players` materialises it, and both the event stream and the
physical metrics are naturally characterised by that same (match, player) pair.

### Separation of raw and processed data

The ingestion layer only writes; the transformation layer only reads. Beyond making the two
independently re-runnable, this means a modelling change costs one `--process` run instead of a
40-minute re-fetch.

---

## 10. Results

### Ingestion volumes

Full-season figures from a complete run:

| Source | Players | Teams | Matches | Runtime |
|---|---|---|---|---|
| **StatsBomb** | 527 | 18 | 207 | ~11 min |
| **SkillCorner** | 575 | 18 | 207 | ~14 min |
| **Transfermarkt** | 473 | 18 | — | ~28 min |

Only matches with StatsBomb `match_status == "available"` (i.e. actually played) are ingested.
Transfermarkt is the slowest stage by a wide margin, because every request is spaced by a random
1–3 second delay to avoid triggering anti-bot measures.

### Mapping outcomes

| Mapping | Outcome |
|---|---|
| **Teams** | **18/18, exact.** Verified manually — the Hungarian assignment resolved every club correctly across all three sources. |
| **Players** | **All but one player matched** correctly, after manual verification against the players actually present in each source. |
| **Matches** | Every match available in both StatsBomb and SkillCorner was linked. Coverage is bounded by source availability, not by the algorithm. |

See [Mapping techniques](#8-mapping-techniques) for the algorithms behind these numbers and for
why a 100% player match rate is not the target.

### Output

The processing stage produces 12 DB-ready CSVs, loaded into 15 PostgreSQL tables:

```
edition.csv         teams.csv            players.csv       matches.csv
match_players.csv   physical.csv         events.csv        events_shot.csv
events_pass.csv     events_carry.csv     events_pressure.csv
events_ball_recovery.csv
```

A full `--all` run takes roughly **30–40 minutes** end to end, depending on connection speed.
