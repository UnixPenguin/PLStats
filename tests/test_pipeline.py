"""Checks on small synthetic data. Run with `python -m pytest tests` or `python tests/test_pipeline.py`."""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_pipeline as rp  # noqa: E402
from plstats import clean, formulas, pca, population, regression  # noqa: E402


def rows(*recs):
    """recs: (name, sex, bw, squat, bench, deadlift, date)"""
    df = pd.DataFrame(recs, columns=["Name", "Sex", "BodyweightKg", "Best3SquatKg", "Best3BenchKg",
                                     "Best3DeadliftKg", "Date"])
    df["Date"] = pd.to_datetime(df["Date"])
    df["TotalKg"] = df[["Best3SquatKg", "Best3BenchKg", "Best3DeadliftKg"]].sum(axis=1)
    for lift in ("Squat", "Bench", "Deadlift"):
        df[f"{lift}Pct"] = df[f"Best3{lift}Kg"] / df["TotalKg"]
    params = {"M": {"a": np.log(50), "b": 0.5}, "F": {"a": np.log(50), "b": 0.4}, "scale": 300.0}
    return rp.add_scores(df, params)


def test_repeated_lifter_counts_once():
    # A competes ten times at 500 kg; B and C once each. Per result, A would be 10 of 12 values.
    recs = [("A", "M", 83, 180, 120, 200, f"2024-01-{d:02d}") for d in range(1, 11)]
    recs += [("B", "M", 83, 140, 100, 160, "2024-02-01"), ("C", "M", 83, 100, 80, 120, "2024-03-01")]
    t = rp.percentile_tables(rows(*recs))["M"]
    allc = t["classes"]["All"]
    assert allc["n"] == 3
    assert allc["total"][0] == 300 and allc["total"][100] == 400 and allc["total"][-1] == 500
    assert t["scores_n"]["Dots"] == 3


def test_best_per_metric_can_come_from_different_meets():
    # A's best squat is at meet 1, best total at meet 2
    df = rows(("A", "M", 83, 250, 100, 150, "2024-01-01"), ("A", "M", 83, 200, 130, 250, "2024-06-01"),
              ("B", "M", 83, 100, 100, 100, "2024-01-01"))
    allc = rp.percentile_tables(df)["M"]["classes"]["All"]
    assert allc["squat"][-1] == 250 and allc["total"][-1] == 580 and allc["bench"][-1] == 130


def test_weight_classes_count_lifter_once_per_class():
    df = rows(("A", "M", 82, 200, 100, 200, "2024-01-01"), ("A", "M", 82.5, 210, 100, 200, "2024-02-01"),
              ("A", "M", 90, 220, 120, 230, "2024-06-01"))
    c = rp.percentile_tables(df)["M"]["classes"]
    assert c["83"]["n"] == 1 and c["83"]["total"][-1] == 510
    assert c["93"]["n"] == 1 and c["93"]["total"][-1] == 570
    assert c["All"]["n"] == 1


def test_ties_use_earliest_meet():
    df = rows(("A", "M", 83, 200, 100, 200, "2024-05-01"), ("A", "M", 83, 200, 100, 200, "2024-01-01"),
              ("A", "M", 83, 100, 100, 100, "2023-01-01"))
    best = population.best_rows(df, "Dots")
    assert len(best) == 1 and best["Date"].iloc[0] == pd.Timestamp("2024-01-01")


def test_missing_values_and_empty_groups():
    # 30 kg lifter: IPF GL undefined (as on OpenPowerlifting), other scores fine
    df = rows(("Kid", "F", 30, 60, 30, 70, "2024-01-01"), ("Adult", "F", 60, 120, 60, 140, "2024-01-01"))
    assert np.isnan(df.loc[0, "IPF_GL"]) and np.isfinite(df.loc[1, "IPF_GL"])
    t = rp.percentile_tables(df)
    assert t["F"]["scores_n"]["IPF GL"] == 1 and t["F"]["scores_n"]["Dots"] == 2
    assert t["F"]["classes"]["84+"] == {"n": 0, "squat": None, "bench": None, "deadlift": None, "total": None}
    assert t["M"]["classes"]["All"]["n"] == 0 and t["M"]["scores"]["Dots"] is None
    json.dumps(rp._finite(t), allow_nan=False)                     # must be valid JSON
    assert pca.profiles(df.assign(Year=2024)) == {"M": None, "F": None}
    assert regression.fit(df.assign(Age=25.0, Year=2024)) is None


def test_ipf_gl_matches_opl_rules():
    assert np.isnan(formulas.ipf_gl(300, 34.99, "F"))
    assert abs(formulas.ipf_gl(500, 83, "M") - 500 * 100 / (1199.72839 - 1025.18162 * np.exp(-0.00921 * 83))) < 1e-9


def test_division_matching():
    keep = ["Open", "MR-O", "FR-O", "M-O", "Amateur Open", "Pro Open", "OpenT", "TOpen", "Juniors",
            "MR-Jr", "Juniors 20-23", "Juniors 18-19", "J20-23", "MR-C", "Collegiate", "Seniors", "SNR",
            "M-OR", "F-OR", "MOR", "O", "Police Amateur Open", "Open J23"]
    drop = ["Masters 1", "Sub-Juniors", "Juniors 13-15", "Juniors 16-17", "Juniorzy do lat 16",
            "Junior Varsity", "Open M1", "Open J18", "Guest Open", "Adaptive Open", "Special Olympics Open",
            "Teen 14-18", "Open Masters", "", None, "Boys", "MR-T3"]
    got = clean.core_division(pd.Series(keep + drop)).tolist()
    assert got == [True] * len(keep) + [False] * len(drop), [d for d, g, w in
        zip(keep + drop, got, [True] * len(keep) + [False] * len(drop)) if g != w]


def test_clustered_se_ignores_duplicated_rows():
    rng = np.random.default_rng(0)
    n = 400
    x = rng.normal(size=n)
    y = 1 + 0.5 * x + rng.normal(size=n)
    X = np.column_stack([np.ones(n), x])
    _, se1, *_ = regression._ols(X, y, np.arange(n))
    k = 5                                           # every lifter appears 5 times with the same result
    Xk, yk, g = np.repeat(X, k, axis=0), np.repeat(y, k), np.repeat(np.arange(n), k)
    _, sek, _, _, se_iid = regression._ols(Xk, yk, g)
    assert np.allclose(sek, se1, rtol=0.01)          # clustered SE: repeats add no information
    assert np.all(se_iid < se1 / 2)                   # naive SE would claim ~sqrt(5)x more precision


def _stats(snapshot, a_m, gen="2026-01-01"):
    p = {s: {"a": a_m if s == "M" else 4.0, "A": float(np.exp(a_m)), "b": 0.5, "n": 10, "n_lifters": 5}
         for s in ("M", "F")}
    p.update(scale=300.0, scale_n_lifters=10, method="v2")
    return {"meta": {"generated": gen, "snapshot": snapshot, "source_file": "x.csv", "data_from": "a",
                     "data_to": "b"}, "scoring": {"params": p}}


def test_nscore_history_is_append_only():
    with tempfile.TemporaryDirectory() as tmp:
        pub = Path(tmp)
        h1 = rp.update_history(pub, _stats("2026-01-03", 4.0))
        assert len(h1["fits"]) == 1 and h1["fits"][0]["id"] == 1
        (pub / rp.HISTORY).write_text(json.dumps(h1))
        # same snapshot, same fit, run again on a later day: nothing added, original date kept
        h2 = rp.update_history(pub, _stats("2026-01-03", 4.0, gen="2026-01-05"))
        assert h2["fits"] == h1["fits"]
        # next week: appended, earlier entry untouched
        h3 = rp.update_history(pub, _stats("2026-01-10", 4.1, gen="2026-01-12"))
        assert len(h3["fits"]) == 2 and h3["fits"][0] == h1["fits"][0] and h3["fits"][1]["id"] == 2
        assert h3["fits"][1]["coefficients"]["M"]["ln_a"] == 4.1 and h3["fits"][1]["fit_date"] == "2026-01-12"


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} tests passed")
