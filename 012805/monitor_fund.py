#!/usr/bin/env python3
"""
012805 基金净值监控 (每日一次)
通过 GitHub Actions 每天自动检查净值并推送微信提醒
传输渠道: PushPlus Token for WeChat notification
"""

import requests, json, os, sys, argparse, re
from datetime import datetime

# ============================================================
# 整体持仓
# ============================================================
POSITION_COST = 71704.83

# ============================================================
# 当前 T 仓（已开）
# 2026-05-21: ¥5,000 @ ¥0.7688
# 2026-06-24: ¥5,000 @ ¥0.7212
# ============================================================
T_COST = 10000.00
T_ENTRY_NAV = 0.7442  # 加权均价
T_SHARES = 13437      # 约 13,437 份

# ============================================================
# 新开 T 仓点位（基准净值 ¥0.7761）
# ============================================================
BASE_NAV = 0.7761

NEW_T_ENTRIES = [
    {"nav": 0.7606, "pct": -2.0, "shares": 8000,  "label": "首次开仓"},
    {"nav": 0.7454, "pct": -4.0, "shares": 12000, "label": "加仓 1.5x"},
    {"nav": 0.7221, "pct": -7.0, "shares": 12000, "label": "加仓 1.5x"},
    {"nav": 0.7062, "pct": -9.0, "shares": 16000, "label": "重仓 2x"},
]

FUND_CODE = "012805"


# ============================================================
# Data fetching
# ============================================================

def fetch_latest_nav(fund_code):
    from datetime import timedelta
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')

    for attempt in range(3):
        try:
            url = (
                f"https://api.fund.eastmoney.com/f10/lsjz"
                f"?callback=jQuery&fundCode={fund_code}&pageIndex=1&pageSize=1"
                f"&startDate={start_date}&endDate={end_date}"
            )
            headers = {
                "Referer": "https://fundf10.eastmoney.com/",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            text = resp.text.strip()
            m = re.match(r'^\w+\((.*)\)$', text, re.DOTALL)
            if m:
                data = json.loads(m.group(1))
                records = data["Data"]["LSJZList"]
                if not records:
                    continue
                latest = records[0]
                nav = float(latest["DWJZ"])
                date = latest["FSRQ"]
                return nav, date
        except Exception as e:
            print(f"  获取净值失败 attempt {attempt+1}: {e}")
    return None, None


# ============================================================
# PushPlus 推送
# ============================================================

def push_to_wechat(title, content, token, template="markdown"):
    if not token:
        print("   WARNING: PUSHPLUS_TOKEN not configured")
        return

    url = "https://www.pushplus.plus/send"
    payload = {"token": token, "title": title, "content": content, "template": template}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"   PushPlus推送成功")
        else:
            print(f"   PushPlus推送失败: {resp.status_code}")
    except Exception as e:
        print(f"   PushPlus推送异常: {e}")


# ============================================================
# T 仓状态计算
# ============================================================

def t_position_status(nav):
    """返回当前 T 仓状态和触发信息"""
    t_market = T_SHARES * nav
    t_pnl = t_market - T_COST
    t_pnl_pct = (nav / T_ENTRY_NAV - 1) * 100

    tp_levels = [
        {"nav": T_ENTRY_NAV * 1.05, "pct": +5, "sell_pct": 60, "sell_shares": int(T_SHARES * 0.6), "triggered": False},
        {"nav": T_ENTRY_NAV * 1.08, "pct": +8, "sell_pct": 40, "sell_shares": int(T_SHARES * 0.4), "triggered": False},
    ]
    sl_nav = T_ENTRY_NAV * 0.92
    sl_triggered = False

    triggered_tp = []
    for tp in tp_levels:
        if nav >= tp["nav"]:
            tp["triggered"] = True
            triggered_tp.append(tp)
    if nav <= sl_nav:
        sl_triggered = True

    return {
        "t_market": t_market,
        "t_pnl": t_pnl,
        "t_pnl_pct": t_pnl_pct,
        "tp_levels": tp_levels,
        "sl_nav": sl_nav,
        "sl_triggered": sl_triggered,
        "triggered_tp": triggered_tp,
    }


# ============================================================
# 新开 T 仓检查
# ============================================================

def new_t_entry_status(nav):
    """检查触发了哪些新 T 入场点位"""
    triggered = []
    pending = []
    for entry in NEW_T_ENTRIES:
        gap_pct = (entry["nav"] / nav - 1) * 100
        if nav <= entry["nav"]:
            triggered.append(entry)
        else:
            pending.append({**entry, "gap_pct": gap_pct})
    return triggered, pending


# ============================================================
# 报告生成
# ============================================================

def generate_report(nav, date, t_status, new_triggered, new_pending):
    # 基于用户确认数据：净值 ¥0.7761 时市值 ¥65,454.42
    CONFIRMED_MARKET_AT_BASE = 65454.42
    total_shares = CONFIRMED_MARKET_AT_BASE / BASE_NAV

    overall_market = total_shares * nav
    overall_pnl = overall_market - POSITION_COST
    overall_pnl_pct = (overall_pnl / POSITION_COST) * 100

    # ---- 标题 ----
    has_alert = bool(t_status["triggered_tp"]) or t_status["sl_triggered"] or bool(new_triggered)
    title = "012805"
    if t_status["triggered_tp"]:
        title += " 🟢止盈"
    if t_status["sl_triggered"]:
        title += " 🔴止损"
    if new_triggered:
        title += " 🟢开仓"

    # ---- 正文 ----
    content = f"""## 📊 012805 净值监控

**数据日期**: {date}
**当前净值**: ¥{nav:.4f}

---

### 💰 整体持仓

| 项目 | 数值 |
|------|------|
| 总投入 | ¥{POSITION_COST:,.2f} |
| 市值 | ¥{overall_market:,.2f} |
| 盈亏 | ¥{overall_pnl:+,.0f} ({overall_pnl_pct:+.2f}%) |

---

### 📌 当前 T 仓（成本 ¥{T_COST:,.0f}，均价 ¥{T_ENTRY_NAV:.4f}，{T_SHARES:,} 份）

| 项目 | 数值 |
|------|------|
| T仓市值 | ¥{t_status['t_market']:,.0f} |
| T仓盈亏 | {t_status['t_pnl_pct']:+.1f}% |

"""

    # T 仓止盈
    content += "**止盈位：**\n"
    for tp in t_status["tp_levels"]:
        icon = "✅" if tp["triggered"] else "⏳"
        gap = abs(tp["nav"] - nav)
        content += f"- {icon} +{tp['pct']}% → ¥{tp['nav']:.4f} → 卖 {tp['sell_pct']}%（{tp['sell_shares']:,} 份）"
        if tp["triggered"]:
            content += f" ⚡已触发"
        else:
            content += f" 差 ¥{gap:.4f}"
        content += "\n"

    # T 仓止损
    sl_icon = "🔴" if t_status["sl_triggered"] else "⏳"
    sl_gap = nav - t_status["sl_nav"]
    content += f"\n**止损位：**\n- {sl_icon} -8% → ¥{t_status['sl_nav']:.4f} → 全出（{T_SHARES:,} 份）"
    if t_status["sl_triggered"]:
        content += " ⚡已触发"
    else:
        content += f" 距离 ¥{sl_gap:.4f}"
    content += "\n"

    # 新开 T 仓
    content += f"\n---\n\n### 🎯 新开 T 仓点位\n\n"
    if new_triggered:
        content += "**⚠️ 已触发入场：**\n"
        for entry in new_triggered:
            content += f"- 🟢 ¥{entry['nav']:.4f}（{entry['pct']:+.0f}%）→ 买入 {entry['shares']:,} 份 | {entry['label']}\n"
        content += "\n"

    if new_pending:
        content += "**等待触发：**\n"
        for entry in new_pending:
            content += f"- ¥{entry['nav']:.4f}（{entry['pct']:+.0f}%）→ {entry['shares']:,} 份 | 距当前 {entry['gap_pct']:+.1f}%\n"

    content += f"\n---\n> 012805 智能监控 | {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    return title, content


# ============================================================
# Main
# ============================================================

def main(pushplus_token=None):

    if pushplus_token is None:
        pushplus_token = os.environ.get("PUSHPLUS_TOKEN")

    print("=" * 60)
    print(f"  012805 净值监控 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    nav, date = fetch_latest_nav(FUND_CODE)
    if nav is None:
        print("  ❌ 获取净值失败")
        return

    print(f"  净值: ¥{nav:.4f} ({date})")

    t_status = t_position_status(nav)
    new_triggered, new_pending = new_t_entry_status(nav)

    title, content = generate_report(nav, date, t_status, new_triggered, new_pending)
    push_to_wechat(title, content, pushplus_token)

    # Console summary
    print(f"\n  T仓盈亏: {t_status['t_pnl_pct']:+.1f}%")
    for tp in t_status["tp_levels"]:
        if tp["triggered"]:
            print(f"  ⚡ T止盈触发: +{tp['pct']}% ¥{tp['nav']:.4f} → 卖 {tp['sell_pct']}%")
    if t_status["sl_triggered"]:
        print(f"  🔴 T止损触发: ¥{t_status['sl_nav']:.4f}")
    if new_triggered:
        for e in new_triggered:
            print(f"  🟢 新T入场: ¥{e['nav']:.4f} 买 {e['shares']:,}份")
    if not (t_status["triggered_tp"] or t_status["sl_triggered"] or new_triggered):
        print(f"  无触发")

    print(f"\n  ✅ 推送完成")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--push-token", help="PushPlus Token")
    args = parser.parse_args()
    main(args.push_token)
