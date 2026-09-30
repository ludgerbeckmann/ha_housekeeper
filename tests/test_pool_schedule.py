from datetime import datetime, timezone

from custom_components.ha_housekeeper.pool_schedule import (
    describe_window,
    is_active,
    next_start,
    parse_windows,
)

UTC = timezone.utc
ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def at(day, hh, mm=0):
    # 2026-09-28 ist ein Montag
    return datetime(2026, 9, day, hh, mm, tzinfo=UTC)


def test_simple_window():
    w = parse_windows([{"start": "08:00:00", "end": "10:00:00", "days": ALL}])
    assert not is_active(w, at(28, 7, 59))
    assert is_active(w, at(28, 8, 0))
    assert is_active(w, at(28, 9, 59))
    assert not is_active(w, at(28, 10, 0))


def test_weekday_filter():
    w = parse_windows([{"start": "08:00", "end": "10:00", "days": ["mon"]}])
    assert is_active(w, at(28, 9))
    assert not is_active(w, at(29, 9))


def test_overnight_window_uses_start_day():
    w = parse_windows([{"start": "22:00", "end": "02:00", "days": ["mon"]}])
    assert is_active(w, at(28, 23))
    assert is_active(w, at(29, 1))  # Dienstag früh gehört zum Montags-Fenster
    assert not is_active(w, at(29, 23))
    assert not is_active(w, at(28, 1))


def test_invalid_windows_ignored():
    w = parse_windows(
        [
            {"start": "08:00", "end": "08:00", "days": ALL},
            {"start": "08:00", "end": "09:00", "days": []},
            {"start": "x", "end": "09:00", "days": ALL},
            {"end": "09:00"},
        ]
    )
    assert w == []


def test_next_start():
    w = parse_windows(
        [
            {"start": "08:00", "end": "10:00", "days": ALL},
            {"start": "18:00", "end": "19:00", "days": ["wed"]},
        ]
    )
    assert next_start(w, at(28, 7)) == at(28, 8)
    assert next_start(w, at(28, 8)) == at(29, 8)  # strikt nach jetzt
    assert next_start(w, at(30, 12)) == at(30, 18)  # Mittwoch 18:00
    assert next_start([], at(28, 7)) is None


def test_next_start_weekly_only():
    w = parse_windows([{"start": "08:00", "end": "10:00", "days": ["mon"]}])
    assert next_start(w, at(28, 9)) == datetime(2026, 10, 5, 8, tzinfo=UTC)


def test_describe():
    w = parse_windows([{"start": "08:00", "end": "10:00", "days": ["mon", "tue"]}])[0]
    assert describe_window(w, "de") == "08:00–10:00 (Mo, Di)"
    assert describe_window(w, "en") == "08:00–10:00 (Mon, Tue)"
