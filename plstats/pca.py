"""Strength-profile PCA on log-ratios of the three lifts.

Why log-ratios?
    A lifter's squat, bench and deadlift shares always add to 100%, so if one
    share goes up another must go down.  That constraint creates negative
    correlations between the raw shares even when the lifts are unrelated, so
    PCA and correlations on raw shares are distorted (Aitchison, 1986).  The
    standard fix is the centred log-ratio (clr) transform:
        clr_i = ln(share_i) - mean_j ln(share_j)
    which turns ratios between lifts into ordinary, unconstrained numbers.

Why (at most) three components?
    PCA returns one component per input variable.  We have three lifts, and the
    clr values of each lifter add to 0, so the data lie on a 2-D plane: PC3 has
    exactly 0% of the variance and PC1 + PC2 are a complete picture.

What the components mean (signs fixed so both sexes match)
    PC1: bench-heavy (-) vs lower-body-heavy (+)
    PC2: squat-heavy (+) vs deadlift-heavy (-)

Squat vs deadlift trade-off
    Measured with log-ratios, the squat/deadlift ratio is the *least* variable
    of the three ratios (`logratio_var`): lifters who are strong at one
    lower-body lift tend to be strong at the other, and bench is what varies
    most independently.

One point per lifter
    Each lifter appears once, at their best meet by Dots (ties: earliest), so
    frequent competitors don't count more than others.

Groups
    The map is one continuous cloud with no gaps between "types".  A
    "specialist" is a lifter in one tail of that cloud, not a separate group.

3-D map
    The website can also show the profile map in 3-D, with each lifter's Dots
    as the height.  The third axis is overall strength, not a PCA component
    (PC3 is empty, see above), so the view shows profile and strength together.
    It draws a fixed random sample of CLOUD_N lifters per sex.

PCA on raw kg (z-scored) is kept for comparison: PC1 there is simply overall
strength (~94% of the variance).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from . import config, population
from .plotting import SEX_NAME, density, plt, save

LIFTS = ["Squat", "Bench", "Deadlift"]
PCT = [f"{l}Pct" for l in LIFTS]
KG = [f"Best3{l}Kg" for l in LIFTS]
CLOUD_N = 4000          # lifters per sex drawn on the 3-D map


def clr(X):
    """Centred log-ratio transform of rows of shares."""
    L = np.log(X)
    return L - L.mean(axis=1, keepdims=True)


def _orient(components):
    """Fix PCA's arbitrary signs so men and women plots point the same way:
    PC1 negative = bench-heavy, PC2 positive = squat-heavy."""
    c = components.copy()
    if c[0, 1] > 0:
        c[0] *= -1
    if c[1, 0] < 0:
        c[1] *= -1
    return c


def _grid(x, y, bins=70):
    xr = np.percentile(x, [0.2, 99.8])
    yr = np.percentile(y, [0.2, 99.8])
    h, xe, ye = np.histogram2d(x, y, bins=bins, range=[xr, yr])
    return {"x0": float(xe[0]), "dx": float(xe[1] - xe[0]), "y0": float(ye[0]),
            "dy": float(ye[1] - ye[0]), "counts": h.T.astype(int).tolist()}


def _profile(sub, sex):
    """Log-ratio PCA for one sex of one comparison group, one row per lifter (their best meet by Dots)."""
    sub = population.best_rows(sub, "Dots")
    X = sub[PCT].values
    Z = clr(X)
    center = Z.mean(axis=0)
    pca = PCA(n_components=3).fit(Z)
    comp = _orient(pca.components_)
    scores = (Z - center) @ comp[:2].T
    hl = sub[sub["Name"].isin(config.HIGHLIGHT_LIFTERS[sex])]
    hl_scores = (clr(hl[PCT].values) - center) @ comp[:2].T if len(hl) else np.empty((0, 2))
    lr = lambda a, b: float(np.var(np.log(X[:, a] / X[:, b])))
    bw = sub["BodyweightKg"].values
    prof = {
        "n": int(len(sub)),
        "mean": X.mean(axis=0).tolist(),          # average shares (for the profile bars)
        "sd": X.std(axis=0).tolist(),
        "space": "clr",
        "center": center.tolist(),                # clr mean, for projecting a lifter
        "components": comp.tolist(),
        "explained": pca.explained_variance_ratio_.tolist(),
        "logratio_var": {"squat/deadlift": lr(0, 2), "squat/bench": lr(0, 1),
                         "deadlift/bench": lr(2, 1)},
        "bw_corr": [float(np.corrcoef(bw, X[:, i])[0, 1]) for i in range(3)],
        "score_sd": scores.std(axis=0).tolist(),
        "grid": _grid(scores[:, 0], scores[:, 1]),
        "highlights": [
            {"name": r["Name"].split(" #")[0], "pc": hl_scores[i].tolist(),
             "pct": [float(r[p]) for p in PCT], "total": float(r["TotalKg"])}
            for i, (_, r) in enumerate(hl.iterrows())
        ],
    }
    return prof, X, center, comp, scores, hl, hl_scores, sub


def _cloud(scores, sub, n=CLOUD_N, seed=0):
    """A fixed random sample of lifters for the 3-D map: their two profile coordinates and their Dots."""
    idx = np.sort(np.random.default_rng(seed).choice(len(sub), size=min(n, len(sub)), replace=False))
    return {"n_total": int(len(sub)),
            "pc1": np.round(scores[idx, 0], 3).tolist(), "pc2": np.round(scores[idx, 1], 3).tolist(),
            "dots": np.round(sub["Dots"].values[idx], 1).tolist()}


def profiles(df: pd.DataFrame) -> dict:
    """Per-sex strength-profile data for a comparison group (no figures)."""
    out = {}
    for sex in ("M", "F"):
        sub = df[df["Sex"] == sex]
        out[sex] = _profile(sub, sex)[0] if sub["Name"].nunique() >= 10 else None   # too few to map
    return out


def run(df: pd.DataFrame) -> dict:
    out = {}

    # ---------------- PCA-A: raw kilos, standardised so deadlift (the heaviest
    # lift) does not dominate just because its numbers are bigger.
    base = population.best_rows(df, "Dots")          # one row per lifter, as everywhere else
    za = StandardScaler().fit_transform(base[KG].values)
    pca_a = PCA(n_components=3).fit(za)
    out["raw"] = {
        "explained": pca_a.explained_variance_ratio_.tolist(),
        "loadings": pca_a.components_.tolist(),
    }

    # ---------------- PCA-B per sex
    out["by_sex"] = {}
    cloud = {}
    fig_scree, axes_scree = plt.subplots(1, 3, figsize=(18, 5))
    bars = [("Raw kg (z-scored), both sexes", pca_a.explained_variance_ratio_)]

    for sex in ("M", "F"):
        prof, X, mean, comp, scores, hl, hl_scores, sub = _profile(df[df["Sex"] == sex], sex)
        ev = np.array(prof["explained"])
        bars.append((f"Lift log-ratios, {SEX_NAME[sex].lower()}", ev))
        out["by_sex"][sex] = prof
        cloud[sex] = _cloud(scores, sub)

        # Biplot: density + loading arrows + labelled lifters
        fig, ax = plt.subplots(figsize=(10, 8.5))
        density(ax, scores[:, 0], scores[:, 1], cmap="Greys")
        lim = np.percentile(np.abs(scores), 99.8) * 1.15
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_aspect("equal")
        scale = 2 * scores.std(axis=0).max()
        colors = {"Squat": "#2a6fdb", "Bench": "#e0533d", "Deadlift": "#1a9e5c"}
        for i, lift in enumerate(LIFTS):
            x, y = comp[0, i] * scale, comp[1, i] * scale
            ax.annotate("", xy=(x, y), xytext=(0, 0),
                        arrowprops=dict(arrowstyle="-|>", lw=2.5, color=colors[lift]))
            ax.text(x * 1.2, y * 1.2, f"{lift}-heavy", color=colors[lift],
                    fontsize=15, fontweight="bold", ha="center", va="center")
        for j, (_, r) in enumerate(hl.iterrows()):
            ax.scatter(*hl_scores[j], s=90, c="gold", edgecolors="black", zorder=5)
            ax.annotate(r["Name"].split(" #")[0], hl_scores[j], xytext=(6, 6),
                        textcoords="offset points", fontsize=12, fontweight="bold")
        ax.axhline(0, color="k", lw=0.6)
        ax.axvline(0, color="k", lw=0.6)
        ax.set_xlabel(f"PC1: bench-heavy (-) vs lower-body-heavy (+)  [{ev[0]:.1%} of variance]")
        ax.set_ylabel(f"PC2: deadlift-heavy (-) vs squat-heavy (+)  [{ev[1]:.1%}]")
        ax.set_title(f"Strength-profile PCA (log-ratios), {SEX_NAME[sex]} (n = {len(sub):,} lifters)")
        save(fig, config.FIG_DIR / f"pca_biplot_{sex}.png")

    for ax, (title, ev) in zip(axes_scree, bars):
        ax.bar(["PC1", "PC2", "PC3"], ev * 100, color="#2a6fdb")
        for i, v in enumerate(ev):
            ax.text(i, v * 100 + 1.5, f"{v:.1%}", ha="center", fontsize=13)
        ax.set_ylim(0, 105)
        ax.set_ylabel("Variance explained (%)")
        ax.set_title(title)
    fig_scree.suptitle("How much variance each principal component explains")
    save(fig_scree, config.FIG_DIR / "pca_scree.png")

    # Raw-lift PCA coloured by bodyweight (mean bodyweight per hexagon).
    sa = pca_a.transform(za)
    fig, ax = plt.subplots(figsize=(10, 7.5))
    lo, hi = np.percentile(base["BodyweightKg"], [2, 98])
    density(ax, sa[:, 0], sa[:, 1], C=base["BodyweightKg"].values, reduce=np.mean,
            label="Mean bodyweight in cell (kg)", vmin=lo, vmax=hi)
    ev = pca_a.explained_variance_ratio_
    ax.set_xlabel(f"PC1: overall strength  [{ev[0]:.1%}]")
    ax.set_ylabel(f"PC2  [{ev[1]:.1%}]")
    ax.set_title("PCA on raw lifts (z-scored), coloured by bodyweight")
    save(fig, config.FIG_DIR / "pca_raw_bodyweight.png")

    out["cloud"] = cloud
    return out
