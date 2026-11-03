# -*- coding: utf-8 -*-
"""
factor_ic.py —— 动量因子实证（块30）

问题：12 月动量这个因子，在我们的 6 只 ETF 横截面上到底有没有预测力？
方法（量化研究标准三件套）：
1. Rank IC：每月末，因子值排名 与 下月收益排名 的 Spearman 相关
2. ICIR = IC均值 / IC标准差（因子的"夏普"）
3. Top-Bottom 分层：因子最强 2 只与最弱 2 只的下月收益差（不含成本）
诚实声明：横截面只有 6 个资产 → IC 噪音大；未扣成本；QDII 有溢价与汇率口径。
"""
import math
from collections import defaultdict

import quant_core as qc
import quant_data as qd

ASSETS = {"HS300": "sh510300", "ZZ1000": "sh512100", "CYB": "sz159915",
          "HLDB": "sh512890", "SP500": "sh513500", "HSTK": "sh513180"}
MOM_LEN = 240

raw = {k: qd.get_close(v) for k, v in ASSETS.items()}
cal = sorted(raw["HS300"].keys())
first = {k: min(d) for k, d in raw.items()}

def px(k, date):
    if date < first[k]:
        return None
    return raw[k].get(date)

me = qc.month_ends(cal)

def _rank(vals):
    """平均秩（处理并列），vals: list[float] -> list[float]，1 = 最小。"""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k2 in range(i, j + 1):
            ranks[order[k2]] = avg
        i = j + 1
    return ranks

def spearman(xs, ys):
    n = len(xs)
    rx, ry = _rank(xs), _rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)

ics, spreads, months = [], [], []
for i in range(len(me) - 1):
    t, t2 = me[i], me[i + 1]
    idx = cal.index(t)
    if idx < MOM_LEN:
        continue
    fac, out = {}, {}
    for k in ASSETS:
        m = qc.momentum(lambda d, _k=k: px(_k, d), cal, idx, MOM_LEN)
        a, b = px(k, t), px(k, t2)
        if m is not None and a and b:
            fac[k], out[k] = m, b / a - 1
    if len(fac) < 4:          # 横截面太小没有统计意义
        continue
    ks = list(fac)
    ic = spearman([fac[k] for k in ks], [out[k] for k in ks])
    if ic is None:
        continue
    ics.append(ic)
    months.append(t)
    order = sorted(ks, key=lambda k: fac[k])
    top2 = [out[k] for k in order[-2:]]
    bot2 = [out[k] for k in order[:2]]
    spreads.append(sum(top2) / 2 - sum(bot2) / 2)

n = len(ics)
mu = sum(ics) / n
sd = math.sqrt(sum((x - mu) ** 2 for x in ics) / (n - 1))
icir = mu / sd
tstat = icir * math.sqrt(n)
win = sum(1 for x in ics if x > 0) / n
sp_mu = sum(spreads) / len(spreads)
sp_win = sum(1 for x in spreads if x > 0) / len(spreads)
sp_mdd = qc.max_drawdown(spreads)
sp_cum = 1.0
for x in spreads:
    sp_cum *= (1 + x)
yrs = len(spreads) / 12.0

print(f"样本：{months[0]} ~ {months[-1]}，{n} 个月（横截面 = 6 只 ETF）")
print(f"\n[Rank IC]  均值 {mu:+.3f} | 标准差 {sd:.3f} | ICIR {icir:+.2f} | t≈{tstat:+.1f} | IC>0 占比 {win*100:.0f}%")
print(f"[Top2-Bot2 分层价差（未扣成本）] 月均 {sp_mu*100:+.2f}% | 月度胜率 {sp_win*100:.0f}% | "
      f"累计 {sp_cum:.2f}x（{yrs:.1f} 年，年化 {(sp_cum**(1/yrs)-1)*100:+.2f}%）| 价差曲线回撤 {sp_mdd*100:.1f}%")
print("\n[分年度 IC 均值]")
yrs_ic = defaultdict(list)
for t, ic in zip(months, ics):
    yrs_ic[t[:4]].append(ic)
for y in sorted(yrs_ic):
    v = yrs_ic[y]
    m = sum(v) / len(v)
    print(f"  {y}: {m:+.3f}  ({'+' if m > 0 else ' '}{len([x for x in v if x > 0])}/{len(v)} 月为正)")
print("\n判读基准（学术经验值）：|IC|>0.03 且 ICIR>0.5 算有信息；t>3 才算扛住多重检验（Harvey-Liu-Zhu）。")
