# -*- coding: utf-8 -*-
"""
引擎A 验证协议执行（对应《交易系统.md》第 7 章）：
V1 参数平台期：动量回看期 × 持有数 × 波动率目标 网格
V2 成本压力：双边成本 ×2
V3 剔除红利顺风：去掉 HLDB 的 5 资产池
V4 分段样本外：2013-2019 vs 2020-2026
V5 蒙特卡洛：月度收益洗牌 1000 次，看实际最大回撤的分位
"""
import urllib.request, urllib.parse, json, math, time, random, datetime as dt
from collections import defaultdict

API_HOST = "https://web.ifzq.gtimg.cn"

def fetch(secid, beg="2012-01-01"):
    prefix = {"1.": "sh", "0.": "sz"}.get(secid[:2]); assert prefix in ("sh", "sz")
    symbol = prefix + secid.split(".")[1]
    rows = {}; end = dt.date.today().isoformat()
    opener = urllib.request.build_opener(_NoRedirect())
    for _ in range(15):
        url = f"{API_HOST}/appstock/app/fqkline/get?param={symbol},day,,{end},640,hfq"
        assert urllib.parse.urlparse(url).hostname == "web.ifzq.gtimg.cn"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
        d = json.load(opener.open(req, timeout=20))
        node = d["data"][symbol]; key = next(k for k in node if "day" in k)
        if not node[key]: break
        n0 = len(rows)
        for r in node[key]: rows[r[0]] = float(r[2])
        earliest = min(rows)
        if earliest <= beg or len(rows) == n0: break
        end = (dt.date.fromisoformat(earliest) - dt.timedelta(days=1)).isoformat()
        time.sleep(0.35)
    return rows

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None

ASSETS = {"HS300":"1.510300","ZZ1000":"1.512100","CYB":"0.159915","HLDB":"1.512890",
          "SP500":"1.513500","HSTK":"1.513180","BOND":"1.511010","CASH":"1.511990"}
STOCKS = ["HS300","ZZ1000","CYB","HLDB","SP500","HSTK"]
raw = {k: fetch(v) for k, v in ASSETS.items()}
cal = sorted(raw["HS300"].keys())
first = {k: min(d) for k, d in raw.items()}
def px(k, date):
    if date < first[k]: return None
    return raw[k].get(date)
month_last = {}
for d in cal: month_last[d[:7]] = d
me = [month_last[m] for m in sorted(month_last)]

def run(pool, mom_len=240, top_n=2, tvol=0.12, cost=0.0027, t0=None, t1=None, gate=True):
    prev_w, used, recs = {"CASH":1.0}, [], []
    for t in me:
        idx = cal.index(t)
        if idx < mom_len + 20: continue
        mom = {}
        for k in pool:
            p0, p1 = px(k, cal[idx-mom_len]), px(k, t)
            if p0 and p1: mom[k] = p1/p0 - 1
        c0, c1 = px("CASH", cal[idx-mom_len]), px("CASH", t)
        cm = (c1/c0-1) if (c0 and c1) else 0.015
        elig = sorted([k for k in mom if (mom[k] > cm or not gate)], key=lambda k:-mom[k])[:top_n]
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
        if used and ((not t0 or t >= t0) and (not t1 or t <= t1)):
            t_prev = used[-1]; pr = 0.0
            for k, w in prev_w.items():
                a, b = px(k, t_prev), px(k, t)
                if a and b: pr += w*(b/a-1)
            turn = sum(abs(new.get(k,0)-prev_w.get(k,0)) for k in set(new)|set(prev_w))/2
            recs.append((t, pr - turn*2*cost))
        if not t0 or t >= t0:
            prev_w = new; used.append(t)
    return recs

def metrics(recs):
    v, peak, mdd = 1.0, 1.0, 0.0
    for _, r in recs:
        v *= (1+r); peak = max(peak, v); mdd = max(mdd, 1-v/peak)
    y = len(recs)/12.0
    cagr = v**(1/y)-1
    rs = [r for _, r in recs]; mu = sum(rs)/len(rs)
    vol = math.sqrt(sum((x-mu)**2 for x in rs)/(len(rs)-1))*math.sqrt(12)
    win = sum(1 for x in rs if x > 0)/len(rs)
    return cagr, vol, mdd, win, v

def show(tag, m):
    print(f"{tag:<46} CAGR {m[0]*100:6.2f}%  vol {m[1]*100:5.2f}%  DD {m[2]*100:6.2f}%  胜率 {m[3]*100:5.1f}%")

print("V1 参数平台期（基准=240/2/12%）")
base_pool = STOCKS
grid = []
for ml in (120, 180, 240, 300):
    for tn in (1, 2, 3):
        for tv in (0.10, 0.12, 0.15):
            m = metrics(run(base_pool, ml, tn, tv))
            grid.append((ml, tn, tv, m))
            show(f"  mom={ml:>3} top={tn} tv={tv:.0%}", m)
cagrs = [g[3][0] for g in grid]; dds = [g[3][2] for g in grid]
print(f"  → CAGR 范围 {min(cagrs)*100:.1f}%~{max(cagrs)*100:.1f}% | DD 范围 {min(dds)*100:.1f}%~{max(dds)*100:.1f}%（平台期判定：范围窄=稳，悬崖=过拟合）")

print("\nV2 成本压力（双边 0.54%）")
show("  基准成本 0.27%", metrics(run(base_pool)))
show("  压力成本 0.54%", metrics(run(base_pool, cost=0.0054)))

print("\nV3 剔除红利顺风（去掉 HLDB）")
show("  全池(含红利低波)", metrics(run(base_pool)))
show("  5资产(无红利低波)", metrics(run([k for k in STOCKS if k != "HLDB"])))

print("\nV4 分段样本外")
show("  2013-2019", metrics(run(base_pool, t0=None, t1="2019-12-31")))
show("  2020-2026", metrics(run(base_pool, t0="2020-01-01")))

print("\nV5 蒙特卡洛：月收益洗牌 1000 次")
m = metrics(run(base_pool))
rs = [r for _, r in run(base_pool)]
random.seed(42)
dds = []
for _ in range(1000):
    s = rs[:]; random.shuffle(s)
    v, peak, dd = 1.0, 1.0, 0.0
    for r in s:
        v *= (1+r); peak = max(peak, v); dd = max(dd, 1-v/peak)
    dds.append(dd)
dds.sort()
rank = sum(1 for x in dds if x <= m[2])/len(dds)
print(f"  实际 DD {m[2]*100:.2f}% | 洗牌分布 P50 {dds[500]*100:.2f}%  P95 {dds[949]*100:.2f}% | 实际值分位 {rank*100:.1f}%")
print("  （分位 50% 左右=回撤符合随机重排；>95%=这串顺序特别倒霉；<5%=特别走运，反而要警惕）")
