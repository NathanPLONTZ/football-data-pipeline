"""
common.py
---------
Helpers shared by the ingestion, mapping and processing scripts.

Everything here was previously duplicated across several scripts. Only
strictly identical behaviour was centralised: the two `normalize_name`
variants in the mapping scripts intentionally differ in how they treat
digits, so only their shared accent-stripping step lives here.
"""

import csv
import json
import unicodedata

import requests


# -----------------------------------------------------------------------------
# CONSOLE OUTPUT
# -----------------------------------------------------------------------------

def print_separator(char="=", width=80):
    """Print a single separator line."""
    print(char * width)


def print_section(title):
    """Print a section title framed by separator lines."""
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


# -----------------------------------------------------------------------------
# FILE I/O
# -----------------------------------------------------------------------------

def save_json(path, data):
    """Write data as indented UTF-8 JSON, keeping non-ASCII characters as-is."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_csv_rows(path, fieldnames, rows):
    """Write a list of dicts to a CSV file, header included."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# -----------------------------------------------------------------------------
# HTTP
# -----------------------------------------------------------------------------

def api_get(url, auth, params=None):
    """
    Authenticated REST GET returning (data, status_code).

    `auth` is a (username, password) tuple. On any non-200 response the data
    is None so the caller can report the status code itself.
    """
    response = requests.get(
        url,
        params=params,
        auth=auth,
        headers={"accept": "application/json"},
    )
    if response.status_code == 200:
        return response.json(), 200
    return None, response.status_code


# -----------------------------------------------------------------------------
# TEXT NORMALISATION
# -----------------------------------------------------------------------------

def strip_accents_lower(name):
    """
    Remove diacritics and lowercase a name.

    Shared first step of the team and player name normalisation; each mapping
    script then applies its own punctuation rules on top.
    """
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFD", name)
    without_marks = "".join(
        c for c in decomposed if unicodedata.category(c) != "Mn"
    )
    return without_marks.lower()
