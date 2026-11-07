"""Load the OpenPowerlifting CSV and keep a comparable population.

Glossary (for readers new to powerlifting)
------------------------------------------
* Full meet / SBD  - the lifter competed in all three lifts: Squat, Bench, Deadlift.
* Total            - best successful squat + bench + deadlift.
* Raw              - no supportive suits/shirts (knee sleeves and belts only).
* Tested           - the federation drug-tests its athletes.
* DQ               - "disqualified": the lifter was removed from the results,
                     e.g. a failed drug test or a rule violation.  In the data
                     the Place column is "DQ" instead of a number.
* Bomb-out         - the lifter missed all three attempts on one lift, so that
                     lift counts as 0 and there is no valid total.  OPL also
                     marks these with a non-numeric Place ("DQ").
* NS / G           - "no-show" / "guest lifter" (not ranked).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, formulas

COLS = [
    "Name", "Sex", "Event", "Equipment", "Age", "Division", "BodyweightKg",
    "Best3SquatKg", "Best3BenchKg", "Best3DeadliftKg", "TotalKg", "Place",
    "Dots", "Wilks", "Goodlift", "Tested", "Country", "Federation", "Date",
]


def clean(raw_csv) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    """Returns (default population, cleaning steps for it, wider pool).

    The default population is US + drug-tested + raw + Open/Junior/Collegiate.
    The wider pool also keeps other countries, untested federations, lifters in
    knee wraps and every age division, with boolean flag columns (IsUS,
    IsTested, IsRaw, IsCoreDiv) so the website can offer other comparison groups.
    """
    df = pd.read_csv(raw_csv, usecols=COLS, parse_dates=["Date"], low_memory=False)
    n_all = len(df)

    flags = {
        "IsUS": (df["Country"] == "USA").values,
        "IsTested": (df["Tested"] == "Yes").values,
        "IsRaw": (df["Equipment"] == "Raw").values,
        "IsCoreDiv": core_division(df["Division"]).values,
    }
    sbd = (df["Event"] == "SBD").values
    # Window relative to the newest full-power meet in the file, so re-running
    # the pipeline later on the same CSV gives the same result.
    cutoff = df.loc[sbd, "Date"].max() - pd.DateOffset(years=config.YEARS_WINDOW)

    # A lift that is < 15% of the total is almost always a "token" lift taken
    # only to register a total (e.g. a bench specialist opening the squat with
    # 60 kg).  Those rows would pull the strength-profile analysis to the edges.
    s, t = config.MIN_LIFT_SHARE, df["TotalKg"]
    shares_ok = ((df["Best3SquatKg"] > 0) & (df["Best3BenchKg"] > 0) & (df["Best3DeadliftKg"] > 0)
                 & (df["Best3SquatKg"] / t >= s) & (df["Best3BenchKg"] / t >= s)
                 & (df["Best3DeadliftKg"] / t >= s)).values

    # Steps reported for the default population, in the order they are applied.
    ordered = [
        ("US lifters only", flags["IsUS"]),
        ("Drug-tested federations", flags["IsTested"]),
        ("Raw (unequipped)", flags["IsRaw"]),
        ("Full meet (squat + bench + deadlift)", sbd),
        (f"Last {config.YEARS_WINDOW} years", (df["Date"] >= cutoff).values),
        ("Open / Junior / Collegiate divisions", flags["IsCoreDiv"]),
        ("Drop DQ, bomb-outs, no-shows, guests", pd.to_numeric(df["Place"], errors="coerce").notna().values),
        (f"Every lift >= {s:.0%} of total", shares_ok),
        ("Bodyweight recorded, sex M/F", (df["BodyweightKg"].notna() & df["Sex"].isin(["M", "F"])).values),
    ]
    steps = [{"step": "Full OpenPowerlifting dataset", "rows": n_all}]
    keep = np.ones(n_all, dtype=bool)
    for label, m in ordered:
        keep &= m
        steps.append({"step": label, "rows": int(keep.sum())})

    # Pool: same quality filters, but optional cohort filters relaxed.
    pool_mask = np.ones(n_all, dtype=bool)
    for label, m in ordered:
        if label in ("US lifters only", "Drug-tested federations", "Open / Junior / Collegiate divisions"):
            continue
        if label == "Raw (unequipped)":
            m = df["Equipment"].isin(["Raw", "Wraps"]).values
        pool_mask &= m

    pool = df[pool_mask].copy()
    for k, v in flags.items():
        pool[k] = v[pool_mask]
    for lift in ("Squat", "Bench", "Deadlift"):
        pool[f"{lift}Pct"] = pool[f"Best3{lift}Kg"] / pool["TotalKg"]
    pool["Year"] = pool["Date"].dt.year
    pool["Dots"] = formulas.dots(pool["TotalKg"].values, pool["BodyweightKg"].values, pool["Sex"].values)
    pool = pool.sort_values(["Name", "Date"]).reset_index(drop=True)

    default = pool[pool["IsUS"] & pool["IsTested"] & pool["IsRaw"] & pool["IsCoreDiv"]].reset_index(drop=True)
    assert len(default) == steps[-1]["rows"]
    return default, steps, pool


# Division names are free text, one convention per federation. Audited against the 2026-10-31 snapshot:
# * "Open" also appears inside youth, masters, guest and adaptive divisions ("Open J18", "Open M1",
#   "Guest Open", "Adaptive Open", "Special Olympics Open"); those are excluded.
# * Open divisions without "open" as a separate word were missed: "OpenT"/"TOpen" (USPA and USPC tested
#   open), "O", "MO", "M-OR", "F-OR", "MOR", and "Senior(s)"/"SNR"/"Seniorzy"/"Seniorki", which several
#   European federations use for the open age class.
# * "Junior" also names youth groups ("Juniors 13-15", "Juniors 16-17", "Juniorzy do lat 16",
#   "Junior Varsity"); juniors whose upper age limit is under 18 are excluded.
# Police, military, fire and amateur/pro "Open" divisions are open-age and stay in.
_DIV_EXCLUDE = (r"master|\bm[1-4]\b|\bj1[0-8]\b|teen|youth|\bsub|varsity|high ?school|\bhs\b|guest|"
                r"adaptive|\bpara|disabled|special olympics|\bso\b")


def core_division(division: pd.Series) -> pd.Series:
    """True for Open, Junior (18+) and Collegiate divisions (see the audit note above)."""
    div = division.fillna("").str.strip()
    low = div.str.lower()
    is_open = (low.str.contains(r"(?<![a-z])t?opent?(?![a-z])", regex=True)
               | div.str.match(r"^(?:[MF]R?-O|[MF]-?OR?|O)$")
               | low.str.match(r"^(?:seniors?|seniorzy|seniorki|snr)$"))
    is_junior = (low.str.contains("junior") | div.str.match(r"^[MF]R?-Jr$")
                 | low.str.match(r"^j ?(?:18|19|20)-2[34]$"))
    is_coll = div.str.match(r"^[MF]R?-C$") | low.str.contains("collegiate")
    # upper age limit written in the name: "13-15" -> 15, "do lat 16" (Polish "under 16") -> 15
    upper = pd.to_numeric(low.str.extract(r"\b\d{2}\s?-\s?(\d{2})\b")[0], errors="coerce")
    under = pd.to_numeric(low.str.extract(r"do lat (\d{2})")[0], errors="coerce") - 1
    youth = (upper.fillna(99) < 18) | (under.fillna(99) < 18)
    return (is_open | is_junior | is_coll) & ~low.str.contains(_DIV_EXCLUDE, regex=True) & ~youth


def weight_class(bw, sex):
    """IPF weight-class label, e.g. '83' or '120+'."""
    for c in config.WEIGHT_CLASSES[sex]:
        if bw <= c:
            return str(c)
    return f"{config.WEIGHT_CLASSES[sex][-1]}+"
