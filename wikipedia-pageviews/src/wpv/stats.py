"""Trend statistics for pageview series. Pure numpy, no network.

Design choices (see references/methodology.md for the reasoning):
- Mann-Kendall test + Sen's slope: rank-based, robust to single news spikes.
- Yue & Wang lag-1 autocorrelation correction of the MK variance: monthly
  pageviews are autocorrelated, and the plain test would overstate significance.
- Spikes: robust z-score (median/MAD) of residuals around the Sen line, in log
  space, so a 3x jump counts the same for a small and a large wiki.
- Confidence: a transparent points system; every point comes with a reason
  string that the agent can quote.
"""

from __future__ import annotations

import math

import numpy as np

SPIKE_Z = 3.0


def mann_kendall(y: np.ndarray, slope: float | None = None) -> dict:
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 4:
        return {"s": 0, "z": 0.0, "p": 1.0, "p_raw": 1.0, "autocorr_lag1": None}
    diff = y[None, :] - y[:, None]
    s = int(np.sign(diff[np.triu_indices(n, 1)]).sum())
    _, counts = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5)
           - sum(t * (t - 1) * (2 * t + 5) for t in counts if t > 1)) / 18.0

    def z_of(v):
        if v <= 0 or s == 0:
            return 0.0
        return (s - np.sign(s)) / math.sqrt(v)

    z_raw = z_of(var)
    p_raw = math.erfc(abs(z_raw) / math.sqrt(2))

    # Yue & Wang (2004) correction with lag-1 autocorrelation of the Sen-detrended
    # series (same formula as pymannkendall.yue_wang_modification_test(lag=1)).
    # Floored at 1: negative autocorrelation never makes the test less strict.
    if slope is None:
        slope, _ = sen_slope(y)
    resid = y - slope * np.arange(1, n + 1)
    resid = resid - resid.mean()
    denom = float((resid ** 2).sum())
    r1 = float((resid[:-1] * resid[1:]).sum() / denom) if denom > 0 else 0.0
    factor = max(1.0, 1 + 2 * (1 - 1 / n) * r1)
    z = z_of(var * factor)
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"s": s, "z": round(z, 3), "p": p, "p_raw": p_raw,
            "autocorr_lag1": round(r1, 3), "variance_factor": round(factor, 3)}


def sen_slope(y: np.ndarray) -> tuple[float, float]:
    """Median of pairwise slopes and the matching intercept (x = 0..n-1)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 2:
        return 0.0, float(y[0]) if n else 0.0
    i, j = np.triu_indices(n, 1)
    slope = float(np.median((y[j] - y[i]) / (j - i)))
    intercept = float(np.median(y - slope * np.arange(n)))
    return slope, intercept


def safe_log(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    positive = y[y > 0]
    floor = positive.min() / 2 if positive.size else 1.0
    return np.log(np.maximum(y, floor))


def detect_spikes(y: np.ndarray) -> np.ndarray:
    """Boolean mask of upward outliers (news spikes) relative to the trend."""
    ly = safe_log(y)
    slope, intercept = sen_slope(ly)
    resid = ly - (intercept + slope * np.arange(len(ly)))
    med = np.median(resid)
    mad = np.median(np.abs(resid - med))
    if mad == 0:
        return np.zeros(len(y), dtype=bool)
    robust_z = 0.6745 * (resid - med) / mad
    return robust_z > SPIKE_Z


def despike(y: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Replace spike points by the trend line value (in log space)."""
    y = np.asarray(y, dtype=float).copy()
    if not mask.any():
        return y
    ly = safe_log(y)
    slope, intercept = sen_slope(ly[~mask]) if (~mask).sum() >= 2 else sen_slope(ly)
    x = np.arange(len(y))
    # re-anchor intercept on non-spike points
    intercept = float(np.median(ly[~mask] - slope * x[~mask]))
    y[mask] = np.exp(intercept + slope * x[mask])
    return y


def annual_growth(y: np.ndarray, steps_per_year: int) -> float:
    """Sen slope of log(y), expressed as % change per year."""
    slope, _ = sen_slope(safe_log(y))
    return (math.exp(slope * steps_per_year) - 1) * 100


def recent_vs_prior(y: np.ndarray, window: int) -> tuple[float | None, int]:
    """% change of the last `window` points vs the `window` before them.

    With a full year per window this is a year-over-year comparison and is
    immune to seasonality. Falls back to half/half for short series.
    """
    y = np.asarray(y, dtype=float)
    if len(y) < 2 * window:
        window = len(y) // 2
    if window < 1:
        return None, 0
    prior, recent = y[-2 * window:-window].sum(), y[-window:].sum()
    if prior <= 0:
        return None, window
    return (recent / prior - 1) * 100, window


def verdict(p: float, growth: float, rvp: float | None) -> str:
    if p < 0.10 and abs(growth) >= 5:
        return "growing" if growth > 0 else "declining"
    if p >= 0.10 and abs(growth) < 5 and (rvp is None or abs(rvp) < 15):
        return "flat"
    return "unclear"


def confidence(m: dict, granularity: str) -> dict:
    """Points-based confidence in the verdict, with human-readable reasons."""
    score, reasons, cap = 0.0, [], None
    n = m["n_points"]
    long_enough = 24 if granularity == "monthly" else 90
    too_short = 12 if granularity == "monthly" else 28
    if n >= long_enough:
        score += 1
        reasons.append(f"+ long series ({n} {granularity} points)")
    elif n < too_short:
        cap = "low"
        reasons.append(f"- very short series ({n} points)")
    else:
        score += 0.5
        reasons.append(f"~ moderate series length ({n} points)")

    v, p = m["verdict"], m["mk_p"]
    if v in ("growing", "declining"):
        if p < 0.05:
            score += 1
            reasons.append(f"+ trend statistically significant ({fmt_p(p)})")
        else:
            score += 0.5
            reasons.append(f"~ trend only marginally significant ({fmt_p(p)})")
    elif v == "flat":
        score += 1
        reasons.append(f"+ no significant trend detected ({fmt_p(p)})")
    else:
        cap = "low"
        reasons.append("- mixed signals: trend test and year-over-year disagree")

    signs = {np.sign(x) for x in (m["growth_pct_per_year"], m["recent_vs_prior_pct"],
                                  m["recent_vs_prior_pct_despiked"]) if x is not None}
    if v == "flat" or len(signs) == 1:
        score += 1
        reasons.append("+ trend, year-over-year and spike-free comparisons agree")
    else:
        reasons.append("- trend and period-over-period comparisons point different ways")

    spike_share = m["spike_share_pct"]
    survives = m["verdict_despiked"] == v
    if spike_share < 20 and survives:
        score += 1
        if m["spike_count"]:
            reasons.append(f"+ result holds without the {m['spike_count']} spike(s)")
        else:
            reasons.append("+ no news spikes distorting the series")
    else:
        reasons.append(f"- spikes carry {spike_share:.0f}% of views"
                       + ("" if survives else "; conclusion changes without them"))

    med = m["median_views"]
    solid, modest = (1000, 100) if granularity == "monthly" else (30, 3)
    if med >= solid:
        score += 1
        reasons.append(f"+ solid volume (median {med:,.0f} views/{_unit(granularity)})")
    elif med >= modest:
        score += 0.5
        reasons.append(f"~ modest volume (median {med:,.0f} views/{_unit(granularity)})")
    else:
        cap = "low"
        reasons.append(f"- low volume (median {med:,.0f} views/{_unit(granularity)}): noisy")

    if cap is None and n < (12 if granularity == "monthly" else 365):
        cap = "medium"
        reasons.append("- less than a year of data: seasonality cannot be separated from "
                       "trend, and %/yr is an extrapolation")
    level = "high" if score >= 4 else "medium" if score >= 2.5 else "low"
    if cap == "low" or (cap == "medium" and level == "high"):
        level = cap
    return {"level": level, "score": score, "max_score": 5, "reasons": reasons}


def fmt_p(p: float) -> str:
    return "p<0.001" if p < 0.001 else f"p={p:.3f}"


def _unit(granularity: str) -> str:
    return "month" if granularity == "monthly" else "day"


def split_seasonal(spikes: np.ndarray, months: list[int] | None) -> tuple[np.ndarray, list[int]]:
    """Outliers that recur in the same calendar month in 2+ years are seasonal
    peaks (exam season, school year start), not news spikes."""
    if months is None or not spikes.any():
        return np.zeros_like(spikes), []
    seasonal = []
    for mo in sorted({months[i] for i in np.flatnonzero(spikes)}):
        if sum(1 for i in np.flatnonzero(spikes) if months[i] == mo) >= 2:
            seasonal.append(mo)
    mask = np.array([bool(spikes[i]) and months[i] in seasonal for i in range(len(spikes))])
    return mask, seasonal


def describe(views: np.ndarray, share: np.ndarray, granularity: str,
             months: list[int] | None = None) -> dict:
    """All metrics for one series. `share` = views per million wiki views.
    `months` = calendar month of each point (monthly data), for seasonality."""
    steps = 12 if granularity == "monthly" else 365
    window = 12 if granularity == "monthly" else 30
    outliers = detect_spikes(share)
    seasonal_mask, seasonal_months = split_seasonal(
        outliers, months if granularity == "monthly" else None)
    spikes = outliers & ~seasonal_mask
    clean = despike(share, spikes)

    slope_log, _ = sen_slope(safe_log(share))
    mk = mann_kendall(safe_log(share), slope_log)
    mk_clean = mann_kendall(safe_log(clean))
    growth = annual_growth(share, steps)
    growth_clean = annual_growth(clean, steps)
    rvp, win = recent_vs_prior(share, window)
    rvp_clean, _ = recent_vs_prior(clean, window)
    raw_rvp, _ = recent_vs_prior(views, window)

    views_clean = despike(views, spikes)
    excess = float((views - views_clean)[spikes].sum())
    total = float(views.sum())

    m = {
        "n_points": int(len(views)),
        "total_views": int(total),
        "median_views": float(np.median(views)),
        "median_per_million": float(np.median(share)),
        "growth_pct_per_year": growth,
        "growth_pct_per_year_despiked": growth_clean,
        "raw_growth_pct_per_year": annual_growth(views, steps),
        "recent_vs_prior_pct": rvp,
        "recent_vs_prior_pct_despiked": rvp_clean,
        "raw_recent_vs_prior_pct": raw_rvp,
        "comparison_window": win,
        "mk_p": mk["p"],
        "mk_p_uncorrected": mk["p_raw"],
        "autocorr_lag1": mk["autocorr_lag1"],
        "spike_count": int(spikes.sum()),
        "spike_mask": spikes.tolist(),
        "seasonal_peak_months": seasonal_months,
        "spike_share_pct": (excess / total * 100) if total > 0 else 0.0,
    }
    m["verdict"] = verdict(mk["p"], growth, rvp)
    m["verdict_despiked"] = verdict(mk_clean["p"], growth_clean, rvp_clean)
    m["confidence"] = confidence(m, granularity)
    return m


def rank(rows: list[dict], weights: dict[str, float]) -> list[dict]:
    """Composite attractiveness score. Components are min-max scaled within
    the compared set, so the score is relative: 1.0 = best in this set."""
    usable = [r for r in rows if r.get("metrics")]
    if len(usable) < 2:
        return []
    comps = {
        "growth": [r["metrics"]["growth_pct_per_year"] for r in usable],
        "volume": [math.log10(max(r["metrics"]["median_views"], 1)) for r in usable],
        "trust": [r["metrics"]["confidence"]["score"] / 5 for r in usable],
    }
    scaled = {}
    for k, vals in comps.items():
        lo, hi = min(vals), max(vals)
        scaled[k] = [0.5 if hi == lo else (v - lo) / (hi - lo) for v in vals]
    total_w = sum(weights.values()) or 1.0
    out = []
    for i, r in enumerate(usable):
        parts = {k: scaled[k][i] for k in comps}
        score = sum(weights.get(k, 0) * parts[k] for k in comps) / total_w
        out.append({"id": r["id"], "score": round(score, 3),
                    "components": {k: round(v, 3) for k, v in parts.items()}})
    out.sort(key=lambda x: -x["score"])
    for i, o in enumerate(out, 1):
        o["rank"] = i
    return out
