#!/usr/bin/env python3
"""
012805 净值监控 - 到达关键价位时发送提醒
每30分钟检查一次净值，触发关键价位时发出通知

使用方式: python3 monitor_012805.py
"""

import requests, json, time, subprocess, os, ssl, re
import urllib.request
from datetime import datetime, timedelta

# ============================================================
# 整体持仓
# ============================================================
POSITION_COST = 71704.83
# 用户确认：净值 ¥0.7761 时市值 ¥65,454.42
CONFIRMED_MV = 65454.42
CONFIRMED_BASE = 0.7761
TOTAL_SHARES = CONFIRMED_MV / CONFIRMED_BASE

# ============================================================
# 当前 T 仓（已开）
# ============================================================
T_COST = 10000.00
T_ENTRY_NAV = 0.7442
T_SHARES = 13437

# T 仓止盈止损
T_TP1 = T_ENTRY_NAV * 1.05
T_TP2 = T_ENTRY_NAV * 1.08
T_SL = T_ENTRY_NAV * 0.92

# ============================================================
# 新开 T 仓点位
# ============================================================
NEW_T_ENTRIES = [
    (0.7606, 8000,  "首次开仓"),
    (0.7454, 12000, "加仓 1.5x"),
    (0.7221, 12000, "加仓 1.5x"),
    (0.7062, 16000, "重仓 2x"),
]

FUND_CODE = "012805"
CHECK_INTERVAL = 1800


def send_notification(title, message):
    try:
        script = f'display notification "{message}" with title "{title}" sound name "Hero"'
        subprocess.run(["osascript", "-e", script], check=True)
    except Exception as e:
        print(f"   [通知失败] {e}")


def fetch_current_nav():
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
        url = (f"https://api.fund.eastmoney.com/f10/lsjz"
               f"?callback=jQuery&fundCode={FUND_CODE}&pageIndex=1&pageSize=1"
               f"&startDate={start_date}&endDate={end_date}")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={'Referer': 'https://fundf10.eastmoney.com/'})
        resp = urllib.request.urlopen(req, context=ctx, timeout=15)
        content = resp.read().decode('utf-8')
        m = re.match(r'^\w+\((.*)\)$', content.strip(), re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            records = data['Data']['LSJZList']
            if records:
                latest = records[0]
                return float(latest['DWJZ']), latest['FSRQ']
    except Exception as e:
        print(f"   [获取净值失败] {e}")
    return None, None


def main():
    print("=" * 60)
    print("  012805 净值监控（T仓版）")
    print("=" * 60)
    print(f"  启动: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  当前 T 仓: ¥{T_COST:,.0f} @ ¥{T_ENTRY_NAV:.4f}（{T_SHARES:,} 份）")
    print()
    print("  T 仓止盈/止损:")
    print(f"    +5% → ¥{T_TP1:.4f} → 卖 {int(T_SHARES*0.6):,} 份（60%）")
    print(f"    +8% → ¥{T_TP2:.4f} → 卖 {int(T_SHARES*0.4):,} 份（40%）")
    print(f"    -8% → ¥{T_SL:.4f} → 全出（{T_SHARES:,} 份）")
    print()
    print("  新开 T 仓点位:")
    for nav, shares, label in NEW_T_ENTRIES:
        print(f"    ¥{nav:.4f} → 买 {shares:,} 份 | {label}")
    print(f"  {'─'*60}")

    cycle = 0
    try:
        while True:
            cycle += 1
            nav, date = fetch_current_nav()
            if nav is None:
                time.sleep(60)
                continue

            t_pnl_pct = (nav / T_ENTRY_NAV - 1) * 100
            overall_mv = TOTAL_SHARES * nav
            overall_pnl = overall_mv - POSITION_COST
            overall_pnl_pct = (overall_pnl / POSITION_COST) * 100

            triggered = []

            # T 仓止盈
            if nav >= T_TP1:
                triggered.append(("🟢 T止盈", f"+5% ¥{T_TP1:.4f} → 卖 {int(T_SHARES*0.6):,} 份（60%）"))
            if nav >= T_TP2:
                triggered.append(("🟢 T止盈", f"+8% ¥{T_TP2:.4f} → 卖 {int(T_SHARES*0.4):,} 份（40%）"))

            # 止损
            if nav <= T_SL:
                triggered.append(("🔴 T止损", f"-8% ¥{T_SL:.4f} → 全出 {T_SHARES:,} 份"))

            # 新 T 入场
            for entry_nav, entry_shares, label in NEW_T_ENTRIES:
                if nav <= entry_nav:
                    triggered.append(("🟢 新T入场", f"¥{entry_nav:.4f} → 买 {entry_shares:,} 份 | {label}"))

            if triggered:
                print(f"\n  {'='*55}")
                print(f"  ⚡ 触发 @ {datetime.now().strftime('%H:%M:%S')}")
                for tag, msg in triggered:
                    print(f"  {tag}: {msg}")
                    send_notification(f"012805 {tag}", msg)
                print(f"  整体盈亏: {overall_pnl_pct:+.2f}% | T仓盈亏: {t_pnl_pct:+.1f}%")
                print(f"  净值: ¥{nav:.4f} ({date})")
                print(f"  {'='*55}")
            else:
                if cycle % 4 == 0:
                    print(f"  [{datetime.now().strftime('%H:%M')}] ¥{nav:.4f} | "
                          f"整体 {overall_pnl_pct:+.1f}% | T仓 {t_pnl_pct:+.1f}% | 无触发")

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n  监控已停止")


if __name__ == "__main__":
    main()
