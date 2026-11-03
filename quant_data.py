# -*- coding: utf-8 -*-
"""
quant_data.py —— 量化数据层（块29）

职责：行情抓取（腾讯 hfq 日线）+ 本地 JSON 缓存（TTL 过期）。
设计原则（块29 教学点）：
1. 网络隔离：只有 fetch_remote 触网；fetcher 可注入 → 单元测试完全不触网
2. 缓存透明：get_close() 是唯一入口，调用方不感知缓存
3. 输入校验前置：symbol/日期严格正则校验；动态路径限定在缓存目录内
"""
import json
import os
import re
import time
import urllib.request
import datetime as dt
from pathlib import Path

API_HOST = "https://web.ifzq.gtimg.cn"
SYMBOL_RE = re.compile(r"^(sh|sz)\d{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_TTL = 12 * 3600.0  # 12 小时


def validate_symbol(symbol: str) -> None:
    if not isinstance(symbol, str) or not SYMBOL_RE.match(symbol):
        raise ValueError(f"非法行情代码: {symbol!r}")


def validate_date(s: str) -> None:
    if not isinstance(s, str) or not DATE_RE.match(s) or ".." in s:
        raise ValueError(f"非法日期: {s!r}")


def _safe_path(cache_dir: str, symbol: str, beg: str, suffix: str) -> str:
    """缓存路径构造：组件全部通过严格正则校验，且 realpath 后必须仍在缓存目录内。"""
    validate_symbol(symbol)
    validate_date(beg)
    root = os.path.realpath(cache_dir)
    candidate = os.path.join(root, f"{symbol}_{beg}{suffix}")
    if ".." in symbol or ".." in beg or not os.path.realpath(candidate).startswith(root + os.sep):
        raise ValueError("缓存路径越界")
    return candidate


def _cache_path(cache_dir: str, symbol: str, beg: str) -> str:
    """get_close 与测试共用的缓存路径入口。"""
    return _safe_path(cache_dir, symbol, beg, ".json")


def cache_is_fresh(path: str, ttl: float = DEFAULT_TTL, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    try:
        return (now - os.path.getmtime(path)) < ttl
    except OSError:
        return False


def load_cache(path: str) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("缓存格式错误：应为 {date: close} 字典")
    return {str(k): float(v) for k, v in obj.items()}


def save_cache(path: str, rows: dict) -> None:
    root = os.path.dirname(path) or "."
    target = Path(_safe_path(root, *_split_parts(path), ".json"))
    tmp = Path(str(target) + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(rows, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(str(tmp), str(target))


def _split_parts(path: str) -> tuple[str, str]:
    """从完整路径反解出 (symbol, beg)，供 save_cache 复用同一套校验。"""
    basename = os.path.basename(path)
    m = re.match(r"^((?:sh|sz)\d{6})_(\d{4}-\d{2}-\d{2})\.json$", basename)
    if not m:
        raise ValueError(f"缓存文件名不符合约定: {basename!r}")
    return m.group(1), m.group(2)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 禁止任何重定向（供应链安全课：不跟随到未知域）


def fetch_remote(symbol: str, beg: str, end: str | None = None,
                 host: str = API_HOST, opener=None,
                 page_pause: float = 0.35, max_pages: int = 15) -> dict:
    """腾讯 hfq 日线分页抓取，返回 {date: close}。

    opener 可注入：测试传 FakeOpener，完全不触网。
    仅当使用真实网络（opener 为 None）时强制域名白名单断言。
    """
    validate_symbol(symbol)
    end = end or dt.date.today().isoformat()
    if opener is None:
        assert host == API_HOST, "真实网络只允许白名单域名"
        opener = urllib.request.build_opener(_NoRedirect())
    rows: dict = {}
    for _page in range(max_pages):
        url = f"{host}/appstock/app/fqkline/get?param={symbol},day,,{end},640,hfq"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://gu.qq.com/"})
        data = json.load(opener.open(req, timeout=20))
        node = data["data"][symbol]
        key = next((k for k in node if "day" in k), None)
        arr = node.get(key, []) if key else []
        if not arr:
            break
        n0 = len(rows)
        for r in arr:
            rows[r[0]] = float(r[2])  # [date, open, close, high, low, volume]
        earliest = min(rows)
        if earliest <= beg or len(rows) == n0:
            break
        end = (dt.date.fromisoformat(earliest) - dt.timedelta(days=1)).isoformat()
        if page_pause:
            time.sleep(page_pause)
    return rows


def get_close(symbol: str, beg: str = "2012-01-01", end: str | None = None,
              cache_dir: str = DEFAULT_CACHE_DIR, ttl: float = DEFAULT_TTL,
              fetcher=fetch_remote, use_cache: bool = True,
              now: float | None = None) -> dict:
    """唯一入口：新鲜缓存直接返回；过期/缺失则经 fetcher 抓取并落盘。"""
    path = _safe_path(cache_dir, symbol, beg, ".json")
    if use_cache and cache_is_fresh(path, ttl, now):
        return load_cache(path)
    rows = dict(fetcher(symbol, beg, end))
    if not rows:
        raise RuntimeError(f"{symbol} 未取到任何行情数据")
    if use_cache:
        save_cache(path, rows)
    return rows
