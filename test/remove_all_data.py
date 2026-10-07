"""
remove_all_data.py
------------------
Recursively deletes all files in the data/ folder.
Folder structure is preserved (empty directories remain).

USAGE
-----
  python test/remove_all_data.py           # deletes all files immediately
  python test/remove_all_data.py --dry-run # lists what would be deleted
"""

import sys
from pathlib import Path

ROOT      = Path(__file__).resolve().parent.parent
DATA_DIR  = ROOT / "data"


def main():
    dry_run = "--dry-run" in sys.argv

    if not DATA_DIR.exists():
        print(f"[ERROR] Directory not found: {DATA_DIR}")
        sys.exit(1)

    # Collect all files recursively
    files = list(DATA_DIR.rglob("*"))
    files = [f for f in files if f.is_file()]

    if not files:
        print("Nothing to delete, data/ is already empty.")
        return

    print(f"{'[DRY-RUN] ' if dry_run else ''}Files to delete ({len(files)}):")
    for f in files:
        print(f"  {f.relative_to(ROOT)}")

    if dry_run:
        print("\n[DRY-RUN] No files were deleted.")
        return

    deleted = 0
    for f in files:
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            print(f"[ERROR] Could not delete {f}: {e}")

    print(f"\n{deleted} file(s) deleted.")


if __name__ == "__main__":
    main()