"""Statistics on synthetic series with a known answer."""

import numpy as np
import pytest

from wpv import stats

RNG = np.random.default_rng(42)
MONTHS = [(i % 12) + 1 for i in range(36)]


def noisy(level, n=36, sd=0.08, growth_per_year=0.0):
    t = np.arange(n)
    return level * np.exp(np.log1p(growth_per_year) * t / 12 + RNG.normal(0, sd, n))


def test_clear_growth_is_detected_with_high_confidence():
    share = noisy(100, growth_per_year=0.30)
    m = stats.describe(share * 50, share, "monthly", MONTHS)
    assert m["verdict"] == "growing"
    assert 15 < m["growth_pct_per_year"] < 45
    assert m["mk_p"] < 0.01
    assert m["confidence"]["level"] == "high"


def test_flat_noise_is_flat():
    share = noisy(100, sd=0.05)
    m = stats.describe(share * 50, share, "monthly", MONTHS)
    assert m["verdict"] == "flat"
    assert abs(m["growth_pct_per_year"]) < 5


def test_single_news_spike_is_flagged_and_does_not_create_a_trend():
    share = noisy(100, sd=0.05)
    share[30] *= 6  # one viral month near the end
    m = stats.describe(share * 50, share, "monthly", MONTHS)
    assert m["spike_count"] == 1 and m["spike_mask"][30]
    assert m["verdict_despiked"] == "flat"
    assert m["recent_vs_prior_pct"] > m["recent_vs_prior_pct_despiked"]


def test_yearly_peak_is_seasonal_not_spike():
    share = noisy(100, sd=0.04)
    for i, mo in enumerate(MONTHS):
        if mo == 9:
            share[i] *= 3  # school year start, every year
    m = stats.describe(share * 50, share, "monthly", MONTHS)
    assert m["seasonal_peak_months"] == [9]
    assert m["spike_count"] == 0


def test_autocorrelation_correction_makes_test_more_conservative():
    walk = np.exp(np.cumsum(RNG.normal(0, 0.15, 48)))  # random walk: no real trend
    mk = stats.mann_kendall(np.log(walk))
    assert mk["p"] >= mk["p_raw"]


def test_mann_kendall_known_values():
    mk = stats.mann_kendall(np.arange(10.0))
    assert mk["s"] == 45
    assert mk["p_raw"] < 0.001


def test_sen_slope_ignores_outlier():
    y = np.arange(20.0)
    y[5] = 500
    slope, _ = stats.sen_slope(y)
    assert slope == pytest.approx(1.0)


def test_low_volume_caps_confidence():
    share = noisy(100, growth_per_year=0.5)
    m = stats.describe(share * 0.3, share, "monthly", MONTHS)  # ~30 views/month
    assert m["confidence"]["level"] == "low"
    assert any("low volume" in r for r in m["confidence"]["reasons"])


def test_recent_vs_prior_is_year_over_year():
    y = np.array([10.0] * 12 + [15.0] * 12)
    pct, window = stats.recent_vs_prior(y, 12)
    assert window == 12 and pct == pytest.approx(50.0)


def test_rank_respects_weights():
    def row(i, g, med, score):
        return {"id": i, "metrics": {"growth_pct_per_year": g, "median_views": med,
                                     "confidence": {"score": score}}}
    rows = [row("fast-small", 40, 100, 5), row("slow-big", 0, 100_000, 5)]
    by_growth = stats.rank(rows, {"growth": 1, "volume": 0, "trust": 0})
    by_volume = stats.rank(rows, {"growth": 0, "volume": 1, "trust": 0})
    assert by_growth[0]["id"] == "fast-small"
    assert by_volume[0]["id"] == "slow-big"
    assert stats.rank(rows[:1], {"growth": 1}) == []


def test_short_daily_window_never_high_confidence():
    share = noisy(100, n=60, sd=0.03, growth_per_year=2.0)
    m = stats.describe(share * 20, share, "daily")
    assert m["verdict"] == "growing"
    assert m["confidence"]["level"] != "high"
    assert any("less than a year" in r for r in m["confidence"]["reasons"])


def test_sen_confidence_interval_contains_slope_and_widens_with_autocorrelation():
    share = noisy(100, growth_per_year=0.3, sd=0.15)
    ly = stats.safe_log(share)
    mk = stats.mann_kendall(ly)
    slope, _ = stats.sen_slope(ly)
    lo, hi = stats.sen_ci(ly, mk["var"])
    assert lo < slope < hi
    lo2, hi2 = stats.sen_ci(ly, mk["var"] * 2)
    assert lo2 <= lo and hi2 >= hi


def test_many_empty_months_cap_confidence():
    share = noisy(100, growth_per_year=0.3)
    views = share * 50
    views[::3] = 0  # a third of the months have no recorded views
    m = stats.describe(views, share, "monthly", MONTHS)
    assert m["zero_points"] == 12
    assert m["confidence"]["level"] == "low"
