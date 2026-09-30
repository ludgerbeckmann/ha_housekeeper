from datetime import datetime, timedelta, timezone

from custom_components.ha_housekeeper.pool_dry_run import DryRunDetector, in_range

T0 = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def test_in_range_inclusive_and_unknown():
    assert in_range(75, 75, 100) and in_range(100, 75, 100)
    assert not in_range(74.9, 75, 100) and not in_range(100.1, 75, 100)
    assert not in_range(None, 75, 100)


def test_triggers_after_duration():
    d = DryRunDetector(75, 100, timedelta(minutes=5))
    assert not d.update(T0, True, 90)
    assert not d.update(T0 + timedelta(minutes=4, seconds=59), True, 90)
    assert d.update(T0 + timedelta(minutes=5), True, 90)


def test_leaving_range_resets():
    d = DryRunDetector(75, 100, timedelta(minutes=5))
    d.update(T0, True, 90)
    d.update(T0 + timedelta(minutes=3), True, 250)  # normale Last
    assert d.since is None
    assert not d.update(T0 + timedelta(minutes=6), True, 90)  # Timer startet neu


def test_pump_off_or_sensor_unavailable_resets():
    d = DryRunDetector(75, 100, timedelta(minutes=5))
    d.update(T0, True, 90)
    d.update(T0 + timedelta(minutes=2), False, 90)
    assert d.since is None
    d.update(T0 + timedelta(minutes=3), True, 90)
    d.update(T0 + timedelta(minutes=4), True, None)
    assert d.since is None
