import pytest

from app.benchmarks.control_plane import measure, nearest_rank, report


def test_nearest_rank_percentiles() -> None:
    samples = [float(value) for value in range(1, 21)]

    assert nearest_rank(samples, 0.50) == 10
    assert nearest_rank(samples, 0.95) == 19
    assert nearest_rank(samples, 0.99) == 20


def test_measure_requires_positive_iterations() -> None:
    with pytest.raises(ValueError, match="positive"):
        measure(lambda: None, 0)


def test_local_report_does_not_require_postgres() -> None:
    result = report(2, with_database=False)
    measurements = result["measurements"]

    assert isinstance(measurements, dict)
    assert set(measurements) == {"health_http", "in_memory_agent"}
