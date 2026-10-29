# -*- coding: utf-8 -*-
"""
PBO（Probability of Backtest Overfitting, Bailey et al. 2017 CSCV 法）：
把 36 组参数的月度收益矩阵按时间切成 S=6 块，穷举 C(6,3)=20 种"训练/测试"组合，
对每组计算：IS 表现排名与 OOS 表现排名的一致性（logit λ）。
PBO = P(λ < 0) = "样本内最优参数在样本外跑输中位数"的概率。
低于 ~30% 可接受；>50% 说明参数选择基本是过拟合产物。
"""
import urllib.request, urllib.parse, json, math, time, random, datetime as dt
from itertools import combinations

API_HOST = "https://web.ifzq.gtimg.cn"
def fetch(secid, beg="2012-01-01"):
    prefix = {"1.": "sh", "0.": "sz"}.get(secid[:2]); assert prefix in ("sh","sz")
    symbol = prefix + secid.split(".")[1]
    rows = {}; end = dt.date.today().isoformat()
    opener = urllib.request.build_opener(_NoRedirect())
    for _ in range(15):
        url = f"{API_HOST}/appstock/app/fqkline/get?param={symbol},day,,{end},640,hfq"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://gu.qq.com/"})
        d = json.load(opener.open(req, timeout=20))
        node = d["data"][symbol]; key = next(k for k in node if "day" in k)
        if not node[key]: break
        n0 = len(rows)
        for r in node[key]: rows[r[0]] = float(r[2])
        e = min(rows)
        if e <= beg or len(rows) == n0: break
        end = (dt.date.fromisoformat(e)-dt.timedelta(days=1)).isoformat()
        time.sleep(0.35)
    return rows

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None

ASSETS = {"HS300":"1.510300","ZZ1000":"1.512100","CYB":"0.159915","HLDB":"1.512890",
          "SP500":"1.513500","HSTK":"1.513180","BOND":"1.511010","CASH":"1.511990"}
STOCKS = list(ASSETS)[:6] if False else ["HS300","ZZ1000","CYB","HLDB","SP500","HSTK"]
raw = {k: fetch(v) for k, v in ASSETS.items()}
cal = sorted(raw["HS300"].keys())
first = {k: min(d) for k, d in raw.items()}
def px(k, d):
    if d < first[k]: return None
    return raw[k].get(d)
month_last = {}
for d in cal: month_last[d[:7]] = d
me = [month_last[m] for m in sorted(month_last)]

def monthly_returns(pool, mom_len, top_n, tvol, cost=0.0027):
    recs = []; prev_w = {"CASH":1.0}; used = []
    for t in me:
        idx = cal.index(t)
        if idx < mom_len + 20: continue
        mom = {}
        for k in pool:
            p0, p1 = px(k, cal[idx-mom_len]), px(k, t)
            if p0 and p1: mom[k] = p1/p0-1
        c0, c1 = px("CASH", cal[idx-mom_len]), px("CASH", t)
        cm = (c1/c0-1) if (c0 and c1) else 0.015
        elig = sorted([k for k in mom if mom[k] > cm], key=lambda k:-mom[k])[:top_n]
        new = {k: 1.0/top_n for k in elig}
        bw = 1.0 - sum(new.values())
        if bw > 1e-9: new["BOND"] = new.get("BOND",0)+bw
        vols = []
        for k in [x for x in new if x in STOCKS]:
            ps = [px(k, cal[idx-j]) for j in range(21)][::-1]
            rs = [ps[j]/ps[j-1]-1 for j in range(1,len(ps)) if ps[j] and ps[j-1]]
            if len(rs) > 5:
                mu = sum(rs)/len(rs)
                vols.append(math.sqrt(sum((r-mu)**2 for r in rs)/(len(rs)-1))*math.sqrt(243))
        pv = sum(vols)/len(vols) if vols else 0
        sc = min(1.0, tvol/pv) if pv > 0 else 1.0
        for k in list(new):
            if k in STOCKS: new[k] *= sc
        cw = 1.0 - sum(new.values())
        if cw > 1e-9: new["CASH"] = new.get("CASH",0)+cw
        if used:
            t0 = used[-1]; pr = 0.0
            for k, w in prev_w.items():
                a, b = px(k, t0), px(k, t)
                if a and b: pr += w*(b/a-1)
            turn = sum(abs(new.get(k,0)-prev_w.get(k,0)) for k in set(new)|set(prev_w))/2
            recs.append((t, pr - turn*2*cost))
        prev_w = new; used.append(t)
    return recs

# 36 组参数的月度收益矩阵（与 validation_engine_a.py 的网格一致）
params = [(ml, tn, tv) for ml in (120,180,240,300) for tn in (1,2,3) for tv in (0.10,0.12,0.15)]
print("计算 36 组参数的月度收益矩阵 ...")
series, dates = [], None
for i, (ml, tn, tv) in enumerate(params):
    recs = monthly_returns(STOCKS, ml, tn, tv)
    if dates is None: dates = [t for t, _ in recs]
    series.append({t: r for t, r in recs})
    print(f"  [{i+1}/36] mom={ml} top={tn} tv={tv:.0%}")
N = len(params); T = len(dates)
M = [[series[i].get(t, 0.0) for t in dates] for i in range(N)]

# CSCV：S=6 块，C(6,3)=20 组
S = 6
blocks = [list(range(j*T//S, (j+1)*T//S)) for j in range(S)]
logits = []
for train_combo in combinations(range(S), S//2):
    test = [j for j in range(S) if j not in train_combo]
    tr_idx = [x for j in train_combo for x in blocks[j]]
    te_idx = [x for j in test for x in blocks[j]]
    def sharpe(idxs):
        out = []
        for i in range(N):
            rs = [M[i][x] for x in idxs]
            mu = sum(rs)/len(rs)
            sd = (sum((r-mu)**2 for r in rs)/(len(rs)-1)) ** 0.5
            out.append(mu/sd if sd > 0 else 0)
        return out
    is_r = sharpe(tr_idx); oos_r = sharpe(te_idx)
    best_is = max(range(N), key=lambda i: is_r[i])
    rank_oos = sorted(range(N), key=lambda i: oos_r[i]).index(best_is)
    w = (rank_oos + 1) / (N + 1)          # OOS 相对排名 ∈ (0,1)
    logits.append(math.log(w/(1-w)))
pbo = sum(1 for l in logits if l < 0) / len(logits)
print(f"\nPBO = {pbo:.0%}（{sum(1 for l in logits if l<0)}/{len(logits)} 组）")
print(f"λ 分布：中位 {sorted(logits)[len(logits)//2]:+.2f}，最小 {min(logits):+.2f}，最大 {max(logits):+.2f}")
print("判读：<30% 参数选择可信；30-50% 警戒；>50% 参数基本是过拟合产物（Bailey et al. 2017）")
