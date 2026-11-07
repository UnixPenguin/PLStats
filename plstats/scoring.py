"""N-Score: an allometric (power-law) scoring formula, compared to Wilks, Dots
and IPF GL.  See formulas.py for what each of those formulas is.

Model, fitted separately for each sex:
    Total = a * BW^b   <=>   ln(Total) = ln(a) + b * ln(BW)
Each lifter counts once in the fit: a lifter's rows are weighted 1/(number of
their results).  N-Score = 500 * (Total / predicted Total) / q99, where q99 is
the 99th percentile of lifters' best Total/predicted, both sexes pooled, so the
top 1% of lifters score above 500.

The fit is redone on every weekly refresh, so it adapts to the current
population; every fit is appended to docs/data/nscore_history.json, and scores
from different fits are not exactly comparable.

Because men and women each get their own curve, both are centred on their own
sex's typical lifter; the ~1.0 men/women mean-score ratio follows from that
construction and is not independent evidence that the formula is fair across
sexes.

A good formula should give scores that do not depend on bodyweight
(correlation ~ 0).  Evaluation uses one row per lifter: their best meet by
the score being evaluated.

Validation:
* 80/20 train/test split: the power law and the 5th-degree polynomial are fit
  on 80% of lifters and scored on the other 20%, so the comparison is out of
  sample.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, formulas, population
from .plotting import SEX_COLOR, SEX_NAME, density, plt, save

SCORES = {"Wilks": "Wilks", "Dots": "Dots", "IPF GL": "IPF_GL", "N-Score": "NScore"}


def _r2(y, yhat, w=None):
    w = np.ones_like(y) if w is None else w
    ybar = np.average(y, weights=w)
    return 1 - np.sum(w * (y - yhat) ** 2) / np.sum(w * (y - ybar) ** 2)


FIT_METHOD = ("v2: ln(Total) = ln(a) + b*ln(BW) by least squares, each lifter's results weighted to a total "
              "of 1; scale = 500 / 99th percentile of lifters' best Total/(a*BW^b), both sexes pooled")


def run(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = df.copy()
    rng = np.random.default_rng(config.SEED)
    # split by lifter, so the same person never appears in both halves
    names = np.sort(df["Name"].unique())
    test_names = set(rng.choice(names, size=len(names) // 5, replace=False))
    is_test = df["Name"].isin(test_names).values
    # Each lifter counts once: a lifter with 10 meets gets weight 1/10 per meet, so frequent
    # competitors don't pull the curve toward themselves.
    wt = population.lifter_weights(df["Name"].values)

    fits, poly = {}, {}
    for sex in ("M", "F"):
        m = (df["Sex"] == sex).values
        lbw, lt, w = np.log(df.loc[m, "BodyweightKg"].values), np.log(df.loc[m, "TotalKg"].values), wt[m]
        tr, te = ~is_test[m], is_test[m]
        # np.polyfit weights multiply the residuals, so pass sqrt(weight) for weighted least squares
        b, a = np.polyfit(lbw, lt, 1, w=np.sqrt(w))                      # final fit: all data
        b_tr, a_tr = np.polyfit(lbw[tr], lt[tr], 1, w=np.sqrt(w[tr]))
        bw, t = df.loc[m, "BodyweightKg"].values, df.loc[m, "TotalKg"].values
        pc = np.polynomial.Polynomial.fit(bw[tr], t[tr], 5, w=np.sqrt(w[tr]))
        fits[sex] = {
            "a": float(a), "b": float(b), "A": float(np.exp(a)), "n": int(m.sum()),
            "n_lifters": int(df.loc[m, "Name"].nunique()),
            "r2_log": float(_r2(lt, a + b * lbw, w)),
            "test_r2_power": float(_r2(t[te], np.exp(a_tr) * bw[te] ** b_tr, w[te])),
            "test_r2_poly5": float(_r2(t[te], pc(bw[te]), w[te])),
        }
        grid = np.linspace(np.percentile(bw, 0.1), np.percentile(bw, 99.9), 80)
        poly[sex] = {"bw": grid.round(2).tolist(),
                     "power": (np.exp(a) * grid ** b).round(1).tolist(),
                     "poly5": pc(grid).round(1).tolist()}

    expected = np.where(df["Sex"] == "M",
                        fits["M"]["A"] * df["BodyweightKg"] ** fits["M"]["b"],
                        fits["F"]["A"] * df["BodyweightKg"] ** fits["F"]["b"])
    best_ratio = population.best_values(df.assign(_r=df["TotalKg"] / expected), "_r")
    scale = 500 / np.quantile(best_ratio, 0.99)
    params = {"M": fits["M"], "F": fits["F"], "scale": float(scale),
              "scale_n_lifters": int(len(best_ratio)), "method": FIT_METHOD}

    sx, bw, tot = df["Sex"].values, df["BodyweightKg"].values, df["TotalKg"].values
    df["Wilks"] = formulas.wilks(tot, bw, sx)
    df["Dots"] = formulas.dots(tot, bw, sx)
    df["IPF_GL"] = formulas.ipf_gl(tot, bw, sx)
    df["NScore"] = formulas.nscore(tot, bw, sx, params)

    # ---------------- evaluation, one row per lifter: their best meet by that score
    evals, binned, hists, best = [], {}, {}, {}
    bins = {s: np.linspace(*np.percentile(df.loc[df.Sex == s, "BodyweightKg"], [1, 99]), 26)
            for s in ("M", "F")}
    for label, col in SCORES.items():
        row = {"formula": label}
        binned[label], hists[label], best[label] = {}, {}, {}
        for sex in ("M", "F"):
            sub = population.best_rows(df[df["Sex"] == sex], col)
            best[label][sex] = sub
            row[f"n_lifters_{sex}"] = int(len(sub))
            row[f"corr_bw_{sex}"] = float(np.corrcoef(sub["BodyweightKg"], sub[col])[0, 1])
            row[f"mean_{sex}"] = float(sub[col].mean())
            row[f"p99_{sex}"] = float(sub[col].quantile(0.99))
            b = bins[sex]
            idx = np.digitize(sub["BodyweightKg"], b) - 1
            ok = (idx >= 0) & (idx < len(b) - 1)
            means = pd.Series(sub[col].values[ok]).groupby(idx[ok]).mean()
            binned[label][sex] = {"bw": ((b[:-1] + b[1:]) / 2).round(1).tolist(),
                                  "mean": [round(float(means.get(i, np.nan)), 2)
                                           for i in range(len(b) - 1)]}
        hi = max(best[label][s][col].quantile(0.999) for s in ("M", "F"))
        lo = min(best[label][s][col].quantile(0.001) for s in ("M", "F"))
        edges = np.linspace(lo, hi, 61)
        for sex in ("M", "F"):
            h, _ = np.histogram(best[label][sex][col], bins=edges, density=True)
            hists[label][sex] = h.round(6).tolist()
        hists[label]["edges"] = edges.round(3).tolist()
        row["mf_ratio_mean"] = row["mean_M"] / row["mean_F"]
        row["mf_ratio_p99"] = row["p99_M"] / row["p99_F"]
        evals.append(row)

    # ---------------- figures (one panel per formula, readable titles)
    for sex in ("M", "F"):
        fig, axes = plt.subplots(2, 2, figsize=(15, 11), sharex=True)
        for ax, (label, col) in zip(axes.flat, SCORES.items()):
            sub = best[label][sex]
            density(ax, sub["BodyweightKg"], sub[col], gridsize=60)
            ax.plot(binned[label][sex]["bw"], binned[label][sex]["mean"], color="red", lw=2.5,
                    label="Mean score per bodyweight bin")
            r = np.corrcoef(sub["BodyweightKg"], sub[col])[0, 1]
            ax.set_title(f"{label}  (correlation with bodyweight r = {r:+.3f})")
            ax.set_ylabel(f"{label} score")
            ax.legend(loc="upper right", fontsize=11)
        for ax in axes[1]:
            ax.set_xlabel("Bodyweight (kg)")
        fig.suptitle(f"{SEX_NAME[sex]}: does each score depend on bodyweight? "
                     f"(flat red line = fair)")
        save(fig, config.FIG_DIR / f"score_vs_bodyweight_{sex}.png")

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    for ax, label in zip(axes.flat, SCORES):
        e = np.array(hists[label]["edges"])
        for sex in ("M", "F"):
            ax.stairs(hists[label][sex], e, fill=True, alpha=0.35, color=SEX_COLOR[sex])
            ax.stairs(hists[label][sex], e, color=SEX_COLOR[sex], lw=2, label=SEX_NAME[sex])
        ax.set_title(f"{label} distribution by sex")
        ax.set_xlabel(f"{label} score")
        ax.set_ylabel("Density")
        ax.legend()
    fig.suptitle("Distribution of lifters' best scores: men (blue) vs women (red)")
    save(fig, config.FIG_DIR / "score_distributions.png")

    fig, axes = plt.subplots(1, 2, figsize=(16, 6.5))
    for ax, sex in zip(axes, ("M", "F")):
        sub = df[df["Sex"] == sex]
        density(ax, sub["BodyweightKg"], sub["TotalKg"], gridsize=60, cmap="Greys")
        ax.plot(poly[sex]["bw"], poly[sex]["power"], color=SEX_COLOR[sex], lw=3,
                label=f"Power law: {fits[sex]['A']:.1f} x BW^{fits[sex]['b']:.3f}")
        ax.plot(poly[sex]["bw"], poly[sex]["poly5"], "--", color="orange", lw=2.5,
                label="5th-degree polynomial")
        ax.set_title(f"{SEX_NAME[sex]}: total vs bodyweight")
        ax.set_xlabel("Bodyweight (kg)")
        ax.set_ylabel("Total (kg)")
        ax.legend(loc="lower right")
    save(fig, config.FIG_DIR / "allometric_fit.png")

    return df, {"params": params, "fit_curves": poly, "evaluation": evals,
                "binned": binned, "hist": hists}
