# -*- coding: utf-8 -*-
"""
引擎A（ETF 动量轮动）回测 —— 块29 重构版。

重构内容（相对初版）：
1. 数据层抽到 quant_data.py（本地缓存 + 可注入 fetcher，重跑秒级）
2. 纯计算抽到 quant_core.py（有单元测试覆盖）
3. 本脚本只保留"编排"：读数 → 逐月调仓 → 统计输出

诚实声明：这是回测，不是实盘；未建模 QDII 溢价与涨跌停不可成交；
成本按双边 0.27% 计。金标准：重构后输出必须与初版完全一致。
"""
import math
from collections import defaultdict

import quant_core as qc
import quant_data as qd

ASSETS = {  # name -> 行情代码（sh/sz 前缀）
    "HS300":  "sh510300",  # 沪深300
    "ZZ1000": "sh512100",  # 中证1000
    "CYB":    "sz159915",  # 创业板
    "HLDB":   "sh512890",  # 红利低波
    "SP500":  "sh513500",  # 标普500(QDII)
    "HSTK":   "sh513180",  # 恒生科技(QDII)
    "BOND":   "sh511010",  # 国债ETF
    "CASH":   "sh511990",  # 货币ETF(华宝添益)
}
STOCKS = ["HS300", "ZZ1000", "CYB", "HLDB", "SP500", "HSTK"]
TOP_N, MOM_LEN, VOL_LEN, TARGET_VOL, COST = 2, 240, 20, 0.12, 0.0027

raw = {k: qd.get_close(v) for k, v in ASSETS.items()}
cal = sorted(raw["HS300"].keys())              # 沪深300日历为主日历（SSE）
first = {k: min(d) for k, d in raw.items()}

def px(k, date):
    if date < first[k]:
        return None                             # 上市前
    return raw[k].get(date)                     # 上市后缺失日由调用方容忍

me = qc.month_ends(cal)

def run(stock_pool, start=None):
    prev_w, used, recs = {"CASH": 1.0}, [], []
    for t in me:
        idx = cal.index(t)
        if idx < MOM_LEN + VOL_LEN:
            continue
        mom = {}
        for k in stock_pool:
            m = qc.momentum(lambda d, _k=k: px(_k, d), cal, idx, MOM_LEN)
            if m is not None:
                mom[k] = m
        c0, c1 = px("CASH", cal[idx - MOM_LEN]), px("CASH", t)
        cash_mom = (c1 / c0 - 1) if (c0 and c1) else 0.015
        elig = qc.select_eligibles(mom, cash_mom, TOP_N)   # 绝对动量门 + 相对排序
        new = {k: 1.0 / TOP_N for k in elig}
        bw = 1.0 - sum(new.values())
        if bw > 1e-9:
            new["BOND"] = new.get("BOND", 0) + bw
        vols = []
        for k in [x for x in new if x in STOCKS]:
            closes = [px(k, cal[idx - j]) for j in range(VOL_LEN + 1)][::-1]
            pairs = sum(1 for i in range(1, len(closes)) if closes[i] and closes[i - 1])
            v = qc.realized_vol(closes)
            if v is not None and pairs > 5:
                vols.append(v)
        sc = qc.vol_scale(vols, TARGET_VOL)                # 波动率目标仓位
        for k in list(new):
            if k in STOCKS:
                new[k] *= sc
        cw = 1.0 - sum(new.values())
        if cw > 1e-9:
            new["CASH"] = new.get("CASH", 0) + cw
        if start and t < start:
            continue
        if used:
            t0 = used[-1]
            gross = 0.0
            for k, w in prev_w.items():
                a, b = px(k, t0), px(k, t)
                if a and b:
                    gross += w * (b / a - 1)
            turn = sum(abs(new.get(k, 0) - prev_w.get(k, 0))
                       for k in set(new) | set(prev_w)) / 2
            recs.append((t, qc.net_month_return(gross, turn, COST)))
        prev_w, used = new, used + [t]
    return recs

def stats(recs, label):
    if not recs:
        print(f"\n=== {label} === 无数据")
        return
    v = 1.0
    for _, r in recs:
        v *= (1 + r)
    years = len(recs) / 12.0
    cagr = v ** (1 / years) - 1
    rs = [r for _, r in recs]
    mu = sum(rs) / len(rs)
    vol = math.sqrt(sum((x - mu) ** 2 for x in rs) / (len(rs) - 1)) * math.sqrt(12)
    win = sum(1 for x in rs if x > 0) / len(rs)
    mdd = qc.max_drawdown(rs)
    print(f"\n=== {label} ===")
    print(f"区间: {recs[0][0]} ~ {recs[-1][0]}  ({years:.1f} 年, {len(recs)} 个月)")
    print(f"累计 {v:.3f}x | CAGR {cagr*100:.2f}% | 年化波动 {vol*100:.2f}% | 夏普 {(cagr-0.015)/vol:.2f}")
    print(f"月度胜率 {win*100:.1f}% | 最差月 {min(rs)*100:.2f}% | 最大回撤 {mdd*100:.2f}%")
    yr = defaultdict(lambda: 1.0)
    for t, r in recs:
        yr[t[:4]] *= (1 + r)
    print("年度: " + "  ".join(f"{y}:{(x-1)*100:+.1f}%" for y, x in sorted(yr.items())))

if __name__ == "__main__":
    stats(run(STOCKS), "引擎A 全池 12月动量+绝对动量门+波动率目标(12%)")
    stats(run(["HS300", "CYB"]), "引擎A 经典3资产(300/创业板/国债) 同规则")

    def bh(label, k):
        ms = [d for d in me if px(k, d) and cal.index(d) > MOM_LEN]
        recs = [(ms[i], px(k, ms[i]) / px(k, ms[i - 1]) - 1) for i in range(1, len(ms))]
        stats(recs, label)
    bh("对照-买入持有 沪深300", "HS300")
    bh("对照-买入持有 红利低波", "HLDB")
