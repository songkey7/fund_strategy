"""
Fund 012805 Complete Analysis + Position-Based T-Strategy
All NAV data from 2024-01-01 to 2026-08-07 via API pagination
"""
import requests, json, math, time, os
from datetime import datetime, timedelta

# ============================================================
# Config
# ============================================================
FUND_CODE = "012805"
TOTAL_SHARES = 83236.35
COST_BASIS = 71704.83
COST_PER_SHARE = COST_BASIS / TOTAL_SHARES

# T-action level constants
MAX_ENGAGE = "HEAVY_T_HUNT"
ENHANCE_ENGAGE = "ENHANCED_T"
NORMAL_ENGAGE = "NORMAL_T"
PASSIVE_MODE = "PASSIVE_HOLD"


def calc_position_pnl(nav_current):
    """Calculate current P&L based on latest NAV"""
    market_value = nav_current * TOTAL_SHARES
    profit = market_value - COST_BASIS
    profit_rate = (profit / COST_BASIS) * 100
    return profit_rate, profit


def get_t_action(nav_current):
    """Determine T-action based on position P&L rate
    Position loss severity has tiers governing how aggressively to conduct T-operations
    """
    pnl_rate, pnl_value = calc_position_pnl(nav_current)
    if pnl_rate <= -15:
        return {"action_level": MAX_ENGAGE, "t_lot_multiplier": 2.5, "depth": 3, "position": pnl_rate}
    elif pnl_rate <= -10:
        return {"action_level": ENHANCE_ENGAGE, "t_lot_multiplier": 1.8, "depth": 2, "position": pnl_rate}
    elif pnl_rate <= -5:
        return {"action_level": NORMAL_ENGAGE, "t_lot_multiplier": 1.0, "depth": 1, "position": pnl_rate}
    else:
        return {"action_level": PASSIVE_MODE, "t_lot_multiplier": 0.3, "depth": 0, "position": pnl_rate}


# ============================================================
# Data fetching — paginate through ALL pages
# ============================================================
def fetch_all_nav(fund_code, start_date_target, end_date_target):
    """Fetch ALL NAV records from API by paginating through all pages."""
    all_records = []
    headers = {
        "Referer": "https://fundf10.eastmoney.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    page = 1

    while True:
        params = {
            "fundCode": fund_code,
            "pageIndex": page,
            "pageSize": 20,
            "startDate": start_date_target,
            "endDate": end_date_target,
        }
        try:
            resp = requests.get("https://api.fund.eastmoney.com/f10/lsjz",
                                 params=params, headers=headers, timeout=30)
            data = json.loads(resp.text)
        except Exception as e:
            print(f"   Error on page {page}: {e}")
            break

        ds = data.get("Data")
        if not ds:
            break

        lst = ds.get("LSJZList", [])
        if not lst:
            break

        all_records.extend(lst)
        page += 1

    nav_data = []
    for r in all_records:
        date_str = r.get("FSRQ", "")
        nav_str = r.get("DWJZ", "")
        if date_str and nav_str:
            try:
                nav_data.append((date_str, float(nav_str)))
            except (ValueError, KeyError):
                pass

    nav_data = [(d, v) for d, v in nav_data if d >= start_date_target]
    nav_data.sort(key=lambda x: x[0])
    return nav_data


def fetch_index(secid, start_date, end_date, max_retries=3):
    """Fetch index kline data with retries and connection pooling"""
    import urllib3
    session = requests.Session()
    retry = urllib3.util.Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)

    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params_base = {
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "secid": secid,
        "beg": start_date.replace("-", ""),
        "end": end_date.replace("-", ""),
        "lmt": "5000",
    }
    headers = {"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"}

    for attempt in range(max_retries):
        try:
            resp = session.get(url, params=params_base, headers=headers, timeout=30)
            data = json.loads(resp.text)
            klines = data.get("data", {}).get("klines", [])
            result = []
            for k in klines:
                parts = k.split(",")
                if len(parts) >= 3:
                    result.append((parts[0], float(parts[2])))
            return result
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"   Retry {attempt+1}/{max_retries}: {e}")
                time.sleep(5)
            else:
                print(f"   Failed after {max_retries} retries: {e}")
                return []


# ============================================================
# ANALYTICS helpers
# ============================================================
def sma(vals, w):
    if len(vals) < w:
        return None
    return sum(vals[-w:]) / w


def calc_max_drawdown(vals, dates):
    peak = vals[0]
    mdd = 0
    cur_peak = 0
    for i, v in enumerate(vals):
        if v > peak:
            peak = v
            cur_peak = i
        dd = (peak - v) / peak
        if dd > mdd:
            mdd = dd
            peak_idx = cur_peak
            trough_idx = i
    return mdd, peak_idx, trough_idx


def annual_vol(vals, window=None):
    v = vals if window is None else vals[-window:]
    if len(v) < 2:
        return None
    lr = [math.log(v[i]/v[i-1]) for i in range(1, len(v))]
    mean = sum(lr) / len(lr)
    s2 = sum((r-mean)**2 for r in lr) / (len(lr)-1)
    return math.sqrt(s2) * math.sqrt(252) * 100


# ============================================================
# MAIN
# ============================================================
print("=" * 80)
print("FUND 012805 COMPREHENSIVE ANALYSIS + POSITION-BASED STRATEGY")
print("=" * 80)
print(f"\nShares: {TOTAL_SHARES:,.0f} | Cost Basis: ¥{COST_BASIS:,.0f} | Avg Cost: ¥{COST_PER_SHARE:.4f}")

print("\nFetching data...")

# 1. Fund NAV
print("   [1/3] Fund 012805 NAV history...")
nav = fetch_all_nav(FUND_CODE, "2024-01-01", "2026-08-07")
if not nav:
    print("ERROR: No fund data")
    exit(1)
dates = [x[0] for x in nav]
values = [x[1] for x in nav]

# 2. HSTECH Index — try kline API; fallback to fund platform
print("   [2/3] HSTECH Index klines...")
hstech_idx = fetch_index("124.HSTECH", "2024-01-01", "2026-08-07")
if not hstech_idx:
    print("   [2/3] WARNING: Using ETF 513180 as HSTECH proxy (kline fetch failed)")
else:
    print(f"   HSTECH: {len(hstech_idx)} kline points")

# 3. ETF 513180
print("   [3/3] ETF 513180 NAV history...")
time.sleep(2)  # Brief pause between requests
nav_etf = fetch_all_nav("513180", "2024-01-01", "2026-08-07")

# ============================================================
# Current state
# ============================================================
cur = values[-1]
cur_date = dates[-1]
mv = cur * TOTAL_SHARES
pnl = mv - COST_BASIS
pnl_pct = (pnl / COST_BASIS) * 100

print(f"\n{'─'*80}")
print("1. CURRENT POSITION")
print(f"{'─'*80}")
print(f"  Latest NAV:          ¥{cur:.4f} ({cur_date})")
print(f"  Market Value:        ¥{mv:,.2f}")
print(f"  Unrealized P&L:      ¥{pnl:,.2f} ({pnl_pct:+.2f}%)")
print(f"  vs Avg Cost:         {(cur/COST_PER_SHARE-1)*100:+.2f}%")

# Position-based action recommendation
action = get_t_action(cur)
pnl_rate, pnl_value = calc_position_pnl(cur)

print(f"\n  📊 Position P&L: {pnl_rate:+.1f}% ({pnl_value:+,.0f})")
print(f"  🎯 Action Level: {action['action_level']} (lot mult: {action['t_lot_multiplier']}x)")

if action['action_level'] == MAX_ENGAGE:
    print(f"  🚨 HEAVY ENGAGE: 持仓亏损>15%, 全力做T")
elif action['action_level'] == ENHANCE_ENGAGE:
    print(f"  ⚠️  ENHANCED ENGAGE: 亏损10-15%, T-drive + 定投")
elif action['action_level'] == NORMAL_ENGAGE:
    print(f"  ⚡ NORMAL ENGAGE: 亏损5-10%")
else:
    print(f"  🔄 PASSIVE MODE: 亏损<5%, 持有为主")

print(f"\n  Data range: {dates[0]} → {dates[-1]} ({len(nav)} records)")

# 52-week
n52 = min(365, len(values))
r52 = values[-n52:]
hi52, lo52 = max(r52), min(r52)
print(f"\n  52w Hi: ¥{hi52:.4f} | 52w Lo: ¥{lo52:.4f}")
pos52 = (cur-lo52)/(hi52-lo52)*100 if hi52 != lo52 else 50
print(f"  52w Range: ¥{hi52-lo52:.4f} | Position: {pos52:.1f}% from low")

# ATH/ATL
ath = max(values)
atl = min(values)
print(f"\n  ATH: ¥{ath:.4f} | ATL: ¥{atl:.4f}")
print(f"  DD from ATH: {(cur/ath-1)*100:+.2f}%")

# ============================================================
# 2. Performance
# ============================================================
print(f"\n{'─'*80}")
print("2. PERFORMANCE & MAX DRAWDOWN")
print(f"{'─'*80}")

for p in [7, 30, 90, 180, 365]:
    target = (datetime.now() - timedelta(days=p)).strftime("%Y-%m-%d")
    best = None
    for d, v in nav:
        if d <= target:
            best = (d, v)
        else:
            break
    if best:
        print(f"  {p:>4}d return ({best[0]}): {(cur/best[1]-1)*100:+.2f}%")

mdd, mdd_pk, mdd_tr = calc_max_drawdown(values, dates)
print(f"\n  Max Drawdown: {mdd*100:.2f}% ({dates[mdd_pk]}→{dates[mdd_tr]})")

# ============================================================
# 3. Moving Averages
# ============================================================
print(f"\n{'─'*80}")
print("3. MOVING AVERAGES")
print(f"{'─'*80}")

mas = {}
for w in [5, 10, 20, 50, 60, 120, 200, 250]:
    ma = sma(values, w)
    if ma:
        diff = (cur/ma - 1)*100
        tag = "Above" if cur > ma else "BELOW"
        print(f"  MA{w:>3}: ¥{ma:.4f} | {tag} by {abs(diff):.2f}%")
        mas[w] = ma

# ============================================================
# 4. Volatility & Risk
# ============================================================
print(f"\n{'─'*80}")
print("4. VOLATILITY & RISK")
print(f"{'─'*80}")

for p in [30, 90, 180, 365]:
    vol = annual_vol(values, p)
    if vol:
        print(f"  {p:>4}d Ann. Vol: {vol:.2f}%")

dly = [abs(values[i]-values[i-1])/values[i-1]*100 for i in range(1, len(values))]
print(f"\n  Avg Daily Moves:")
for p in [30, 90, 180]:
    if len(dly) >= p:
        a = sum(dly[-p:])/p
        print(f"    {p:>3}d: {a:.3f}%")

# ============================================================
# 5. Bollinger Bands & RSI
# ============================================================
print(f"\n{'─'*80}")
print("5. BOLLINGER BANDS & RSI")
print(f"{'─'*80}")

ma20 = mas.get(20)
if ma20 and len(values) >= 20:
    r20 = values[-20:]
    std20 = math.sqrt(sum((v-ma20)**2 for v in r20)/20)
    upper = ma20+2*std20
    lower = ma20-2*std20
    bp = (cur-lower)/(upper-lower)*100
    print(f"  BB(20,2): ¥{upper:.4f} / ¥{ma20:.4f} / ¥{lower:.4f}")
    print(f"  Band Width: {(upper-lower)/ma20*100:.2f}% | Position: {bp:.1f}%")

# RSI
if len(values) > 14:
    g = []
    l = []
    for i in range(len(values)-14, len(values)):
        ch = values[i]-values[i-1]
        if ch >= 0:
            g.append(ch)
            l.append(0)
        else:
            g.append(0)
            l.append(abs(ch))
    ag = sum(g)/14
    al = sum(l)/14
    rsi = 100 if al == 0 else 100-100/(1+ag/al)
    tag = "OVERSOLD (<30)" if rsi < 30 else ("OVERBOUGHT (>70)" if rsi > 70 else "Neutral")
    print(f"  RSI(14): {rsi:.1f} — {tag}")

# ============================================================
# 6. Trend directions
# ============================================================
print(f"\n{'─'*80}")
print("6. RECENT TREND (LINEAR REGRESSION)")
print(f"{'─'*80}")

for w in [10, 30, 90]:
    n = min(w, len(values))
    y = values[-n:]
    x = list(range(n))
    sxy = sum(x[i]*y[i] for i in range(n))
    slope = (n*sxy - sum(x)*sum(y))/(n*sum(xi*xi for xi in x) - sum(x)*sum(x))
    direction = "UP" if slope > 0 else "DN"
    trend_pct = (slope*(n-1))/y[0]*100
    print(f"  {w:>3}d: {direction} | slope: {slope:+.6f}/day | Δ: {trend_pct:+.2f}%")

# ============================================================
# 7. Key Support / Resistance
# ============================================================
print(f"\n{'─'*80}")
print("7. KEY SUPPORT / RESISTANCE")
print(f"{'─'*80}")

print(f"  Resistance: ¥{hi52:.4f} (52w high)")
print(f"  Resistance: ¥{upper:.4f} (BB Upper)")
print(f"  Midline:   ¥{ma20:.4f} (MA20)")
print(f"  Support:   ¥{lower:.4f} (BB Lower)")
print(f"  Support:   ¥{lo52:.4f} (52w low)")

# ============================================================
# 8. HSTECH Benchmark
# ============================================================
print(f"\n{'─'*80}")
print("8. HSTECH BENCHMARK (using ETF 513180 as proxy)")
print(f"{'─'*80}")

bench_idx = hstech_idx if hstech_idx else nav_etf
kd = dict(bench_idx) if bench_idx else {}
jd = dict(nav)

if kd and jd:
    common = sorted(set(jd.keys()) & set(kd.keys()))
    if len(common) >= 2:
        j0 = jd[common[0]]
        k0 = kd[common[0]]
        jf = jd[common[-1]]
        kf = kd[common[-1]]
        print(f"  Normalized from {common[0]}:")
        print(f"    Fund 012805: {(jf/j0-1)*100:+.2f}%")
        print(f"    ETF 513180:  {(kf/k0-1)*100:+.2f}%")

        idx_v = [kd[d] for d in common]
        i_cur = idx_v[-1]
        print(f"\n  ETF 513180 NAV: {i_cur:.4f}")
        for lbl, p in [("MA20", 20), ("MA50", 50), ("MA200", 200)]:
            if len(idx_v) >= p:
                ma_i = sma(idx_v, p)
                d = (i_cur/ma_i - 1)*100
                print(f"    {lbl}: {ma_i:.4f} ({'Above' if i_cur > ma_i else 'BELOW'} by {abs(d):.2f}%)")

        print(f"\n  ETF 513180 Returns:")
        for p in [30, 90, 180]:
            if len(idx_v) >= p:
                r = (idx_v[-1]/idx_v[-p] - 1)*100
                print(f"    {p:>3}d: {r:+.2f}%")

# ============================================================
# 9. Position-Based Recovery Plan
# ============================================================
print(f"\n{'─'*80}")
print("9. POSITION-BASED RECOVERY PLAN (POSITION P&L DRIVEN)")
print(f"{'─'*80}")

pnl_rate, pnl_value = calc_position_pnl(cur)
action = get_t_action(cur)

print(f"\n  Current Position P&L: {pnl_rate:+.1f}% (¥{pnl_value:+,.0f})")
print(f"  Current NAV:  ¥{cur:.4f}")
print(f"  Avg Cost:    ¥{COST_PER_SHARE:.4f}")
print(f"  BE NAV:       ¥{COST_PER_SHARE:.4f} ({(COST_PER_SHARE/cur-1)*100:+.1f}% away)")

print(f"\n  Action Level: {action['action_level']}")
print(f"  Action Description:", end=" ")
if action['action_level'] == MAX_ENGAGE:
    print("🚨 亏损>15% — 强力T + 加倍定投")
elif action['action_level'] == ENHANCE_ENGAGE:
    print("⚠️  亏损10-15% — 增强T + 定投")
elif action['action_level'] == NORMAL_ENGAGE:
    print("⚡ 亏损5-10% — 常规T + 小额定投")
else:
    print("🔄 亏损<5% — 被动持有")

print(f"\n  Position Sensitivity Bracket Levels:")
print(f"    BE to -5%:  PASSIVE — hold core, T only on extreme signals")
print(f"    -5% to -10%: NORMAL — T on 20% shares")
print(f"    -10% to -15%: ENHANCED — T on 30% shares, monthly DCA enhance")
print(f"    -15%+: MAX ENGAGE — T on 40% shares, double monthly DCA")

# Recommended T-Lot Sizes based on position
base_lot = TOTAL_SHARES * 0.10  # 10% base lot
recommendations = [
    ("-15% or worse", base_lot * 2.5, "强力T + 双倍定投"),
    ("-10% to -15%", base_lot * 1.8, "增强T + 定投"),
    ("-5% to -10%", base_lot * 1.0, "常规T + 小额定投"),
    ("BE to -5%", base_lot * 0.3, "被动持有,仅极端T"),
]
print(f"\n  T-Lot Recommendations:")
for position_range, t_shares, strategy in recommendations:
    approx_val = t_shares * cur
    print(f"    {position_range}: {t_shares:,.0f} shares ({approix_val:,.0f}) — {strategy}")

print(f"\n  DCA Integration:")
print(f"    Every month: invest additional based on position")
print(f"    P&L {pnl_rate:+.1f}% — {'double' if pnl_rate <= -15 else 'enhanced' if pnl_rate <= -10 else 'normal' if pnl_rate <= -5 else 'minimum'} investment")

# Clean up tmp files
for f in ['debug_api.py', 'debug_api2.py', 'debug_api3.py', 'debug_api4.py', 'debug_api5.py', 'debug_api6.py', 'debug_api7.py', 'debug_api8.py', 'debug_api9.py', 'debug_api10.py']:
    try:
        os.remove(os.path.join('/Users/songqi/Projects/ai/fund/fund_strategy', f))
    except:
        pass
