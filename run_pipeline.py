"""Run the whole PLStats analysis and export data for the web page.

    python run_pipeline.py                         # uses data/openpowerlifting-*.csv
    python run_pipeline.py --csv path/to/opl.csv   # explicit file
    python run_pipeline.py --no-figures            # skip the PNGs (the weekly refresh does this)

Outputs
    data/openpowerlifting_clean.parquet    cleaned rows (git-ignored)
    figures/*.png                          static figures
    docs/data/stats.json                   everything the web page needs
    docs/data/cohorts/, docs/data/lifters/ comparison groups and the lifter search index
    docs/data/nscore_history.json          every N-Score fit ever published (append-only)
    results/summary.md                     numeric results in plain text

Everything is first written to build/ (git-ignored) and checked by validate(). Only when every check
passes are docs/data and figures/ swapped for the new versions and the README and summary rewritten, so a
failed or partial run never leaves a mix of old and new files.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import shutil
import sys
import unicodedata
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from plstats import clean, config, formulas, pca, plotting, population, regression, scoring

Q = np.linspace(0, 1, 201)          # percentile grid exported for the web page
BUILD = config.ROOT / "build"        # staging area (git-ignored)
WEB_DIR = config.WEB_DATA.parent     # docs/data
HISTORY = "nscore_history.json"
DEFAULT_COHORT = "us-tested-raw-core"


def quantiles(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return np.quantile(x, Q).round(2).tolist() if len(x) else None


LIFT_COLS = [("squat", "Best3SquatKg"), ("bench", "Best3BenchKg"), ("deadlift", "Best3DeadliftKg"),
             ("total", "TotalKg")]


def percentile_tables(df):
    """Percentiles with each lifter counted once: their best value of each metric (see population.py).
    In a weight-class table it is their best in that class. Empty groups get n = 0 and null quantiles."""
    out = {}
    for sex in ("M", "F"):
        sub = df[df["Sex"] == sex]
        bounds = config.WEIGHT_CLASSES[sex]
        labels = [str(c) for c in bounds] + [f"{bounds[-1]}+"]
        idx = np.searchsorted(bounds, sub["BodyweightKg"].values, side="left")
        groups = {"All": sub, **{c: sub[idx == i] for i, c in enumerate(labels)}}
        scores = {k: population.best_values(sub, col) for k, col in scoring.SCORES.items()}
        out[sex] = {
            "classes": {c: {"n": int(g["Name"].nunique()),
                            **{k: quantiles(population.best_values(g, col)) for k, col in LIFT_COLS}}
                        for c, g in groups.items()},
            "scores": {k: quantiles(v) for k, v in scores.items()},
            "scores_n": {k: int(len(v)) for k, v in scores.items()},
        }
    return out


def add_scores(d, params):
    sx, bw, tot = d["Sex"].values, d["BodyweightKg"].values, d["TotalKg"].values
    return d.assign(Wilks=formulas.wilks(tot, bw, sx), Dots=formulas.dots(tot, bw, sx),
                    IPF_GL=formulas.ipf_gl(tot, bw, sx), NScore=formulas.nscore(tot, bw, sx, params))


# Comparison groups offered on the website. Each option maps to a row filter
# on the flagged pool from clean.clean(); None means "don't filter".
COHORT_DIMS = {
    "region": {"us": "IsUS", "world": None},
    "testing": {"tested": "IsTested", "all": None},
    "equipment": {"raw": "IsRaw", "wraps": None},      # "wraps" = raw + knee wraps
    "ages": {"core": "IsCoreDiv", "all": None},
}


def name_key(name):
    """Detail-file key: first two letters of the name, accents removed (the web page computes the same)."""
    letters = "".join(c for c in unicodedata.normalize("NFKD", name).lower() if "a" <= c <= "z")
    return (letters + "__")[:2]


def lifter_row(r):
    return [r.Sex, round(r.SquatPct * 1000), round(r.BenchPct * 1000), round(r.DeadliftPct * 1000),
            float(r.TotalKg), round(float(r.BodyweightKg), 1), round(float(r.Dots), 1), r.Federation,
            int(r.Year), 1 if r.Equipment == "Wraps" else 0, r.Country if isinstance(r.Country, str) else ""]


def export_lifters(pool, out):
    """Every lifter's best full-power meet (by Dots) from the pool: raw or knee wraps, last ten years, any
    country, federation or division. Only public results already on OpenPowerlifting.

    lifters/names.txt   one "sex<TAB>name" line per lifter, strongest first (searched in the browser)
    lifters/<ab>.json   details for every lifter whose name starts with "ab", fetched on demand
    Returns the default map lifters' details for stats.json, so the page can draw them straight away."""
    best = population.best_rows(pool, "Dots").sort_values(["Dots", "Name"], ascending=[False, True], kind="stable")
    best = best[~best["Name"].str.contains(r"[\t\r\n]", regex=True)]
    out.mkdir(parents=True, exist_ok=True)
    (out / "names.txt").write_text("".join(f"{sx}\t{n}\n" for sx, n in zip(best["Sex"], best["Name"])),
                                   encoding="utf-8", newline="\n")
    shards = {}
    for r in best.itertuples():
        shards.setdefault(name_key(r.Name), {})[r.Name] = lifter_row(r)
    for k, v in shards.items():
        (out / f"{k}.json").write_text(json.dumps(v, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    defaults = sum(config.HIGHLIGHT_LIFTERS.values(), [])
    print(f"  {len(best):,} lifters in {len(shards)} files")
    return {r.Name: lifter_row(r) for r in best[best["Name"].isin(defaults)].itertuples()}, len(best)


def export_cohorts(pool, params, hist_edges, out, snapshot):
    pool = add_scores(pool, params)
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    for combo in itertools.product(*[list(v.items()) for v in COHORT_DIMS.values()]):
        key = "-".join(k for k, _ in combo)
        mask = np.ones(len(pool), dtype=bool)
        for _, col in combo:
            if col:
                mask &= pool[col].values
        d = pool[mask]
        hist = {}
        for label, col in scoring.SCORES.items():
            e = np.array(hist_edges[label])
            hist[label] = {}
            for s in ("M", "F"):
                v = population.best_values(d[d["Sex"] == s], col)       # one value per lifter
                hist[label][s] = np.histogram(v, bins=e, density=True)[0].round(6).tolist() if len(v) else None
        res = {"key": key, "snapshot": snapshot, "n_rows": int(len(d)), "n_lifters": int(d["Name"].nunique()),
               "n_by_sex": d["Sex"].value_counts().to_dict(),
               "n_lifters_by_sex": d.groupby("Sex")["Name"].nunique().to_dict(),
               "percentiles": percentile_tables(d), "regression": regression.fit(d),
               "pca": pca.profiles(d), "hist": hist}
        write_json(out / f"{key}.json", res)
        index[key] = {"n_rows": res["n_rows"], "n_lifters": res["n_lifters"]}
        print(f"  {key:<24} {res['n_lifters']:>8,} lifters {len(d):>9,} results")
    return index


def _finite(o):
    """NaN/inf are not valid JSON; replace with null."""
    if isinstance(o, dict):
        return {str(k): _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    return o


def write_json(path, obj, indent=None):
    """allow_nan=False: a NaN that slipped past _finite() fails the run instead of breaking the page."""
    sep = None if indent else (",", ":")
    path.write_text(json.dumps(_finite(obj), allow_nan=False, indent=indent, separators=sep), encoding="utf-8",
                    newline="\n")


# ------------------------------------------------------------------ N-Score history
def history_entry(stats):
    p, m = stats["scoring"]["params"], stats["meta"]
    return {
        "fit_date": m["generated"], "snapshot": m["snapshot"], "source_file": m["source_file"],
        "data_from": m["data_from"], "data_to": m["data_to"], "population": DEFAULT_COHORT,
        "method": p.get("method", ""), "scale": p["scale"], "scale_quantile": 0.99,
        "scale_n_lifters": p.get("scale_n_lifters"),
        "coefficients": {s: {"ln_a": p[s]["a"], "a": p[s]["A"], "b": p[s]["b"],
                             "n_results": p[s]["n"], "n_lifters": p[s].get("n_lifters")} for s in ("M", "F")},
    }


def _same_fit(a, b):
    return (a["snapshot"] == b["snapshot"] and a["method"] == b["method"]
            and np.isclose(a["scale"], b["scale"], rtol=1e-9)
            and all(np.isclose(a["coefficients"][s][k], b["coefficients"][s][k], rtol=1e-9)
                    for s in ("M", "F") for k in ("ln_a", "b")))


def update_history(published_dir, stats):
    """Append this run's N-Score fit to the published history. Earlier entries are never changed or
    removed. Re-running on the same snapshot with the same code adds nothing."""
    path = published_dir / HISTORY
    if path.exists():
        hist = json.loads(path.read_text(encoding="utf-8"))      # unreadable history: fail, don't overwrite
    else:
        hist = {"fits": []}
        old = published_dir / "stats.json"
        if old.exists():                                         # first run with history: keep the fit in use
            prev = json.loads(old.read_text(encoding="utf-8"))
            e = history_entry(prev)
            if not e["method"]:
                e["method"] = ("v1: ln(Total) = ln(a) + b*ln(BW) by unweighted least squares over all results; "
                               "scale = 500 / 99th percentile of Total/(a*BW^b) over all results, both sexes")
            hist["fits"].append(e)
    hist["about"] = ("Every N-Score fit PLStats has published, oldest first. N-Score = Total / (a * BW^b) * scale, "
                     "with a and b per sex. The fit is redone on each data refresh, so a score is only exactly "
                     "comparable with scores from the same fit (same id).")
    new = history_entry(stats)
    if not hist["fits"] or not _same_fit(hist["fits"][-1], new):
        hist["fits"].append(new)
    for i, f in enumerate(hist["fits"]):
        f.setdefault("id", i + 1)
    hist["fits"][-1]["id"] = len(hist["fits"])
    return hist


# ------------------------------------------------------------------ checks before publishing
def validate(stage, stats, published_dir):
    """Raise SystemExit if the staged output is incomplete or inconsistent."""
    errors = []
    snap = stats["meta"]["snapshot"]
    for key in stats["cohorts"]["index"]:
        f = stage / "cohorts" / f"{key}.json"
        if not f.exists():
            errors.append(f"missing cohort {key}")
            continue
        c = json.loads(f.read_text(encoding="utf-8"))
        if c.get("snapshot") != snap:
            errors.append(f"cohort {key} is from snapshot {c.get('snapshot')}, not {snap}")
    f = stage / "pca3d.json"
    if not f.exists() or json.loads(f.read_text(encoding="utf-8")).get("snapshot") != snap:
        errors.append("pca3d.json missing or from another snapshot")
    if stats["cohorts"]["default"] not in stats["cohorts"]["index"]:
        errors.append("default cohort missing")

    names = (stage / "lifters" / "names.txt").read_text(encoding="utf-8").splitlines()
    if len(names) != stats["meta"]["n_searchable_lifters"]:
        errors.append("names.txt line count does not match n_searchable_lifters")
    shards = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in (stage / "lifters").glob("*.json")}
    missing = [n for n in (ln.split("\t", 1)[1] for ln in names) if n not in shards.get(name_key(n), {})]
    if missing:
        errors.append(f"{len(missing)} searchable lifters have no detail row, e.g. {missing[:3]}")

    hist = json.loads((stage / HISTORY).read_text(encoding="utf-8"))
    if not _same_fit(hist["fits"][-1], history_entry(stats)):
        errors.append("latest N-Score history entry does not match stats.json")
    if (published_dir / HISTORY).exists():
        old = json.loads((published_dir / HISTORY).read_text(encoding="utf-8"))["fits"]
        if hist["fits"][:len(old)] != old:
            errors.append("N-Score history would change or drop earlier entries")

    if (published_dir / "stats.json").exists():
        prev = json.loads((published_dir / "stats.json").read_text(encoding="utf-8"))["meta"]
        if prev.get("snapshot", "") > snap:
            errors.append(f"snapshot {snap} is older than the published {prev['snapshot']}")
        if stats["meta"]["n_rows"] < 0.9 * prev["n_rows"]:
            errors.append(f"default group shrank from {prev['n_rows']:,} to {stats['meta']['n_rows']:,} results "
                          "(truncated download?)")
    if errors:
        raise SystemExit("Not publishing, checks failed:\n  " + "\n  ".join(errors))
    print("  all checks passed")


def _swap(new, target):
    """Replace directory `target` with `new`, keeping the old one until the new one is in place."""
    old = target.with_name(target.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    if target.exists():
        target.rename(old)
    try:
        new.rename(target)
    except Exception:
        if old.exists():
            old.rename(target)
        raise
    if old.exists():
        shutil.rmtree(old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="OpenPowerlifting CSV (default: newest in data/)")
    ap.add_argument("--no-figures", action="store_true", help="don't regenerate figures/*.png")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")       # Windows consoles can't print every character
    csv = args.csv or max(config.DATA_DIR.glob("openpowerlifting-*.csv"), default=None)
    if csv is None:
        raise SystemExit("No CSV found. Run scripts/download_data.py or pass --csv.")

    if BUILD.exists():
        shutil.rmtree(BUILD)
    stage = BUILD / "data"
    stage.mkdir(parents=True)
    plotting.ENABLED = not args.no_figures
    config.FIG_DIR = BUILD / "figures"

    print(f"Cleaning {csv} ...")
    df, steps, pool = clean.clean(csv)
    config.DATA_DIR.mkdir(exist_ok=True)
    df.to_parquet(config.CLEAN_PARQUET, index=False)
    print(f"  {len(df):,} meet results, {df['Name'].nunique():,} lifters")

    print("PCA ...")
    pca_out = pca.run(df)
    cloud = pca_out.pop("cloud")
    print("Scoring formulas ...")
    df, score_out = scoring.run(df)
    print("Regression ...")
    reg_out = regression.run(df)

    snap = snapshot_date(csv, df)
    prev_meta = {}
    if config.WEB_DATA.exists():
        prev_meta = json.loads(config.WEB_DATA.read_text(encoding="utf-8")).get("meta", {})
    stats = {
        "meta": {"generated": date.today().isoformat(), "source_file": Path(csv).name,
                 "snapshot": snap,
                 "data_from": df["Date"].min().date().isoformat(),
                 "data_to": df["Date"].max().date().isoformat(),
                 "n_rows": int(len(df)), "n_lifters": int(df["Name"].nunique()),
                 "n_by_sex": df["Sex"].value_counts().to_dict(),
                 "n_lifters_by_sex": df.groupby("Sex")["Name"].nunique().to_dict(),
                 "weight_classes": config.WEIGHT_CLASSES, "q": Q.round(3).tolist(),
                 "cleaning": steps,
                 "figures_snapshot": snap if plotting.ENABLED else prev_meta.get("figures_snapshot",
                                                                                 prev_meta.get("snapshot"))},
        "pca": pca_out, "scoring": score_out, "regression": reg_out,
    }
    print("Lifter search index ...")
    stats["lifters"], n_search = export_lifters(pool, stage / "lifters")
    stats["meta"]["default_lifters"] = config.HIGHLIGHT_LIFTERS
    stats["meta"]["n_searchable_lifters"] = n_search
    stats["meta"]["max_map_lifters"] = config.MAX_MAP_LIFTERS
    print("Comparison groups ...")
    stats["cohorts"] = {"dims": {k: list(v) for k, v in COHORT_DIMS.items()},
                        "default": DEFAULT_COHORT,
                        "index": export_cohorts(pool, score_out["params"],
                                                {k: v["edges"] for k, v in score_out["hist"].items()},
                                                stage / "cohorts", snap)}
    hist = update_history(WEB_DIR, stats)
    fit = hist["fits"][-1]
    stats["meta"]["nscore_fit"] = {"id": fit["id"], "fit_date": fit["fit_date"], "snapshot": fit["snapshot"],
                                   "n_fits": len(hist["fits"])}
    write_json(stage / HISTORY, hist, indent=1)
    write_json(stage / "stats.json", stats)
    write_json(stage / "pca3d.json", {"snapshot": snap, **cloud})
    print(f"Staged {stage} (stats.json {(stage / 'stats.json').stat().st_size / 1e3:.0f} kB)")

    print("Checking ...")
    validate(stage, stats, WEB_DIR)
    summary = summary_text(stats)
    readme = readme_text(stats)

    print("Publishing ...")
    _swap(stage, WEB_DIR)
    if plotting.ENABLED:
        _swap(BUILD / "figures", config.ROOT / "figures")
    config.RESULTS_TXT.parent.mkdir(exist_ok=True)
    config.RESULTS_TXT.write_text(summary, encoding="utf-8")
    (config.ROOT / "README.md").write_text(readme, encoding="utf-8")
    shutil.rmtree(BUILD, ignore_errors=True)
    print(summary)
    print("Updated docs/data, README.md and results/summary.md" + (", figures/" if plotting.ENABLED else ""))


def snapshot_date(csv, df):
    """OPL names its files openpowerlifting-YYYY-MM-DD.csv; fall back to the newest meet."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", Path(csv).name)
    return m.group(1) if m else df["Date"].max().date().isoformat()


def readme_text(s):
    """README.md with the block between the DATA-START / DATA-END markers rewritten."""
    text = (config.ROOT / "README.md").read_text(encoding="utf-8")
    m, sc, r = s["meta"], s["scoring"], s["regression"]
    ev = {e["formula"]: e for e in sc["evaluation"]}
    nf, nl = m["nscore_fit"], m["n_lifters_by_sex"]
    block = "\n".join([
        "## Current data", "",
        f"**OpenPowerlifting snapshot: {m['snapshot']}** · meets from {m['data_from']} to {m['data_to']} · "
        f"default group (US, drug-tested, raw): {m['n_lifters']:,} lifters ({nl.get('M', 0):,} men, {nl.get('F', 0):,} women) "
        f"with {m['n_rows']:,} results · last refreshed {m['generated']}", "",
        "| Key result | Men | Women |", "|---|---:|---:|",
        f"| N-Score version {nf['id']} ({nf['fit_date']}): Total = a · BW^b | "
        f"{sc['params']['M']['A']:.2f} · BW^{sc['params']['M']['b']:.3f} | "
        f"{sc['params']['F']['A']:.2f} · BW^{sc['params']['F']['b']:.3f} |",
        f"| N-Score correlation with bodyweight | {ev['N-Score']['corr_bw_M']:+.3f} | {ev['N-Score']['corr_bw_F']:+.3f} |",
        f"| Dots correlation with bodyweight | {ev['Dots']['corr_bw_M']:+.3f} | {ev['Dots']['corr_bw_F']:+.3f} |",
        *[f"| Spread of the {k} ratio (variance of its log) | {s['pca']['by_sex']['M']['logratio_var'][k]:.4f} | "
          f"{s['pca']['by_sex']['F']['logratio_var'][k]:.4f} |" for k in ("squat/deadlift", "squat/bench", "deadlift/bench")],
        "",
        "The smaller the spread, the more alike lifters are in that ratio.",
        "",
        f"Mean of lifters' best scores, men ÷ women: N-Score {ev['N-Score']['mf_ratio_mean']:.3f}, "
        f"Dots {ev['Dots']['mf_ratio_mean']:.3f}. "
        f"Regression: R² = {r['r2_log']:.3f}, typical error {r['rmse_kg']:.0f} kg, "
        f"peak age {r['peak_age']:.1f} (from comparing lifters of different ages, not following anyone over time). "
        "Unique ΔR²: " + ", ".join(f"{k.lower()} {v:.3f}" for k, v in
                                   sorted(r["unique_r2"].items(), key=lambda kv: -kv[1])) + ".", "",
        f"Charts in [`figures/`](figures/) are from snapshot {m['figures_snapshot']}.",
    ])
    new, n = re.subn(r"(<!-- DATA-START[^>]*-->\n).*?(<!-- DATA-END -->)",
                     lambda mm: mm.group(1) + block + "\n" + mm.group(2), text, flags=re.S)
    if n != 1:
        raise SystemExit("README.md is missing the DATA-START / DATA-END markers.")
    return new


def summary_text(s):
    m = s["meta"]
    L = ["# PLStats results", "", f"Data: {m['data_from']} to {m['data_to']} (snapshot {m['snapshot']}), "
         f"{m['n_rows']:,} results from {m['n_lifters']:,} lifters. Percentiles, histograms, the profile map "
         "and the formula evaluation count each lifter once (their best result for that metric).", "",
         "## Cleaning", "", "| Step | Rows left |", "|---|---:|"]
    L += [f"| {st['step']} | {st['rows']:,} |" for st in m["cleaning"]]

    p = s["pca"]
    L += ["", "## PCA (one row per lifter: best meet by Dots)", "", "Raw kg (z-scored) variance explained: " +
          ", ".join(f"PC{i+1} {v:.1%}" for i, v in enumerate(p["raw"]["explained"]))]
    for sex, d in p["by_sex"].items():
        L += ["", f"### Lift log-ratios (clr), {sex} (n = {d['n']:,} lifters)",
              "Variance explained: " + ", ".join(f"PC{i+1} {v:.2%}" for i, v in enumerate(d["explained"])),
              "Mean shares: " + ", ".join(f"{l} {mm:.1%}" for l, mm in zip(pca.LIFTS, d["mean"])),
              "", "| Loading | PC1 | PC2 |", "|---|---:|---:|"]
        L += [f"| {l} | {d['components'][0][i]:+.3f} | {d['components'][1][i]:+.3f} |"
              for i, l in enumerate(pca.LIFTS)]
        L += ["", "Variance of log-ratios: " + ", ".join(f"{k} {v:.4f}" for k, v in d["logratio_var"].items()),
              "Correlation of bodyweight with shares: " + ", ".join(
                  f"{l} {c:+.3f}" for l, c in zip(pca.LIFTS, d["bw_corr"]))]

    sc = s["scoring"]
    nf = m["nscore_fit"]
    L += ["", "## Scoring formulas", "",
          f"N-Score fit #{nf['id']} of {nf['n_fits']} (fit {nf['fit_date']}, snapshot {nf['snapshot']}); "
          "all fits: docs/data/nscore_history.json.", f"Method: {sc['params']['method']}", "",
          "| Sex | a | b | R² (log) | test R² power | test R² poly5 | results | lifters |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for sex in ("M", "F"):
        f = sc["params"][sex]
        L.append(f"| {sex} | {f['A']:.2f} | {f['b']:.3f} | {f['r2_log']:.3f} | "
                 f"{f['test_r2_power']:.3f} | {f['test_r2_poly5']:.3f} | {f['n']:,} | {f['n_lifters']:,} |")
    L += ["", f"N-Score scale factor: {sc['params']['scale']:.2f}", "",
          "The men/women mean ratio of about 1 for N-Score follows from fitting each sex separately; "
          "it is not independent evidence that N-Score is fair across sexes.", "",
          "| Formula | r(BW) men | r(BW) women | M/F mean | M/F p99 |", "|---|---:|---:|---:|---:|"]
    L += [f"| {e['formula']} | {e['corr_bw_M']:+.3f} | {e['corr_bw_F']:+.3f} | "
          f"{e['mf_ratio_mean']:.3f} | {e['mf_ratio_p99']:.3f} |" for e in sc["evaluation"]]

    r = s["regression"]
    L += ["", "## Regression", "",
          f"n = {r['n']:,} results from {r['n_lifters']:,} lifters with a recorded age "
          f"({r['n_no_age']:,} results without an age left out); R² (log) = {r['r2_log']:.3f}; "
          f"R² (kg) = {r['r2_kg']:.3f}; RMSE = {r['rmse_kg']:.1f} kg; "
          f"peak age = {r['peak_age']:.1f} (cross-sectional)",
          "", f"SE: {r['se_type']}; naive i.i.d. SE shown for comparison.", "",
          "| Term | Coef | SE (clustered) | SE (i.i.d.) | % change in total |", "|---|---:|---:|---:|---:|"]
    L += [f"| {t} | {b:+.4f} | {se:.4f} | {si:.4f} | {np.expm1(b) * 100:+.1f}% |"
          for t, b, se, si in zip(r["terms"], r["beta"], r["se"], r["se_iid"]) if t != "Intercept"]
    L += ["", "Unique ΔR²: " + ", ".join(f"{k} {v:.3f}" for k, v in r["unique_r2"].items())]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
