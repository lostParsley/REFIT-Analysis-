"""Consistent, exportable figures with explicit units and restrained styling."""
from .data import ROOT
import os
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "data" / "matplotlib-cache"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

BLUE, TEAL, ORANGE, RED = "#28517B", "#008577", "#D98B2B", "#BD4B45"

def setup():
    plt.rcParams.update({"figure.dpi": 120, "savefig.dpi": 180, "font.family": "DejaVu Sans",
        "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
        "axes.titleweight": "bold", "axes.labelcolor": "#334155", "text.color": "#172B42",
        "axes.grid": True, "grid.alpha": .18, "axes.axisbelow": True,
        "figure.facecolor": "white", "axes.prop_cycle": plt.cycler(color=[BLUE, TEAL, ORANGE, RED])})

def save(fig, name):
    folder = ROOT / "output"
    folder.mkdir(exist_ok=True)
    fig.savefig(folder / f"{name}.png", bbox_inches="tight")
    fig.savefig(folder / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)

def times(axis):
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M", tz="Europe/London"))
    axis.set_xlabel("UK local time (Europe/London)")
