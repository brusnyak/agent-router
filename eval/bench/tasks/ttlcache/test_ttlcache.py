from ttlcache import TTLCache
class Clock:
    t = 0.0
    def __call__(self): return self.t
def test_get_set():
    c = TTLCache(2, 10, Clock()); c.set("a", 1); assert c.get("a") == 1 and c.get("zz", 7) == 7
def test_ttl():
    k = Clock(); c = TTLCache(2, 10, k); c.set("a", 1); k.t = 11; assert c.get("a") is None and len(c) == 0
def test_lru():
    c = TTLCache(2, 100, Clock()); c.set("a", 1); c.set("b", 2); c.get("a"); c.set("c", 3)
    assert c.get("b") is None and c.get("a") == 1 and c.get("c") == 3 and len(c) == 2
