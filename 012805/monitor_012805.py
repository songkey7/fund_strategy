#!/usr/bin/env python3
"""
012805 净值监控 - 到达关键价位时发送提醒
每30分钟检查一次净值，触发关键价位时发出通知

使用方式: python3 monitor_012805.py
"""

import requests, json, time, subprocess, os, ssl
import urllib.request
from datetime import datetime

# ============================================================
# 配置参数
# ============================================================
FUND_CODE = "012805"

# 关键价位表 (净值 ¥0.7761)
# 触发买入的价位: 累计跌 2%, 3%, 5%
# 触发卖出的价位: 涨 3%, 5%, 8%
# 止损价位: 跌 8%
BASE_NAV = 0.7761
CHECK_INTERVAL = 1800  # 30分钟检查一次

# 活动操作
POSITION_COST = 71704.83
POSITION_SHARES = 83236.35
CURRENT_MARKET = POSITION_SHARES * BASE_NAV
POSITION_LOSS = POSITION_COST - CURRENT_MARKET
POSITION_LOSS_RATE = POSITION_LOSS / POSITION_COST

# T-Size: ~10% of holding
T_SHARES = 8000

# 关键价位
BUY_LEVELS = [
    {"price": 0.7606, "pct": -2.0, "trigger": "BUY", "size": T_SHARES, "note": "首次入场"},
    {"price": 0.7454, "pct": -4.0, "trigger": "BUY", "size": int(T_SHARES * 1.5), "note": "仓位加仓"},
    {"price": 0.7221, "pct": -7.0, "trigger": "BUY", "size": int(T_SHARES * 1.5), "note": "深度加仓"},
    {"price": 0.7062, "pct": -9.0, "trigger": "BUY", "size": int(T_SHARES * 2), "note": "重仓"},
]

SELL_LEVELS = [
    {"price": 0.7834, "pct": +3.0, "trigger": "SELL_30%", "size": int(T_SHARES * 0.3), "note": "+3%止盈(30%)"},
    {"price": 0.7986, "pct": +5.0, "trigger": "SELL_30%", "size": int(T_SHARES * 0.3), "note": "+5%止盈(30%)"},
    {"price": 0.8214, "pct": +8.0, "trigger": "SELL_40%", "size": int(T_SHARES * 0.4), "note": "+8%止盈(40%)"},
]

STOP_LOSS = {"price": 0.7000, "pct": 0, "size": "ALL", "note": "止损-8%"}

# 提醒方式
NOTIFY_METHOD = "system"  # 默认系统通知


def send_notification(title, message):
    """发送 macOS 系统通知"""
    try:
        script = f'display notification "{message}" with title "{title}" sound name "Hero"'
        subprocess.run(["osascript", "-e", script], check=True)
    except Exception as e:
        print(f"   [通知失败] {e}")


def fetch_current_nav():
    """获取最新净值"""
    try:
        url = f"https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery&fundCode={FUND_CODE}&pageIndex=1&pageSize=1&startDate={datetime.now().strftime('%Y-%m-%d')}&endDate={datetime.now().strftime('%Y-%m-%d')}"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={'Referer': 'https://fundf10.eastmoney.com/'})
        resp = urllib.request.urlopen(req, context=ctx, timeout=15)
        content = resp.read().decode('utf-8')
        start = content.index('(') + 1
        end = content.rindex(')')
        data = json.loads(content[start:end])
        latest = data['Data']['LSJZList'][0]
        nav = float(latest['DWJZ'])
        return nav, latest['FSRQ']
    except Exception as e:
        print(f"   [获取净值失败] {e}")
        return None, None


def check_levels(current_nav, all_levels):
    """检查当前净值是否触发任何价位"""
    triggered = []
    for lvl in all_levels:
        if lvl['pct'] < 0:  # BUY, 跌到目标以下
            if current_nav <= lvl['price']:
                triggered.append(lvl)
        elif lvl['pct'] > 0:  # SELL, 涨到目标以上
            if current_nav >= lvl['price']:
                triggered.append(lvl)
    return triggered


def format_level(lvl):
    """格式化行情输出"""
    if lvl['trigger'] == 'BUY':
        action = f"🟢 买 {lvl['size']:,} 份"
    elif lvl['trigger'] == 'SELL_30%':
        action = f"🔴 卖 {lvl['size']:,} 份 (锁利30%)"
    elif lvl['trigger'] == 'SELL_40%':
        action = f"🔴 卖 {lvl['size']:,} 份 (锁利40%)"
    else:
        action = "全部卖出"

    price = lvl['price']
    return f"  {action} @ ¥{price:.4f}  {lvl['note']}"


def main():
    print("=" * 65)
    print("  012805 净值监控")
    print("=" * 65)
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  当前净值: ¥{BASE_NAV:.4f} | 基准")
    print(f"  监控间隔: {CHECK_INTERVAL}秒 (每{CHECK_INTERVAL//60}分钟)")
    print()

    # 合并所有价位
    all_levels = BUY_LEVELS + SELL_LEVELS + [STOP_LOSS]

    print("  监控价位:")
    print(f"  {'价位':<12} {'操作':<12} {'份数':<12} 说明")
    print(f"  {'─'*40}")

    buy_info = [(l['price'], l) for l in BUY_LEVELS]
    sell_info = [(l['price'], l) for l in SELL_LEVELS]
    all_info = buy_info + sell_info + [(STOP_LOSS['price'], STOP_LOSS)]

    for _, lvl in sorted(all_info, key=lambda x: x[0]):
        print(f"  ¥{lvl['price']:<10.4f}   {lvl['trigger']:<12} "
              f"{str(lvl['size']):<12}  {lvl['note']}")

    print()
    print(f"  {'─'*65}")
    print(f"  紧急止损: ¥{STOP_LOSS['price']:.4f} (跌 -8% 全部清仓)")
    print()

    cycle_count = 0
    try:
        while True:
            cycle_count += 1
            nav, date = fetch_current_nav()
            if nav is None:
                time.sleep(60)
                continue

            # 计算持仓盈亏
            position_pnl = ((nav * POSITION_SHARES) - POSITION_COST)
            position_pnl_pct = (position_pnl / POSITION_COST) * 100

            triggered = check_levels(nav, all_levels)
            if triggered:
                print(f"\n  {'='*60}")
                print(f"  ⚡ 触发提醒 @ {datetime.now().strftime('%H:%M:%S')}")
                print(f"  {'='*60}")

                msg_title = f"012805"
                msg_body = f""

                for lvl in triggered:
                    nav_rounded = lvl['price']
                    notif_msg = format_level(lvl)
                    print(format_time(), notif_msg)
                    msg_body += notif_msg + "\n"

                print(f"  持仓盈亏: {position_pnl_pct:+.2f}% (¥{position_pnl:+.0f})")
                print(f"  净值: ¥{nav:.4f} ({date})")
                msg_body += f"\n"
                msg_body += f"持仓盈亏: {position_pnl_pct:+.2f}% (¥{position_pnl:+.0f})\n"
                msg_body += f"净值: ¥{nav:.4f} ({date})\n"

                # 发系统通知
                if triggered and triggered[0]['trigger'] == 'SELL_30%':
                    msg_title += " 🔴卖信号"
                elif triggered and triggered[0]['trigger'] == 'BUY':
                    msg_title += " 🟢买信号"
                sent = False
                for lvl in triggered:
                    send_notification(msg_title, format_level(lvl))
                    sent = True
                if not sent:
                    send_notification(msg_title, "触发关键价位")

            else:
                if cycle_count % 4 == 0:  # 每2小时输出状态
                    print(f"  [{datetime.now().strftime('%H:%M')}] ¥{nav:.4f} (盈亏:{position_pnl_pct:+.1f}%) "
                          f"无触发 | RS:{nav:.0f} ¥{nav:.4f}")

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n  监控已停止")


if __name__ == "__main__":
    main()
