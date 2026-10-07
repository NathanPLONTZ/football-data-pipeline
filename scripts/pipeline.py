"""
pipeline.py
-----------
Orchestrates all ingestion and mapping scripts.

USAGE
-----
  Full pipeline (everything):
      python pipeline.py --all

  One ingest block:
      python pipeline.py --ingest skillcorner --players 14 18 --teams

  Multiple independent ingest blocks (each block has its own flags/IDs):
      python pipeline.py --ingest skillcorner --players 14 18 --teams \
                         --ingest statsbomb --players --events 3935583 3935584 \
                         --ingest transfermarkt --players 12345

  Mapping:
      python pipeline.py --mapping players
      python pipeline.py --mapping players teams matches

  Create database tables (drops and recreates):
      python pipeline.py --create-db

  Inject processed data into database:
      python pipeline.py --inject

  Process data (regenerate processed CSVs):
      python pipeline.py --process

  Combined:
      python pipeline.py --ingest skillcorner --all \
                         --ingest transfermarkt --players \
                         --mapping players teams

  With limit (applied per block):
      python pipeline.py --ingest skillcorner --all --limit 10
"""

import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPTS_DIR = Path(__file__).resolve().parent

INGEST_SCRIPTS = {
    "skillcorner":   SCRIPTS_DIR / "ingest_skillcorner.py",
    "statsbomb":     SCRIPTS_DIR / "ingest_statsbomb.py",
    "transfermarkt": SCRIPTS_DIR / "ingest_transfermarkt.py",
}

MAPPING_SCRIPTS = {
    "players": SCRIPTS_DIR / "mapping_players.py",
    "teams":   SCRIPTS_DIR / "mapping_teams.py",
    "matches": SCRIPTS_DIR / "mapping_matches.py",
}

PROCESS_SCRIPT   = SCRIPTS_DIR / "process_data.py"
CREATE_DB_SCRIPT = SCRIPTS_DIR.parent / "database" / "create_database.py"
INJECT_SCRIPT    = SCRIPTS_DIR.parent / "database" / "inject_processed_data_in_database.py"

ALL_INGEST_SOURCES  = list(INGEST_SCRIPTS.keys())
ALL_MAPPING_TARGETS = list(MAPPING_SCRIPTS.keys())

# Output log file in data/raw/
LOG_DIR = SCRIPTS_DIR.parent / "data" / "raw"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

def log(message: str, log_fh) -> None:
    """Print to stdout and write to log file."""
    print(message)
    log_fh.write(message + "\n")
    log_fh.flush()


def run(script: Path, args: list[str], log_fh) -> None:
    """Run a script as a subprocess, stream output to stdout and log file."""
    cmd = [sys.executable, "-u", str(script)] + args  # -u = unbuffered stdout
    # Each script runs from its own directory so relative imports work correctly
    cwd = script.parent

    header = (
        f"\n{'=' * 60}\n"
        f"  Running: {script.name}  {' '.join(args)}\n"
        f"{'=' * 60}"
    )
    log(header, log_fh)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=cwd,
    )

    for line in process.stdout:
        line = line.rstrip("\n")
        print(line)
        log_fh.write(line + "\n")
        log_fh.flush()

    process.wait()
    if process.returncode != 0:
        msg = f"\n[ERROR] {script.name} exited with code {process.returncode}"
        log(msg, log_fh)
        sys.exit(process.returncode)


def parse_args(argv: list[str]) -> dict:
    """
    Parses arguments into a sequence of tasks to execute in order.

    Returns:
        {
            "all": bool,
            "create_db": bool,
            "inject": bool,
            "tasks": [
                {"type": "ingest",  "source": "skillcorner", "args": ["--players", "14", "18"]},
                {"type": "ingest",  "source": "statsbomb",   "args": ["--events"]},
                {"type": "mapping", "targets": ["players", "teams"]},
            ]
        }
    """
    parsed = {"all": False, "create_db": False, "inject": False, "process": False, "tasks": []}

    i = 0
    while i < len(argv):
        token = argv[i]

        # --all
        if token == "--all":
            parsed["all"] = True
            i += 1

        # --create-db
        elif token == "--create-db":
            parsed["create_db"] = True
            i += 1

        # --inject
        elif token == "--inject":
            parsed["inject"] = True
            i += 1

        # --process
        elif token == "--process":
            parsed["process"] = True
            i += 1

        # --ingest <source> [flags and IDs until next top-level token]
        elif token == "--ingest":
            i += 1
            if i >= len(argv):
                print("[ERROR] --ingest requires a source name.")
                sys.exit(1)

            source = argv[i]
            if source not in INGEST_SCRIPTS:
                print(f"[ERROR] Unknown ingest source: '{source}'. "
                      f"Choose from: {', '.join(ALL_INGEST_SOURCES)}")
                sys.exit(1)
            i += 1

            block_args = []
            top_level = ("--ingest", "--mapping", "--all", "--create-db", "--inject", "--process")
            while i < len(argv) and argv[i] not in top_level:
                block_args.append(argv[i])
                i += 1

            parsed["tasks"].append({
                "type":   "ingest",
                "source": source,
                "args":   block_args,
            })

        # --mapping <target ...> [until next -- token]
        elif token == "--mapping":
            i += 1

            if i >= len(argv) or argv[i].startswith("--"):
                targets = ALL_MAPPING_TARGETS
            else:
                targets = []
                while i < len(argv) and not argv[i].startswith("--"):
                    tgt = argv[i]
                    if tgt == "all":
                        targets = ALL_MAPPING_TARGETS
                        i += 1
                        break
                    if tgt not in MAPPING_SCRIPTS:
                        print(f"[ERROR] Unknown mapping target: '{tgt}'. "
                              f"Choose from: {', '.join(ALL_MAPPING_TARGETS)}")
                        sys.exit(1)
                    targets.append(tgt)
                    i += 1

            parsed["tasks"].append({
                "type":    "mapping",
                "targets": targets,
            })

        else:
            print(f"[ERROR] Unexpected argument: '{token}'")
            print("Run  python pipeline.py  for full usage.")
            sys.exit(1)

    return parsed


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(0)

    start = time.time()

    parsed = parse_args(sys.argv[1:])

    with open(LOG_FILE, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"Pipeline started at {datetime.now().isoformat()}\n")
        print(f"[LOG] Output will be saved to: {LOG_FILE}")

        # --all: ingest + mapping + process + create-db + inject
        if parsed["all"]:
            for source in ALL_INGEST_SOURCES:
                run(INGEST_SCRIPTS[source], ["--all"], log_fh)
            for target in ALL_MAPPING_TARGETS:
                run(MAPPING_SCRIPTS[target], [], log_fh)
            run(PROCESS_SCRIPT, [], log_fh)
            run(CREATE_DB_SCRIPT, [], log_fh)
            run(INJECT_SCRIPT, [], log_fh)

        elif not parsed["tasks"] and not parsed["create_db"] and not parsed["inject"] and not parsed["process"]:
            msg = "[WARNING] Nothing to do.\nRun  python pipeline.py  for full usage."
            log(msg, log_fh)
            return

        else:
            # Run ingest/mapping tasks
            for task in parsed["tasks"]:
                if task["type"] == "ingest":
                    run(INGEST_SCRIPTS[task["source"]], task["args"], log_fh)
                elif task["type"] == "mapping":
                    for target in task["targets"]:
                        run(MAPPING_SCRIPTS[target], [], log_fh)

            # --process: regenerate processed CSVs
            if parsed["process"]:
                run(PROCESS_SCRIPT, [], log_fh)

            # --create-db: drop and recreate all tables
            if parsed["create_db"]:
                run(CREATE_DB_SCRIPT, [], log_fh)

            # --inject: inject processed CSVs into the database
            if parsed["inject"]:
                run(INJECT_SCRIPT, [], log_fh)

        elapsed = time.time() - start
        minutes, seconds = divmod(int(elapsed), 60)
        footer = (
            f"\n{'=' * 60}\n"
            f"  Pipeline completed in {minutes}m {seconds}s\n"
            f"{'=' * 60}"
        )
        log(footer, log_fh)
        log_fh.write(f"\nPipeline ended at {datetime.now().isoformat()}\n")


if __name__ == "__main__":
    main()