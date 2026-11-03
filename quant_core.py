# -*- coding: utf-8 -*-
"""
quant_core.py —— 回测引擎的纯函数核心（块29）

全部函数：无网络、无文件 IO、无全局状态 → 可被单元测试完整覆盖。
这就是块 29 的核心论点：把"会不会算"和"能不能联网取数"拆开，两边才都能测。
"""
import math

TRADING_DAYS_PER_YEAR = 243


def month_ends(calendar: list) -> list:
    """每个自然月最后一个交易日，按时间升序返回。calendar 必须是升序日期列表。"""
    last = {}
    for d in calendar:
        last[d[:7]] = d
    return [last[m] for m in sorted(last)]


def momentum(px, calendar: list, idx: int, lookback: int) -> float | None:
    """过去 lookback 个交易日的动量；任一端数据缺失返回 None（调用方过滤）。"""
    if idx < lookback:
        return None
    t1, t0 = calendar[idx], calendar[idx - lookback]
    p1, p0 = px(t1), px(t0)
    if p0 is None or p1 is None or p0 == 0:
        return None
    return p1 / p0 - 1.0


def select_eligibles(mom: dict, cash_mom: float, top_n: int, gate: bool = True) -> list:
    """绝对动量门 + 相对动量排序，返回前 top_n 名称。

    gate=True：只保留动量 > cash_mom 的资产；都不达标时返回空表（全仓避险腿）。
    """
    elig = [k for k, v in mom.items() if v is not None and (v > cash_mom or not gate)]
    elig.sort(key=lambda k: -mom[k])
    return elig[:top_n]


def realized_vol(closes: list, periods: int = TRADING_DAYS_PER_YEAR) -> float | None:
    """日收盘序列 → 年化波动率。有效日收益 <2 个时返回 None。"""
    rs = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a and b:
            rs.append(b / a - 1.0)
    if len(rs) < 2:
        return None
    mu = sum(rs) / len(rs)
    var = sum((r - mu) ** 2 for r in rs) / (len(rs) - 1)
    return math.sqrt(var) * math.sqrt(periods)


def vol_scale(vols: list, target_vol: float) -> float:
    """加权平均已实现波动 → 缩放系数 min(1, 目标波动 / 实际波动)。"""
    if not vols:
        return 1.0
    pv = sum(vols) / len(vols)
    if pv <= 0:
        return 1.0
    return min(1.0, target_vol / pv)


def net_month_return(gross: float, turn: float, cost: float) -> float:
    """月度净收益 = 毛收益 − 换手率 × 2 × 单边成本（买卖各一次）。"""
    return gross - turn * 2.0 * cost


def max_drawdown(returns: list) -> float:
    """月（或日）收益序列 → 最大回撤（正数表示，如 0.1853 = -18.53%）。"""
    v = peak = 1.0
    mdd = 0.0
    for r in returns:
        v *= (1.0 + r)
        peak = max(peak, v)
        mdd = max(mdd, 1.0 - v / peak)
    return mdd
