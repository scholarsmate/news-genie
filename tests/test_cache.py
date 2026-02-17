import time

from newsgenie.util.cache import TTLCache


def test_get_miss():
    c = TTLCache(60)
    assert c.get("missing") is None


def test_set_and_get():
    c = TTLCache(60)
    c.set("k", [1, 2, 3])
    assert c.get("k") == [1, 2, 3]


def test_ttl_expiry():
    c = TTLCache(1)
    c.set("k", "v")
    assert c.get("k") == "v"
    time.sleep(1.1)
    assert c.get("k") is None


def test_get_or_set_caches():
    c = TTLCache(60)
    calls = []

    def factory():
        calls.append(1)
        return "computed"

    assert c.get_or_set("k", factory) == "computed"
    assert c.get_or_set("k", factory) == "computed"
    assert len(calls) == 1, "Factory should only be called once"
