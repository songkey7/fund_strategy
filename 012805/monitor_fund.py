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
FUND_NAME = "广发恒生科技ETF联接C"


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

def push_to_wechat(title, content, token, template="html"):
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
    CONFIRMED_MARKET_AT_BASE = 65454.42
    total_shares = CONFIRMED_MARKET_AT_BASE / BASE_NAV

    overall_market = total_shares * nav
    overall_pnl = overall_market - POSITION_COST
    overall_pnl_pct = (overall_pnl / POSITION_COST) * 100

    has_alert = bool(t_status["triggered_tp"]) or t_status["sl_triggered"] or bool(new_triggered)

    title = f"恒生科技 {FUND_CODE}"
    if t_status["triggered_tp"]:
        title += " 止盈"
    if new_triggered:
        title += " 开仓"
    if t_status["sl_triggered"]:
        title += " 止损"

    css = """font-family:-apple-system,'PingFang SC',sans-serif;max-width:100%;color:#222;font-size:14px;line-height:1.6"""
    card = """background:#fff;border-radius:10px;padding:12px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,0.06)"""
    up = "#e53e3e"
    dn = "#38a169"

    def color(v):
        return up if v >= 0 else dn

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="{css};background:#f0f0f0;padding:12px;margin:0">

<div style="background:#1a1a2e;color:#fff;padding:16px;border-radius:12px;text-align:center;margin-bottom:10px">
<div style="font-size:12px;opacity:0.7">{date}</div>
<div style="font-size:12px;opacity:0.6;margin-top:4px">净值</div>
<div style="font-size:26px;font-weight:700;margin:2px 0">{nav:.4f}</div>
<div style="font-size:12px">{FUND_NAME}（{FUND_CODE}）</div>
</div>

<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">💰 整体持仓</div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">市值</span><span>¥{overall_market:,.0f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">盈亏</span><span style="color:{color(overall_pnl_pct)};font-weight:600">{overall_pnl_pct:+.1f}%</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">总投入</span><span>¥{POSITION_COST:,.0f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">浮动</span><span style="color:{color(overall_pnl)};font-weight:600">¥{overall_pnl:+,.0f}</span></div>
</div>

<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">📌 T仓 · 成本 ¥{T_COST:,.0f}</div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">均价</span><span>{T_ENTRY_NAV:.4f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">市值</span><span>¥{t_status['t_market']:,.0f}</span></div>
<div style="display:flex;justify-content:space-between;padding:2px 0"><span style="color:#999">盈亏</span><span style="color:{color(t_status['t_pnl_pct'])};font-weight:600">{t_status['t_pnl_pct']:+.1f}%</span></div>
</div>
"""

    # Alert section
    if has_alert:
        for tp in t_status["triggered_tp"]:
            proceeds = tp["sell_shares"] * nav
            html += f"""
<div style="background:#fff5f5;border:1px solid #fc8181;border-radius:10px;padding:12px;margin-bottom:8px">
<div style="font-size:15px;font-weight:700;color:#c53030;margin-bottom:6px">🟢 止盈触发 +{tp['pct']}%</div>
<div style="font-size:14px;font-weight:600;padding:2px 0">→ 卖出 {tp['sell_shares']:,} 份（{tp['sell_pct']}%）</div>
<div style="font-size:14px;font-weight:600;padding:2px 0">→ 回款约 ¥{proceeds:,.0f}</div>
</div>"""
        if t_status["sl_triggered"]:
            html += f"""
<div style="background:#fff5f5;border:1px solid #fc8181;border-radius:10px;padding:12px;margin-bottom:8px">
<div style="font-size:15px;font-weight:700;color:#c53030;margin-bottom:6px">🔴 止损触发 -8%</div>
<div style="font-size:14px;font-weight:600;padding:2px 0">→ 全出 {T_SHARES:,} 份</div>
<div style="font-size:14px;font-weight:600;padding:2px 0">→ 回收约 ¥{T_SHARES * nav:,.0f}</div>
</div>"""
        for entry in new_triggered:
            cost = entry["shares"] * nav
            html += f"""
<div style="background:#fff5f5;border:1px solid #fc8181;border-radius:10px;padding:12px;margin-bottom:8px">
<div style="font-size:15px;font-weight:700;color:#c53030;margin-bottom:6px">🟢 开仓触发 {entry['pct']:+.0f}%</div>
<div style="font-size:14px;font-weight:600;padding:2px 0">→ 买入 {entry['shares']:,} 份 @ {entry['nav']:.4f}</div>
<div style="font-size:14px;font-weight:600;padding:2px 0">→ 需资金约 ¥{cost:,.0f}</div>
</div>"""
    else:
        upcoming = []
        for tp in t_status["tp_levels"]:
            if not tp["triggered"]:
                upcoming.append(("止盈", tp["nav"], f"+{tp['pct']}% 卖 {tp['sell_pct']}%"))
        for entry in new_pending:
            upcoming.append(("开仓", entry["nav"], f"{entry['pct']:+.0f}% 买 {entry['shares']:,}份"))
        upcoming.sort(key=lambda x: abs(x[1] - nav))
        n = upcoming[0] if upcoming else ("—", 0, "")
        gap = abs(n[1] - nav)

        html += f"""
<div style="background:#f7fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;margin-bottom:8px;text-align:center">
<div style="color:#788;font-size:14px">⏳ 持仓观望，无触发</div>
<div style="color:#555;font-size:13px;margin-top:4px">下一步 {n[0]} {n[2]} @ {n[1]:.4f}（差 {gap:.4f}）</div>
</div>"""

    # T仓价位
    html += f"""
<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">T仓止盈/止损</div>"""
    for tp in t_status["tp_levels"]:
        gap = abs(tp["nav"] - nav)
        if tp["triggered"]:
            tag = '<span style="background:#c6f6d5;color:#276749;font-size:11px;padding:1px 5px;border-radius:3px">已触发</span>'
        else:
            tag = f'<span style="color:#aaa;font-size:12px">差{gap:.4f}</span>'
        html += f'<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #f2f2f2;font-size:13px"><span>+{tp["pct"]}% {tp["nav"]:.4f} 卖{tp["sell_pct"]}%</span>{tag}</div>'

    sl_gap = nav - t_status["sl_nav"]
    if t_status["sl_triggered"]:
        sl_tag = '<span style="background:#fed7d7;color:#9b2c2c;font-size:11px;padding:1px 5px;border-radius:3px">已触发</span>'
    else:
        sl_tag = f'<span style="color:#aaa;font-size:12px">距离{sl_gap:.4f}</span>'
    html += f'<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:13px"><span>-8% {t_status["sl_nav"]:.4f} 全出</span>{sl_tag}</div>'
    html += '</div>'

    # 新T入场
    html += f"""
<div style="{card}">
<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:6px">新开T仓点位</div>"""
    for entry in NEW_T_ENTRIES:
        gap = (entry["nav"] / nav - 1) * 100
        if nav <= entry["nav"]:
            tag = '<span style="background:#c6f6d5;color:#276749;font-size:11px;padding:1px 5px;border-radius:3px">已触发</span>'
        else:
            tag = f'<span style="color:#aaa;font-size:12px">距{gap:+.1f}%</span>'
        html += f'<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #f2f2f2;font-size:13px"><span>{entry["nav"]:.4f} ({entry["pct"]:+.0f}%) {entry["shares"]:,}份</span>{tag}</div>'
    html += '</div>'

    html += '</body></html>'
    return title, html


# ============================================================
# Main
# ============================================================

def main(pushplus_token=None):

    if pushplus_token is None:
        pushplus_token = os.environ.get("PUSHPLUS_TOKEN")

    print("=" * 60)
    print(f"  {FUND_NAME} 净值监控 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
