"""Powerlifting scoring formulas.

Every formula answers the same question: "how strong is this total *for this
bodyweight and sex*?"  They all have the form

    score = Total * K / f(BW)

where f(BW) is a curve describing the expected total at a given bodyweight and
K is a constant that sets the scale.  They differ only in the shape of f:

* Wilks (1994)   - 5th-degree polynomial in BW, fitted by Robert Wilks on
                   (mostly male) elite results from the 1990s.  K = 500.
* Dots (2019)    - 4th-degree polynomial in BW, refitted by Tim Konertz on
                   modern OpenPowerlifting data.  K = 500.
* IPF GL (2020)  - exponential curve A - B*exp(-C*BW) used by the IPF
                   ("Goodlift" points).  K = 100, so ~100 is world-class.
                   Not defined below 35 kg bodyweight (as on OpenPowerlifting).
* N-Score (ours) - power law a*BW^b, fitted separately for each sex on US
                   tested raw lifters with log-log regression (each lifter
                   weighted once).  K is chosen so the 99th percentile of
                   lifters' best scores, both sexes pooled, is 500.  Refit every
                   week; past fits are kept in docs/data/nscore_history.json.

All functions accept numpy arrays or scalars; `sex` is "M" or "F".
"""
from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------- Wilks (1994)
_WILKS = {
    "M": (-216.0475144, 16.2606339, -0.002388645, -0.00113732, 7.01863e-06, -1.291e-08),
    "F": (594.31747775582, -27.23842536447, 0.82112226871, -0.00930733913,
          4.731582e-05, -9.054e-08),
}
_WILKS_BW = {"M": (40.0, 201.9), "F": (26.51, 154.53)}

# ----------------------------------------------------------------- Dots (2019)
_DOTS = {
    "M": (-307.75076, 24.0900756, -0.1918759221, 0.0007391293, -0.000001093),
    "F": (-57.96288, 13.6175032, -0.1126655495, 0.0005158568, -0.0000010706),
}
_DOTS_BW = {"M": (40.0, 210.0), "F": (40.0, 150.0)}

# ----------------------------------------------- IPF GL points, raw full power
_GL = {"M": (1199.72839, 1025.18162, 0.00921), "F": (610.32796, 1045.59282, 0.03048)}


def _poly(coefs, x):
    return sum(c * x ** i for i, c in enumerate(coefs))


def _by_sex(fn, total, bw, sex):
    total = np.asarray(total, dtype=float)
    bw = np.asarray(bw, dtype=float)
    sex = np.asarray(sex)
    out = np.full(np.broadcast(total, bw, sex).shape, np.nan)
    for s in ("M", "F"):
        m = np.broadcast_to(sex == s, out.shape)
        if m.any():
            out[m] = fn(np.broadcast_to(total, out.shape)[m],
                        np.broadcast_to(bw, out.shape)[m], s)
    return out if out.shape else float(out)


def wilks(total, bw, sex):
    def f(t, b, s):
        b = np.clip(b, *_WILKS_BW[s])
        return t * 500.0 / _poly(_WILKS[s], b)
    return _by_sex(f, total, bw, sex)


def dots(total, bw, sex):
    def f(t, b, s):
        b = np.clip(b, *_DOTS_BW[s])
        return t * 500.0 / _poly(_DOTS[s], b)
    return _by_sex(f, total, bw, sex)


GL_MIN_BW = 35.0


def ipf_gl(total, bw, sex):
    """IPF GL points. Like OpenPowerlifting, undefined (NaN; OPL leaves the column blank) below 35 kg
    bodyweight, and never negative."""
    def f(t, b, s):
        a, bb, c = _GL[s]
        out = t * np.maximum(0.0, 100.0 / (a - bb * np.exp(-c * b)))
        return np.where(b < GL_MIN_BW, np.nan, out)
    return _by_sex(f, total, bw, sex)


def nscore(total, bw, sex, params):
    """params = {"M": {"a": ln_a, "b": b}, "F": {...}, "scale": K}."""
    def f(t, b, s):
        expected = np.exp(params[s]["a"]) * b ** params[s]["b"]
        return t / expected * params["scale"]
    return _by_sex(f, total, bw, sex)


FORMULA_COEFFICIENTS = {
    "wilks": {"coef": _WILKS, "bw_clip": _WILKS_BW},
    "dots": {"coef": _DOTS, "bw_clip": _DOTS_BW},
    "ipf_gl": {"coef": _GL},
}
