"""Shared matplotlib style.

Design choices:
* Large fonts everywhere so axis labels are readable when printed.
* Dense scatter plots are drawn as hexbin density maps instead of
  semi-transparent points.  Overlapping translucent points mix into colours
  (e.g. dark green / dark blue) that do not exist on the colourbar; with hexbins
  every cell is painted with exactly one colour from the colourbar.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LogNorm  # noqa: E402

SEX_COLOR = {"M": "#2a6fdb", "F": "#e0533d"}
SEX_NAME = {"M": "Men", "F": "Women"}

plt.rcParams.update({
    "font.size": 14,
    "axes.titlesize": 16,
    "axes.labelsize": 15,
    "xtick.labelsize": 13,
    "ytick.labelsize": 13,
    "legend.fontsize": 13,
    "figure.titlesize": 18,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
})


def density(ax, x, y, gridsize=70, cmap="viridis", label="Number of lifters", C=None,
            reduce=None, vmin=None, vmax=None):
    """Hexbin density (log counts) or, if C is given, the mean of C per cell."""
    if C is None:
        hb = ax.hexbin(x, y, gridsize=gridsize, cmap=cmap, norm=LogNorm(), mincnt=1,
                       linewidths=0)
    else:
        hb = ax.hexbin(x, y, C=C, reduce_C_function=reduce, gridsize=gridsize, cmap=cmap,
                       mincnt=5, linewidths=0, vmin=vmin, vmax=vmax)
    cb = ax.figure.colorbar(hb, ax=ax)
    cb.set_label(label)
    return hb


ENABLED = True          # run_pipeline.py --no-figures turns PNG output off


def save(fig, path):
    if not ENABLED:
        plt.close(fig)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
