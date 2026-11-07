"""Paths and analysis settings. Everything is relative to the repo root."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"                 # raw + cleaned data (git-ignored)
FIG_DIR = ROOT / "figures"               # static figures for the write-up
WEB_DATA = ROOT / "docs" / "data" / "stats.json"   # consumed by the web page
RESULTS_TXT = ROOT / "results" / "summary.md"

CLEAN_PARQUET = DATA_DIR / "openpowerlifting_clean.parquet"

# Cleaning
YEARS_WINDOW = 10        # keep meets from the last N years *of the dataset*
MIN_LIFT_SHARE = 0.15    # each lift must be >= 15% of the total (see clean.py)

# IPF weight classes (kg). Last class is "+" (e.g. 120+).
WEIGHT_CLASSES = {
    "M": [59, 66, 74, 83, 93, 105, 120],
    "F": [47, 52, 57, 63, 69, 76, 84],
}

# Well-known lifters drawn on the PCA plots as sanity checks (public results).
HIGHLIGHT_LIFTERS = {
    "M": ["Austin Perkins #1", "Jesus Olivares", "Bobb Matthews", "Ashton Rouska"],
    "F": ["Tamara Walcott", "Amanda Lawrence #1"],
}

# Most lifters a visitor can put on one profile map.
MAX_MAP_LIFTERS = 5

SEED = 42
