import pytest
from chunker import chunk
def test_even(): assert chunk([1,2,3,4], 2) == [[1,2],[3,4]]
def test_tail(): assert chunk(range(5), 2) == [[0,1],[2,3],[4]]
def test_generator(): assert chunk((i for i in "abc"), 2) == [["a","b"],["c"]]
def test_empty(): assert chunk([], 3) == []
def test_bad_size():
    for s in (0, -1):
        with pytest.raises(ValueError): chunk([1], s)
