# -*- coding: utf-8 -*-
"""
引擎A（ETF 动量轮动）的本机复现回测 —— 纯 Python，零依赖。
数据：东方财富 K 线接口，后复权（fqt=2），对应《交易系统.md》第 4 章。
诚实声明：这是回测，不是实盘；未建模 QDII 溢价约束与涨跌停不可成交细节；
成本按双边 0.27% 计（佣金+印花税+滑点）。仅用于验证协议的第一步。
"""
import urllib.request, urllib.parse, json, math, re, time
from collections import defaultdict

# --- 安全约束：固定协议+域名白名单，symbol 白名单校验，禁用重定向 ---
API_HOST = "https://web.ifzq.gtimg.cn"
import datetime as _dt

def fetch(secid, beg="2012-01-01"):
    # secid 仅用于路由：'1.' -> 沪市(sh)，'0.' -> 深市(sz)
    prefix = {"1.": "sh", "0.": "sz"}.get(secid[:2])
    assert prefix in ("sh", "sz"), f"非法 secid: {secid!r}"
    symbol = prefix + secid.split(".")[1]
    rows = {}
    end = _dt.date.today().isoformat()
    opener = urllib.request.build_opener(_NoRedirect())
    for _page in range(15):
        url = f"{API_HOST}/appstock/app/fqkline/get?param={symbol},day,,{end},640,hfq"
        assert urllib.parse.urlparse(url).hostname == "web.ifzq.gtimg.cn"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://gu.qq.com/"})
        d = json.load(opener.open(req, timeout=20))
        node = d["data"][symbol]
        key = next(k for k in node if "day" in k)
        arr = node[key]
        if not arr: break
        n0 = len(rows)
        for r in arr: rows[r[0]] = float(r[2])   # [date, open, close, high, low, vol]
        earliest = min(rows)
        if earliest <= beg or len(rows) == n0: break
        end = ( _dt.date.fromisoformat(earliest) - _dt.timedelta(days=1) ).isoformat()
        time.sleep(0.4)
    return rows

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 禁止任何重定向

ASSETS = {  # name -> secid
    "HS300":  "1.510300",  # 沪深300
    "ZZ1000": "1.512100",  # 中证1000
    "CYB":    "0.159915",  # 创业板
    "HLDB":   "1.512890",  # 红利低波
    "SP500":  "1.513500",  # 标普500(QDII)
    "HSTK":   "1.513180",  # 恒生科技(QDII)
    "BOND":   "1.511010",  # 国债ETF
    "CASH":   "1.511990",  # 货币ETF(华宝添益)
}
STOCKS = ["HS300", "ZZ1000", "CYB", "HLDB", "SP500", "HSTK"]
TOP_N, MOM_LEN, VOL_LEN, TARGET_VOL, COST = 2, 240, 20, 0.12, 0.0027

raw = {k: fetch(v) for k, v in ASSETS.items()}
cal = sorted(raw["HS300"].keys())            # 沪深300日历为主日历(SSE)
first = {k: min(d.keys()) for k, d in raw.items()}
def px(k, date):                              # 上市前 None，之后前向填充
    if date < first[k]: return None
    return raw[k].get(date)

# 月末交易日
month_last = {}
for d in cal:
    month_last[d[:7]] = d
me = [month_last[m] for m in sorted(month_last)]

def run(label, stock_pool, start=None):
    prev_w, dates_used, recs = {"CASH": 1.0}, [], []
    for t in me:
        idx = cal.index(t)
        if idx < MOM_LEN + VOL_LEN: continue
        mom = {}
        for k in stock_pool:
            p0, p1 = px(k, cal[idx - MOM_LEN]), px(k, t)
            if p0 and p1: mom[k] = p1 / p0 - 1
        c0, c1 = px("CASH", cal[idx - MOM_LEN]), px("CASH", t)
        cash_mom = (c1 / c0 - 1) if (c0 and c1) else 0.015
        elig = sorted([k for k in mom if mom[k] > cash_mom], key=lambda k: -mom[k])[:TOP_N]
        new = {k: 1.0 / TOP_N for k in elig}
        bond_w = 1.0 - sum(new.values())
        if bond_w > 1e-9: new["BOND"] = new.get("BOND", 0) + bond_w
        vols = []
        for k in [x for x in new if x in STOCKS]:
            ps = [px(k, cal[idx - j]) for j in range(VOL_LEN + 1)][::-1]
            rs = [ps[j] / ps[j - 1] - 1 for j in range(1, len(ps)) if ps[j] and ps[j - 1]]
            if len(rs) > 5:
                mu = sum(rs) / len(rs)
                vol = math.sqrt(sum((r - mu) ** 2 for r in rs) / (len(rs) - 1)) * math.sqrt(243)
                vols.append(vol)
        pv = sum(vols) / len(vols) if vols else 0
        scale = min(1.0, TARGET_VOL / pv) if pv > 0 else 1.0
        for k in list(new):
            if k in STOCKS: new[k] *= scale
        cash_w = 1.0 - sum(new.values())
        if cash_w > 1e-9: new["CASH"] = new.get("CASH", 0) + cash_w
        if start and t < start: continue
        if dates_used:
            t0 = dates_used[-1]
            port_r = 0.0
            for k, w in prev_w.items():
                a, b = px(k, t0), px(k, t)
                if a and b: port_r += w * (b / a - 1)
            turn = sum(abs(new.get(k, 0) - prev_w.get(k, 0)) for k in set(new) | set(prev_w)) / 2
            port_r -= turn * 2 * COST
            recs.append((t, port_r, turn))
        prev_w, dates_used = new, dates_used + [t]
    return recs

def stats(recs, label):
    if not recs:
        print(f"\n=== {label} === 无数据"); return
    v, curve, peak, mdd = 1.0, [1.0], 1.0, 0.0
    for _, r, _ in recs:
        v *= (1 + r); curve.append(v); peak = max(peak, v); mdd = max(mdd, 1 - v / peak)
    years = len(recs) / 12.0
    cagr = v ** (1 / years) - 1
    rs = [r for _, r, _ in recs]
    mu = sum(rs) / len(rs)
    vol = math.sqrt(sum((x - mu) ** 2 for x in rs) / (len(rs) - 1)) * math.sqrt(12)
    win = sum(1 for x in rs if x > 0) / len(rs)
    worst = min(rs)
    print(f"\n=== {label} ===")
    print(f"区间: {recs[0][0]} ~ {recs[-1][0]}  ({years:.1f} 年, {len(recs)} 个月)")
    print(f"累计 {v:.3f}x | CAGR {cagr*100:.2f}% | 年化波动 {vol*100:.2f}% | 夏普 {(cagr-0.015)/vol:.2f}")
    print(f"月度胜率 {win*100:.1f}% | 最差月 {worst*100:.2f}% | 最大回撤 {mdd*100:.2f}%")
    yr = defaultdict(lambda: 1.0)
    for t, r, _ in recs: yr[t[:4]] *= (1 + r)
    print("年度: " + "  ".join(f"{y}:{(x-1)*100:+.1f}%" for y, x in sorted(yr.items())))

stats(run("全池-8资产", STOCKS), "引擎A 全池 12月动量+绝对动量门+波动率目标(12%)")
stats(run("经典3资产", ["HS300", "CYB"]), "引擎A 经典3资产(300/创业板/国债) 同规则")

def bh(label, k):
    recs = []
    ms = [d for d in me if px(k, d) and cal.index(d) > MOM_LEN]
    for i in range(1, len(ms)):
        recs.append((ms[i], px(k, ms[i]) / px(k, ms[i-1]) - 1, 0))
    stats(recs, label)
bh("对照-买入持有 沪深300", "HS300")
bh("对照-买入持有 红利低波", "HLDB")
