# -*- coding: utf-8 -*-
"""quant_data 单元测试：全部使用合成数据与注入的假 fetcher/opener，零网络。"""
import json
import os
import time

import pytest

import quant_data as qd


def test_validate_symbol_rejects_garbage():
    for bad in ["", "SH600000", "sh60000", "sh6000001", "sh60000a",
                "sh600000;rm -rf", "sh600000/../../etc", None, 42]:
        with pytest.raises(ValueError):
            qd.validate_symbol(bad)


def test_validate_symbol_accepts_real_codes():
    qd.validate_symbol("sh510300")
    qd.validate_symbol("sz159915")


def test_validate_date_rejects_garbage():
    for bad in ["", "2024/01/02", "2024-1-2", "2024-01-02/../etc", None, "2024-01-02;ls"]:
        with pytest.raises(ValueError):
            qd.validate_date(bad)


def test_cache_path_rejects_traversal():
    with pytest.raises(ValueError):
        qd._cache_path("data", "sh510300", "2012-01-01/../../etc")


def test_cache_roundtrip(tmp_path):
    path = qd._safe_path(str(tmp_path), "sh510300", "2012-01-01", ".json")
    rows = {"2024-01-02": 4.05, "2024-01-03": 4.04}
    qd.save_cache(path, rows)
    assert qd.load_cache(path) == {"2024-01-02": 4.05, "2024-01-03": 4.04}


def test_get_close_uses_fresh_cache_without_network(tmp_path):
    path = qd._safe_path(str(tmp_path), "sh510300", "2012-01-01", ".json")
    rows = {"2024-01-02": 4.05}
    qd.save_cache(path, rows)

    def must_not_fetch(*a, **k):
        raise AssertionError("缓存新鲜时不应触网")

    got = qd.get_close("sh510300", cache_dir=str(tmp_path), fetcher=must_not_fetch)
    assert got == {"2024-01-02": 4.05}


def test_get_close_refetches_when_expired(tmp_path):
    path = qd._cache_path(str(tmp_path), "sh510300", "2012-01-01")
    qd.save_cache(path, {"2024-01-02": 4.05})
    old = time.time() - (qd.DEFAULT_TTL + 3600)
    os.utime(path, (old, old))  # 把 mtime 回拨到 TTL 之外

    def fake_fetcher(symbol, beg, end=None):
        assert symbol == "sh510300"
        return {"2024-01-02": 4.10, "2024-01-03": 4.11}

    got = qd.get_close("sh510300", cache_dir=str(tmp_path), fetcher=fake_fetcher)
    assert got == {"2024-01-02": 4.10, "2024-01-03": 4.11}
    assert qd.load_cache(path) == {"2024-01-02": 4.10, "2024-01-03": 4.11}


def test_get_close_raises_on_empty_fetch(tmp_path):
    def empty_fetcher(symbol, beg, end=None):
        return {}

    with pytest.raises(RuntimeError):
        qd.get_close("sh510300", cache_dir=str(tmp_path), fetcher=empty_fetcher)


def test_get_close_rejects_bad_symbol(tmp_path):
    with pytest.raises(ValueError):
        qd.get_close("sh600000;rm", cache_dir=str(tmp_path), fetcher=lambda *a: {})


def test_fetch_remote_parses_payload_and_enforces_host():
    captured = []

    class FakeResponse:
        def __init__(self, payload):
            self._p = payload

        def read(self):
            return json.dumps(self._p).encode("utf-8")

    class FakeOpener:
        def __init__(self, payloads):
            self.payloads = list(payloads)
            self.urls = []

        def open(self, req, timeout=None):
            self.urls.append(req.full_url)
            return FakeResponse(self.payloads.pop(0))

    page1 = {"data": {"sh510300": {"hfqday": [
        ["2024-01-08", "1.5", "1.52", "1.53", "1.49", "1000"],
        ["2024-01-09", "1.5", "1.51", "1.55", "1.50", "1100"],
        ["2024-01-10", "1.5", "1.50", "1.52", "1.48", "1200"],
    ]}}}
    page2 = {"data": {"sh510300": {"hfqday": [
        ["2024-01-05", "1.5", "1.49", "1.50", "1.47", "900"],
    ]}}}
    fo = FakeOpener([page1, page2])
    rows = qd.fetch_remote("sh510300", beg="2024-01-05", end="2024-01-10",
                           host=qd.API_HOST, opener=fo, page_pause=0)
    assert rows == {"2024-01-08": 1.52, "2024-01-09": 1.51, "2024-01-10": 1.50,
                    "2024-01-05": 1.49}
    assert len(fo.urls) == 2
    assert "param=sh510300,day,,2024-01-07,640,hfq" in fo.urls[1]
    for u in fo.urls:
        assert u.startswith("https://web.ifzq.gtimg.cn/")


def test_fetch_remote_rejects_bad_symbol():
    with pytest.raises(ValueError):
        qd.fetch_remote("sh600000/../../admin", beg="2024-01-01",
                        opener=object())
