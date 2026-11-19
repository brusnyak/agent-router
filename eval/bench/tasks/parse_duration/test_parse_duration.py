import pytest
from parse_duration import parse_duration as p
def test_units(): assert p("1h30m") == 5400 and p("45s") == 45 and p("2d") == 172800
def test_combo(): assert p("1d2h3m4s") == 93784
def test_bare(): assert p("90") == 90
def test_space_case(): assert p("1H 30M") == 5400
def test_bad():
    for bad in ("", "abc", "5x", "h"):
        with pytest.raises(ValueError): p(bad)
