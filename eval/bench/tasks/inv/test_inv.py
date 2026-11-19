import pytest
from inv.parse import parse_lines
from inv.price import total, apply_discount
from inv.report import render
TEXT = "# inventory\nA1,2,3.50\nB2,1,10.00\n\nC3,4,0.25\n"
def test_parse():
    items = parse_lines(TEXT)
    assert items == [{"sku": "A1", "qty": 2, "price": 3.5}, {"sku": "B2", "qty": 1, "price": 10.0}, {"sku": "C3", "qty": 4, "price": 0.25}]
def test_parse_error_has_line_number():
    with pytest.raises(ValueError, match="2"): parse_lines("A1,2,3.5\nbroken\n")
def test_price():
    items = parse_lines(TEXT)
    assert total(items) == 18.0 and apply_discount(18.0, 10) == 16.2
    with pytest.raises(ValueError): apply_discount(1.0, 101)
def test_render():
    items = parse_lines(TEXT)
    assert render(items) == "A1 x2 @ 3.50 = 7.00\nB2 x1 @ 10.00 = 10.00\nC3 x4 @ 0.25 = 1.00\nTOTAL: 18.00"
    assert render(items, 10).endswith("TOTAL: 16.20")
