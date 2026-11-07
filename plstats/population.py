"""Count each lifter once.

OpenPowerlifting has one row per lifter per meet, and also one row per *division* when a lifter entered
several at the same meet (e.g. Open and Junior). Frequent competitors would otherwise count many times in a
percentile. Every percentile, histogram, profile map and sample count on the site therefore uses one value
per lifter: their best result for that metric in the comparison group and time window.

* Total uses the lifter's best total, Dots their best Dots, squat their best squat, and so on, so the
  "best" row can differ between metrics.
* Weight-class tables use the lifter's best result *in that class*; a lifter who competed in two classes
  counts once in each.
* Ties (the same best value at several meets) don't change the value; where a row is needed (the profile
  map), the earliest such meet is used.
* Missing values (e.g. IPF GL below 35 kg bodyweight) are ignored; a lifter with no valid value for a
  metric is left out of that metric only.
* Lifters are identified by OpenPowerlifting's Name, which already carries "#1", "#2" ... for different
  people with the same name, so one lifter across federations, divisions and equipment counts once.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def best_values(df: pd.DataFrame, col: str) -> pd.Series:
    """Each lifter's best (largest) value of `col`, missing values ignored."""
    v = df[["Name", col]].replace([np.inf, -np.inf], np.nan).dropna()
    return v.groupby("Name", sort=False)[col].max()


def best_rows(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """The row of each lifter's best `col`; ties go to the earliest meet."""
    d = df[np.isfinite(df[col].astype(float))].sort_values(["Name", "Date"], kind="stable")
    return d.loc[d.groupby("Name", sort=False)[col].idxmax()]


def lifter_weights(names) -> np.ndarray:
    """1 / (number of rows of that lifter): each lifter's rows add up to a total weight of 1."""
    s = pd.Series(np.asarray(names))
    return (1.0 / s.map(s.value_counts())).to_numpy()
