"""PNG charts from an analysis dict."""

from __future__ import annotations

import datetime as dt

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .i18n import labels  # noqa: E402

PALETTE = ["#2f6fdf", "#e0702a", "#2a9d6f", "#b8418f", "#7a5cd6",
           "#c9a227", "#3aa8c1", "#d0473f", "#6b7a8f", "#8c6d46"]


def _dates(keys: list[str]) -> list[dt.date]:
    return [dt.date(int(k[:4]), int(k[4:6]), int(k[6:8])) for k in keys]


def plot(analysis: dict, path: str, label_lang: str = "en",
         size: tuple[float, float] = (11, 3.6)) -> str:
    L = labels(label_lang)
    gran = analysis["params"]["granularity"]
    unit = L["month" if gran == "monthly" else "day"]
    x = _dates(analysis["timeline"])
    rows = [s for s in analysis["series"] if s.get("metrics")]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=size, dpi=150)
    for i, s in enumerate(rows):
        c = PALETTE[i % len(PALETTE)]
        v = np.array(s["views"], float)
        ax1.plot(x, v, color=c, lw=1.6, label=s["id"])
        mask = np.array(s["metrics"]["spike_mask"], bool)
        if mask.any():
            ax1.scatter(np.array(x)[mask], v[mask], s=40, facecolors="none",
                        edgecolors="#d0473f", lw=1.3, zorder=3)
        share = np.array(s["per_million"], float)
        start = next((j for j, val in enumerate(share) if val > 0), 0)
        # median of the first points, so a spike in month 1 does not distort the index
        base = float(np.median(share[start:start + (3 if gran == "monthly" else 7)]))
        idx = np.where(share > 0, share / base * 100, np.nan) if base > 0 else share * np.nan
        ax2.plot(x, idx, color=c, lw=1.6)

    vmax = max((max(s["views"]) for s in rows), default=1)
    vmin = min((min(v for v in s["views"] if v > 0) for s in rows
                if any(s["views"])), default=1)
    if vmax / max(vmin, 1) > 30:
        ax1.set_yscale("log")
    ax1.set_title(L["views_title"].format(unit=unit), fontsize=10, loc="left")
    ax2.set_title(L["index_title"], fontsize=10, loc="left")
    ax2.axhline(100, color="#999", lw=0.8, ls="--")
    for ax in (ax1, ax2):
        ax.grid(alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m" if gran == "monthly" else "%m-%d"))
        ax.tick_params(labelsize=8)
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(30)
            lbl.set_ha("right")
    ax1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    handles, names = ax1.get_legend_handles_labels()
    if any(np.array(s["metrics"]["spike_mask"]).any() for s in rows):
        handles.append(plt.Line2D([], [], ls="", marker="o", mfc="none", mec="#d0473f"))
        names.append(L["spike"])
    fig.legend(handles, names, loc="lower center", ncol=min(len(names), 5),
               fontsize=8, frameon=False)
    fig.tight_layout(rect=(0, 0.08 + 0.04 * ((len(names) - 1) // 5), 1, 1))
    fig.savefig(path)
    plt.close(fig)
    return path
