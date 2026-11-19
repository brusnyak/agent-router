import pytest
from csvsum import sum_column
def test_basic(): assert sum_column("a,b\n1,2\n3,4\n", "b") == 6.0
def test_quoted(): assert sum_column('name,amt\n"Smith, J",5\n"Doe",2.5\n', "amt") == 7.5
def test_blank(): assert sum_column("a,b\n1,\n,4\n", "a") == 1.0 and sum_column("a,b\n1,\n,4\n", "b") == 4.0
def test_missing():
    with pytest.raises(KeyError): sum_column("a\n1\n", "z")
