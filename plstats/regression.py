"""Multivariable regression: what predicts a lifter's total?

    ln(Total) = b0 + b1*zBW + b2*Male + b3*(zBW x Male) + b4*zAge + b5*zAge^2 + b6*zYear

Variables
* zBW   - ln(bodyweight), standardised (subtract mean, divide by SD).
* Male  - indicator variable: 1 if the lifter competed as male, 0 if female.
          Sex is categorical, so it enters the model as this 0/1 dummy.
* zBW x Male - the product of the two above.  For women (Male = 0) it is
          always 0, so the bodyweight slope for women is b1.  For men it equals
          zBW, so their slope is b1 + b3.  This is mathematically the same as
          fitting a separate bodyweight slope for each sex, and b3 is the
          *difference* between the men's and women's slopes.
* zAge, zAge^2 - age (standardised) and its square: strength rises and then
          falls with age, which a straight line cannot capture.
* zYear - meet year, standardised.

Because every continuous predictor is standardised, each coefficient is the
change in ln(Total) for a one-standard-deviation change in that predictor, so
coefficients are directly comparable regardless of units (kg, years, ...).
We also report each variable group's *unique* share of R^2 (drop-one
Delta R^2), which is the cleanest "how much does this variable matter" number.

Sample: the default comparison group (see clean.py), every meet result with a
recorded age (OpenPowerlifting estimates some ages from the age class, e.g.
"24.5").  Results without an age are left out.  Many lifters appear several
times, so the standard errors are clustered by lifter (CR1 sandwich
estimator); naive i.i.d. SEs are kept as `se_iid` for comparison.

Peak age is cross-sectional: it compares different lifters at different ages
in the same decade, not the same lifters as they get older, so it also
reflects who starts and who keeps competing at each age.

The calculator's "stronger than X% of lifters like you" uses each lifter's
best residual (one value per lifter), matching the per-lifter percentiles.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .plotting import density, plt, save

TERMS = ["Intercept", "zBW", "Male", "zBW x Male", "zAge", "zAge^2", "zYear"]
GROUPS = {"Bodyweight": ["zBW", "zBW x Male"], "Sex": ["Male", "zBW x Male"],
          "Age": ["zAge", "zAge^2"], "Year": ["zYear"]}


def design(lbw, male, age, year, std):
    zbw = (lbw - std["lbw_mean"]) / std["lbw_sd"]
    za = (age - std["age_mean"]) / std["age_sd"]
    zy = (year - std["year_mean"]) / std["year_sd"]
    return np.column_stack([np.ones_like(zbw), zbw, male, zbw * male, za, za ** 2, zy])


def _ols(X, y, groups=None):
    """OLS. With `groups` (lifter names) the standard errors are cluster-robust (CR1): a lifter's
    results are not independent of each other, and treating them as independent understates the SEs."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    se_iid = np.sqrt(np.diag(XtX_inv) * (resid @ resid / (n - k)))
    se = se_iid
    if groups is not None:
        codes, uniq = pd.factorize(np.asarray(groups))
        g = len(uniq)
        S = np.zeros((g, k))
        np.add.at(S, codes, X * resid[:, None])            # per-lifter sums of x_i * e_i
        meat = S.T @ S
        V = XtX_inv @ meat @ XtX_inv * (g / (g - 1)) * ((n - 1) / (n - k))
        se = np.sqrt(np.diag(V))
    r2 = 1 - resid @ resid / np.sum((y - y.mean()) ** 2)
    return beta, se, resid, r2, se_iid


def _best_resid_quantiles(names, resid, digits):
    """Quantiles of each lifter's best (largest) residual: "stronger than X% of lifters like you"
    then counts each lifter once, at their best meet relative to the model."""
    best = pd.Series(resid).groupby(np.asarray(names), sort=False).max().values
    return np.quantile(best, np.linspace(0, 1, 201)).round(digits).tolist()


def fit(df: pd.DataFrame) -> dict:
    """Just the numbers the calculator needs, for one comparison group."""
    d = df[df["Age"].notna()]
    lbw, age, year = np.log(d["BodyweightKg"].values), d["Age"].values, d["Year"].values.astype(float)
    male = (d["Sex"] == "M").astype(float).values
    y = np.log(d["TotalKg"].values)
    std = {k: float(v) for k, v in {
        "lbw_mean": lbw.mean(), "lbw_sd": lbw.std(), "age_mean": age.mean(),
        "age_sd": age.std(), "year_mean": year.mean(), "year_sd": max(year.std(), 1e-9)}.items()}
    if len(d) < 50 or d["Sex"].nunique() < 2:
        return None                                       # too few results to fit the model
    beta, _, resid, r2, _ = _ols(design(lbw, male, age, year, std), y)
    return {"n": int(len(d)), "n_lifters": int(d["Name"].nunique()), "beta": beta.tolist(), "std": std,
            "smear": float(np.mean(np.exp(resid))), "r2_log": float(r2),
            "resid_quantiles": _best_resid_quantiles(d["Name"].values, resid, 4)}


def run(df: pd.DataFrame) -> dict:
    d = df[df["Age"].notna()].copy()
    lbw, age, year = np.log(d["BodyweightKg"].values), d["Age"].values, d["Year"].values.astype(float)
    male = (d["Sex"] == "M").astype(float).values
    y = np.log(d["TotalKg"].values)
    std = {"lbw_mean": lbw.mean(), "lbw_sd": lbw.std(), "age_mean": age.mean(),
           "age_sd": age.std(), "year_mean": year.mean(), "year_sd": year.std()}
    std = {k: float(v) for k, v in std.items()}

    X = design(lbw, male, age, year, std)
    beta, se, resid, r2, se_iid = _ols(X, y, d["Name"].values)

    unique = {}
    for g, cols in GROUPS.items():
        keep = [i for i, t in enumerate(TERMS) if t not in cols]
        unique[g] = float(r2 - _ols(X[:, keep], y)[3])

    # back-transform to kg with Duan's smearing correction
    smear = float(np.mean(np.exp(resid)))
    pred_kg = np.exp(X @ beta) * smear
    actual = d["TotalKg"].values
    r2_kg = 1 - np.sum((actual - pred_kg) ** 2) / np.sum((actual - actual.mean()) ** 2)
    rmse = float(np.sqrt(np.mean((actual - pred_kg) ** 2)))

    # Cross-sectional: different lifters at different ages over the same ten years, not the same
    # lifters followed as they age (who keeps competing, and when people start, both shape it).
    peak_z = -beta[4] / (2 * beta[5])
    peak_age = float(peak_z * std["age_sd"] + std["age_mean"])

    lo, hi = np.percentile(np.r_[pred_kg, actual], [0.2, 99.8])
    h, e, _ = np.histogram2d(pred_kg, actual, bins=70, range=[[lo, hi], [lo, hi]])

    # ---------------- figures
    fig, axes = plt.subplots(1, 2, figsize=(17, 7))
    ax = axes[0]
    density(ax, pred_kg, actual, gridsize=70)
    ax.plot([lo, hi], [lo, hi], "r--", lw=2, label="Perfect prediction (y = x)")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("Model-predicted total (kg)")
    ax.set_ylabel("Actual total (kg)")
    ax.set_title(f"Predicted vs actual total  (R² = {r2_kg:.3f}, RMSE = {rmse:.0f} kg)")
    ax.legend(loc="upper left")
    ax = axes[1]
    density(ax, pred_kg, actual - pred_kg, gridsize=70)
    ax.axhline(0, color="r", lw=2)
    ax.set_xlabel("Model-predicted total (kg)")
    ax.set_ylabel("Actual - predicted (kg)")
    ax.set_title("Residuals vs predicted")
    save(fig, config.FIG_DIR / "regression_predicted_vs_actual.png")

    fig, axes = plt.subplots(1, 2, figsize=(17, 6))
    terms, b, s = TERMS[1:], beta[1:], se[1:]
    order = np.argsort(np.abs(b))
    axes[0].barh([terms[i] for i in order], [b[i] for i in order],
                 xerr=[1.96 * s[i] for i in order],
                 color=["#2a6fdb" if b[i] > 0 else "#e0533d" for i in order])
    axes[0].axvline(0, color="k", lw=1)
    axes[0].set_xlabel("Change in ln(Total) per 1 SD (Male: male vs female)")
    axes[0].set_title("Standardised coefficients (95% CI, clustered by lifter)")
    g = sorted(unique, key=unique.get)
    axes[1].barh(g, [unique[k] * 100 for k in g], color="#1a9e5c")
    axes[1].set_xlabel("Unique share of variance explained (ΔR², %)")
    axes[1].set_title("Variable importance (drop-one ΔR²)")
    save(fig, config.FIG_DIR / "regression_importance.png")

    return {
        "n": int(len(d)), "n_lifters": int(d["Name"].nunique()), "n_no_age": int(df["Age"].isna().sum()),
        "n_lifters_total": int(df["Name"].nunique()),
        "terms": TERMS, "beta": beta.tolist(), "se": se.tolist(), "se_iid": se_iid.tolist(),
        "se_type": "cluster-robust (CR1) by lifter",
        "std": std, "smear": smear, "resid_sd": float(resid.std()),
        "resid_quantiles": _best_resid_quantiles(d["Name"].values, resid, 5),
        "r2_log": float(r2), "r2_kg": float(r2_kg), "rmse_kg": rmse,
        "unique_r2": unique, "peak_age": peak_age,
        "pred_vs_actual": {"x0": float(e[0]), "dx": float(e[1] - e[0]),
                           "counts": h.T.astype(int).tolist()},
    }
