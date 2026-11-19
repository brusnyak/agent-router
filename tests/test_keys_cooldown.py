from backbone.keys import KeyPool

ENV = {"NIM_1": "a", "NIM_2": "b"}

def mk(cooldown_s=60):
    t = [0.0]
    def sleep(s):
        t[0] += s
    p = KeyPool(["NIM_1", "NIM_2"], env=ENV, cooldown_s=cooldown_s, clock=lambda: t[0], sleep=sleep, wait_s=5)
    return p, t

def test_cooldown_avoids_failed_key():
    p, t = mk()
    p.report("NIM_1", False)  # failure without Retry-After -> config cooldown
    assert p.status()["NIM_1"]["cooling_s"] > 0
    name = None
    with p.lease() as name:
        pass
    assert name == "NIM_2", name

def test_cooldown_expires():
    p, t = mk()
    p.report("NIM_1", False)
    with p.lease() as name:
        assert name == "NIM_2"
    t[0] += 60
    assert p.status()["NIM_1"]["cooling_s"] == 0
    with p.lease() as name:
        assert name == "NIM_1"

def test_zero_cooldown_means_no_cooling():
    p, t = mk(cooldown_s=0)
    p.report("NIM_1", False)
    assert p.status()["NIM_1"]["cooling_s"] == 0
    # lease is round-robin with load spreading on main, so a failed key is not guaranteed first;
    # the contract is that it stays eligible rather than being cooled out.
    seen = set()
    for _ in range(2):
        with p.lease() as name:
            seen.add(name)
    assert "NIM_1" in seen

def test_retry_after_cools_even_with_zero_config():
    p, t = mk(cooldown_s=0)
    p.report("NIM_1", False, retry_after=30)
    assert p.status()["NIM_1"]["cooling_s"] > 0
