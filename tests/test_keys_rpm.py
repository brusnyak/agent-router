from backbone.keys import KeyPool, Transient
from backbone.core import swarm_cap

ENV = {"NIM_1": "a", "NIM_2": "b"}


def mk(**kw):
    t = [0.0]
    sl = lambda s: t.__setitem__(0, t[0] + s)
    return KeyPool(["NIM_1", "NIM_2"], env=ENV, clock=lambda: t[0], sleep=sl, **kw), t


def test_unlimited_concurrency():
    p, _ = mk()
    ls = [p.lease() for _ in range(10)]
    for l in ls:
        l.__enter__()
    assert p._sem == {}


def test_81st_waits_then_raises():
    p, t = mk(wait_s=30)
    for _ in range(80):
        with p.lease():
            pass
    assert p.status()["NIM_1"]["in_window"] == 40
    try:
        with p.lease():
            pass
        assert False
    except Transient:
        pass
    p.wait_s = 120
    with p.lease():
        pass
    assert t[0] >= 30


def test_fewest_in_window():
    p, _ = mk()
    for _ in range(3):
        with p.lease(prefer="NIM_1"):
            pass
    p._win["NIM_1"] += [0.0] * 5
    with p.lease() as n:
        assert n == "NIM_2"


def test_retry_after_cools_only_that_key():
    p, _ = mk()
    p.report("NIM_1", False, retry_after=30)
    p.report("NIM_2", False)
    s = p.status()
    assert s["NIM_1"]["cooling_s"] == 30 and s["NIM_2"]["cooling_s"] == 0
    with p.lease() as n:
        assert n == "NIM_2"


def test_prefer_avoid():
    p, _ = mk()
    with p.lease(prefer="NIM_2") as n:
        assert n == "NIM_2"
    p2, _ = mk()
    with p2.lease(avoid="NIM_1") as n:
        assert n == "NIM_2"


def test_swarm_cap():
    assert swarm_cap(None, 8, 40, 3) == 8
    assert swarm_cap("auto", 8, 2, 2) == 4
    assert swarm_cap(5, 8, 40, 3) == 5
    assert swarm_cap("auto", 8, 40, 0) == 8
