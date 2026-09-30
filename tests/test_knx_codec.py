"""Tests der reinen KNX-Hilfsfunktionen."""

import pytest

from custom_components.ha_housekeeper.knx_codec import (
    decode_dimming,
    decode_percent,
    decode_scene,
    decode_switch,
    is_valid_ga,
    normalize_ga,
    truncate_text,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1/2/3", "1/2/3"),
        (" 1/2/3 ", "1/2/3"),
        ("1/515", "1/2/3"),      # 2-Ebenen-Schreibweise
        ("2563", "1/2/3"),       # freie Schreibweise
        ("0/0/0", "0/0/0"),
        ("31/7/255", "31/7/255"),
    ],
)
def test_normalize_ga(value, expected):
    assert normalize_ga(value) == expected
    assert is_valid_ga(value)


@pytest.mark.parametrize("value", ["", "a", "1/2", "32/0/0", "1/8/0", "1/2/256", "1/2/3/4", "70000", None])
def test_invalid_ga(value):
    if value == "1/2":  # 2-Ebenen-Adresse ist gültig
        assert is_valid_ga(value)
        return
    assert normalize_ga(value) is None and not is_valid_ga(value)


def test_decode_switch():
    assert decode_switch(1) is True and decode_switch(0) is False
    assert decode_switch(2) is None and decode_switch((1,)) is None and decode_switch(True) is None


def test_decode_percent():
    assert decode_percent((0,)) == 0
    assert decode_percent((128,)) == 50
    assert decode_percent((255,)) == 100
    assert decode_percent(5) is None and decode_percent((1, 2)) is None


def test_decode_scene_is_one_based():
    assert decode_scene((0,)) == 1
    assert decode_scene((63,)) == 64
    assert decode_scene((64,)) is None


def test_decode_dimming():
    assert decode_dimming(0b1011) == (True, 3)    # heller/lauter, Schritt 3
    assert decode_dimming(0b0011) == (False, 3)   # dunkler/leiser
    assert decode_dimming(0b1000) == (True, 0)    # Stopp
    assert decode_dimming(16) is None and decode_dimming((1,)) is None


def test_truncate_text():
    assert truncate_text("Zürich Hbf abcdefgh") == "Zürich Hbf abc"
    assert truncate_text(None) == ""
    assert truncate_text("日本語") == "???"   # nicht in ISO 8859-1 darstellbar
