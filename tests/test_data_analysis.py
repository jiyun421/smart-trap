import matplotlib

matplotlib.use("Agg")
import pandas as pd
import pytest

from src.data_analysis import (env_vs_detection, hourly_profile, plot_hourly_profile, plot_location_comparison,
                               plot_trap_location_conversion, quality_report, setup_style)
from src.metrics import aggregate_performance
from src.synthetic_data import generate_scenario


@pytest.fixture(scope="module")
def data():
    setup_style()
    return generate_scenario(write=False)


def test_hourly_profile_counts_only_rat(data):
    ev = data["detection_events"]
    prof = hourly_profile(ev)
    assert list(prof.index) == list(range(24))
    assert prof.sum() == (ev["classification"] == "rat").sum()


def test_quality_report_values(data):
    rep = quality_report(data["trap_day_summary"], data["detection_events"])
    assert rep["duplicate_event_ids"] == 0
    assert rep["zero_operating_rows"] == 1
    assert 0 < rep["unclassified_rate"] < 0.1


def test_env_analysis_uses_ratio_to_location_mean(data):
    d, rho, p = env_vs_detection(data["trap_day_summary"])
    assert (d["operating_hours"] >= 6).all() and d["avg_temperature_c"].notna().all()
    assert -1 <= rho <= 1 and 0 <= p <= 1


def test_plots_render_without_error(data):
    s = data["trap_day_summary"]
    figs = [plot_location_comparison(aggregate_performance(s)),
            plot_trap_location_conversion(aggregate_performance(s, by=("trap_id", "location_id"))),
            plot_hourly_profile(data["detection_events"])[0]]
    for f in figs:
        assert f.axes
        matplotlib.pyplot.close(f)
